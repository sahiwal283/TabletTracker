"""
Reporting analytics: PO flavor/shipment summaries, trends, and dimension slices.

Uses tablet_types.tablet_type_name as the primary "flavor" dimension for rows.
"""

from __future__ import annotations

import hashlib
import math
import sqlite3
from datetime import datetime
from typing import Any

from app.services.submission_calculator import calculate_submission_total_with_fallback
from app.services.submission_query_service import apply_resolved_bag_fields, build_submission_base_query


def _parse_date(s: str | None) -> str | None:
    if not s:
        return None
    try:
        datetime.strptime(s[:10], "%Y-%m-%d")
        return s[:10]
    except (ValueError, TypeError):
        return None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    v = str(value).strip()
    if not v:
        return None
    # Handle common UTC-naive and ISO variants used in submissions.
    candidates = [v]
    if "T" in v and " " not in v:
        candidates.append(v.replace("T", " "))
    for c in candidates:
        try:
            return datetime.fromisoformat(c)
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(c, fmt)
            except ValueError:
                continue
    return None


def _safe_avg(packed: int, bags: int) -> float | None:
    if bags <= 0 or packed <= 0:
        return None
    return round(packed / bags, 2)


def _product_details_tuple(row: dict[str, Any]) -> tuple[dict | None, dict | None]:
    pd_primary = None
    if row.get("packages_per_display") is not None or row.get("tablets_per_package") is not None:
        pd_primary = {
            "packages_per_display": row.get("packages_per_display"),
            "tablets_per_package": row.get("tablets_per_package"),
        }
    pd_fallback = None
    if row.get("tablets_per_package_final") is not None:
        pd_fallback = {"tablets_per_package": row.get("tablets_per_package_final")}
    return pd_primary, pd_fallback


def packed_output_tablets(conn: sqlite3.Connection, sub: dict[str, Any]) -> int:
    """Tablets counted as 'packed' production output for reporting."""
    st = (sub.get("submission_type") or "packaged").lower()
    if st in ("bag", "machine"):
        return 0
    if st == "bottle":
        row = conn.execute(
            "SELECT COALESCE(SUM(tablets_deducted), 0) AS t FROM submission_bag_deductions WHERE submission_id = ?",
            (sub["id"],),
        ).fetchone()
        if row and (row["t"] or 0) > 0:
            return int(row["t"])
        tpb = 0
        pn = sub.get("product_name")
        if pn:
            cfg = conn.execute(
                """
                SELECT tablets_per_bottle
                FROM product_details
                WHERE TRIM(LOWER(product_name)) = TRIM(LOWER(?))
                """,
                (pn,),
            ).fetchone()
            if cfg:
                tpb = cfg["tablets_per_bottle"] or 0
        return int((sub.get("bottles_made") or 0) * tpb)

    pd_primary, pd_fallback = _product_details_tuple(sub)
    return int(calculate_submission_total_with_fallback(sub, pd_primary, pd_fallback))


def packed_tablets_allocations(conn: sqlite3.Connection, sub: dict[str, Any]) -> list[tuple[int, int, int]]:
    """
    Split packed output by tablet flavor (and receiving) for reporting.

    Variety-pack bottle submissions deduct from multiple reserved bags; each
    ``submission_bag_deductions`` row ties to a ``bags.tablet_type_id`` so we
    attribute tablets to the correct flavor/shipment instead of the variety
    product's primary tablet type on ``product_details``.

    Returns tuples of (tablet_type_id, tablets, receive_id) with receive_id -1
    when unknown.
    """
    st = (sub.get("submission_type") or "packaged").lower()
    if st in ("bag", "machine"):
        return []
    if st == "bottle":
        rows = conn.execute(
            """
            SELECT b.tablet_type_id AS tid,
                   r.id AS receive_id,
                   SUM(sbd.tablets_deducted) AS tablets
            FROM submission_bag_deductions sbd
            JOIN bags b ON b.id = sbd.bag_id
            LEFT JOIN small_boxes sb ON sb.id = b.small_box_id
            LEFT JOIN receiving r ON r.id = sb.receiving_id
            WHERE sbd.submission_id = ?
            GROUP BY b.tablet_type_id, r.id
            """,
            (sub["id"],),
        ).fetchall()
        alloc_total = sum(int(r["tablets"] or 0) for r in rows)
        if rows and alloc_total > 0:
            out: list[tuple[int, int, int]] = []
            for r in rows:
                tid = r["tid"]
                if tid is None:
                    tt_key = -2
                else:
                    tt_key = int(tid)
                rid = r["receive_id"]
                if rid is None:
                    recv = -1
                else:
                    recv = int(rid)
                t = int(r["tablets"] or 0)
                if t > 0:
                    out.append((tt_key, t, recv))
            return out
        n = packed_output_tablets(conn, sub)
        if n <= 0:
            return []
        tid, _ = _flavor_id_name(sub, conn)
        tt_key = tid if tid is not None else -2
        rid = sub.get("receive_id")
        recv = -1 if rid is None else int(rid)
        return [(tt_key, n, recv)]
    n = packed_output_tablets(conn, sub)
    if n <= 0:
        return []
    tid, _ = _flavor_id_name(sub, conn)
    tt_key = tid if tid is not None else -2
    rid = sub.get("receive_id")
    recv = -1 if rid is None else int(rid)
    return [(tt_key, n, recv)]


def _tablets_per_display_by_flavor(conn: sqlite3.Connection) -> dict[int, float]:
    """
    Build tablet_type_id -> tablets_per_display from product configuration.

    Uses the first valid product row per flavor; this is sufficient for
    display-equivalent analytics where flavor-level card config is stable.
    """
    rows = conn.execute(
        """
        SELECT tablet_type_id, packages_per_display, tablets_per_package
        FROM product_details
        WHERE tablet_type_id IS NOT NULL
          AND COALESCE(packages_per_display, 0) > 0
          AND COALESCE(tablets_per_package, 0) > 0
        ORDER BY id ASC
        """
    ).fetchall()
    out: dict[int, float] = {}
    for row in rows:
        tid = int(row["tablet_type_id"])
        if tid in out:
            continue
        out[tid] = float(row["packages_per_display"] * row["tablets_per_package"])
    return out


def _submission_report_rows(
    conn: sqlite3.Connection,
    po_id: int | None = None,
    po_number: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    vendor_name: str | None = None,
    tablet_type_id: int | None = None,
) -> list[dict[str, Any]]:
    """Load submission rows with joins for reporting (no row limit)."""
    query = build_submission_base_query(include_calculated_total=False)
    clauses = ["1=1"]
    params: list[Any] = []

    if po_id is not None:
        # Variety-pack bottle rows often omit assigned_po_id; tie them to the PO via
        # bag deductions → receiving instead of excluding them from PO reports.
        clauses.append(
            "("
            "ws.assigned_po_id = ? OR EXISTS ("
            " SELECT 1 FROM submission_bag_deductions sbd"
            " JOIN bags b ON b.id = sbd.bag_id"
            " JOIN small_boxes sb ON sb.id = b.small_box_id"
            " JOIN receiving r ON r.id = sb.receiving_id"
            " WHERE sbd.submission_id = ws.id AND r.po_id = ?"
            ")"
            ")"
        )
        params.append(po_id)
        params.append(po_id)
    if po_number:
        clauses.append("po.po_number = ?")
        params.append(po_number)
    if vendor_name:
        clauses.append("po.vendor_name = ?")
        params.append(vendor_name)
    if tablet_type_id is not None:
        # Include variety-pack bottle rows that deduct from this flavor's bags
        # even when the product row maps to a different tablet_type_id.
        clauses.append(
            "("
            "COALESCE(tt.id, tt_fallback.id, tt_bag.id) = ? OR EXISTS ("
            " SELECT 1 FROM submission_bag_deductions sbd"
            " JOIN bags b ON b.id = sbd.bag_id"
            " WHERE sbd.submission_id = ws.id AND b.tablet_type_id = ?"
            ")"
            ")"
        )
        params.append(tablet_type_id)
        params.append(tablet_type_id)
    if date_from:
        clauses.append("COALESCE(ws.submission_date, DATE(ws.created_at)) >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("COALESCE(ws.submission_date, DATE(ws.created_at)) <= ?")
        params.append(date_to)

    query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY ws.created_at ASC"
    rows = conn.execute(query, params).fetchall()
    out = []
    for row in rows:
        d = dict(row)
        apply_resolved_bag_fields(d)
        out.append(d)
    return out


def _flavor_id_name(sub: dict[str, Any], conn: sqlite3.Connection | None = None) -> tuple[int | None, str]:
    """
    Resolve flavor for a submission row. Prefer joined tablet_type_id / tablet_type_name
    (query uses COALESCE(product, inventory fallback, bag tablet type)).
    """
    tid = sub.get("tablet_type_id")
    name = sub.get("tablet_type_name")
    if tid is not None:
        tid = int(tid)
        if name:
            return tid, str(name)
        if conn:
            row = conn.execute(
                "SELECT tablet_type_name FROM tablet_types WHERE id = ?",
                (tid,),
            ).fetchone()
            if row and row["tablet_type_name"]:
                return tid, str(row["tablet_type_name"])
        return tid, (sub.get("product_name") or "Unknown").strip()

    # Last-resort mapping for legacy rows where SQL joins fail:
    # normalize product_name and match against both product_details.product_name
    # and tablet_types.tablet_type_name.
    product_name = (sub.get("product_name") or "").strip()
    if conn and product_name:
        norm_expr = "REPLACE(REPLACE(REPLACE(LOWER(TRIM({})), '-', ''), ' ', ''), '_', '')"
        row = conn.execute(
            f"""
            SELECT tt.id, tt.tablet_type_name
            FROM product_details pd
            JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            WHERE {norm_expr.format('pd.product_name')} = {norm_expr.format('?')}
            LIMIT 1
            """,
            (product_name,),
        ).fetchone()
        if not row:
            row = conn.execute(
                f"""
                SELECT id, tablet_type_name
                FROM tablet_types
                WHERE {norm_expr.format('tablet_type_name')} = {norm_expr.format('?')}
                LIMIT 1
                """,
                (product_name,),
            ).fetchone()
        if row:
            return int(row["id"]), str(row["tablet_type_name"])

    return None, (sub.get("product_name") or "Unknown").strip()


def get_report_fingerprint(conn: sqlite3.Connection) -> str:
    """Lightweight version string for polling 'what changed'."""
    r1 = conn.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM warehouse_submissions) AS ws_cnt,
          (SELECT IFNULL(MAX(id), 0) FROM warehouse_submissions) AS ws_max_id,
          (SELECT IFNULL(MAX(created_at), '') FROM warehouse_submissions) AS ws_max_ca,
          (SELECT COUNT(*) FROM bags) AS bag_cnt,
          (SELECT IFNULL(MAX(id), 0) FROM bags) AS bag_max_id
        """
    ).fetchone()
    raw = "|".join(str(x) for x in dict(r1).values())
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def get_filter_metadata(conn: sqlite3.Connection) -> dict[str, Any]:
    vendors = [
        r["vendor_name"]
        for r in conn.execute(
            """
            SELECT DISTINCT vendor_name FROM purchase_orders
            WHERE vendor_name IS NOT NULL AND TRIM(vendor_name) != ''
            ORDER BY vendor_name COLLATE NOCASE
            """
        ).fetchall()
    ]
    flavors = [
        {"id": r["id"], "name": r["tablet_type_name"]}
        for r in conn.execute(
            "SELECT id, tablet_type_name FROM tablet_types ORDER BY tablet_type_name COLLATE NOCASE"
        ).fetchall()
    ]
    pos_all = [
        dict(r)
        for r in conn.execute(
            """
            SELECT id, po_number, COALESCE(vendor_name, '') AS vendor_name,
                   COALESCE(tablet_type, '') AS tablet_type,
                   COALESCE(internal_status, 'Active') AS internal_status,
                   COALESCE(closed, 0) AS closed
            FROM purchase_orders
            WHERE po_number IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 500
            """
        ).fetchall()
    ]
    # Hide draft POs from analytics selectors entirely.
    pos_all = [p for p in pos_all if (p.get("internal_status") or "").lower() != "draft"]
    pos_open = [p for p in pos_all if not bool(p.get("closed"))]
    pos_closed = [p for p in pos_all if bool(p.get("closed"))]
    bounds = conn.execute(
        """
        SELECT
          MIN(COALESCE(submission_date, DATE(created_at))) AS dmin,
          MAX(COALESCE(submission_date, DATE(created_at))) AS dmax
        FROM warehouse_submissions
        """
    ).fetchone()
    b = dict(bounds) if bounds else {}
    return {
        "vendors": vendors,
        "flavors": flavors,
        "pos": pos_open,  # Backward-compatible key used by existing UI.
        "pos_open": pos_open,
        "pos_closed": pos_closed,
        "date_bounds": {
            "min": b.get("dmin"),
            "max": b.get("dmax"),
        },
    }


def get_receives_for_po(conn: sqlite3.Connection, po_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT r.id, r.received_date, r.receive_name, r.po_id,
               (
                 SELECT COUNT(*) + 1 FROM receiving r2
                 WHERE r2.po_id = r.po_id
                   AND (r2.received_date < r.received_date
                        OR (r2.received_date = r.received_date AND r2.id < r.id))
               ) AS receive_number
        FROM receiving r
        WHERE r.po_id = ?
        ORDER BY r.received_date ASC, r.id ASC
        """,
        (po_id,),
    ).fetchall()
    out = []
    for row in rows:
        d = dict(row)
        rd = d.get("received_date")
        date_str = str(rd)[:10] if rd else ""
        num = d.get("receive_number") or 1
        name = d.get("receive_name") or ""
        label = f"Shipment {int(num)}"
        if date_str:
            label += f" ({date_str})"
        if name:
            label += f" — {name}"
        d["label"] = label
        d["date"] = date_str
        out.append(d)
    return out


def _ordered_by_flavor(conn: sqlite3.Connection, po_id: int) -> dict[int, dict[str, Any]]:
    """Map tablet_type_id -> {ordered, line_name}."""
    rows = conn.execute(
        """
        SELECT pl.inventory_item_id, pl.line_item_name, SUM(COALESCE(pl.quantity_ordered, 0)) AS q
        FROM po_lines pl
        WHERE pl.po_id = ?
        GROUP BY pl.inventory_item_id, pl.line_item_name
        """,
        (po_id,),
    ).fetchall()
    by_tt: dict[int, dict[str, Any]] = {}
    for row in rows:
        r = dict(row)
        inv = r.get("inventory_item_id")
        q = int(r.get("q") or 0)
        line_name = r.get("line_item_name") or ""
        tt = None
        if inv:
            tt = conn.execute(
                "SELECT id, tablet_type_name FROM tablet_types WHERE inventory_item_id = ?",
                (inv,),
            ).fetchone()
        if tt:
            tid = int(tt["id"])
            if tid not in by_tt:
                by_tt[tid] = {"ordered": 0, "name": tt["tablet_type_name"], "line_name": line_name}
            by_tt[tid]["ordered"] += q
        else:
            # Unmapped line: synthetic key by hash of line name for display only
            synthetic = -(hash(line_name) % 10_000_000)
            if synthetic not in by_tt:
                by_tt[synthetic] = {"ordered": q, "name": line_name or "Unmapped line", "line_name": line_name}
            else:
                by_tt[synthetic]["ordered"] += q
    return by_tt


def _received_bags_by_flavor_receive(
    conn: sqlite3.Connection, po_id: int
) -> tuple[dict[tuple[int, int], dict[str, Any]], dict[int, str]]:
    """
    Keys: (receive_id, tablet_type_id) -> received, bags_count, flavor_name.
    Also returns receive_id -> label map.
    """
    rows = conn.execute(
        """
        SELECT
          r.id AS receive_id,
          r.received_date,
          r.receive_name,
          tt.id AS tablet_type_id,
          tt.tablet_type_name,
          SUM(COALESCE(b.bag_label_count, 0)) AS received_tablets,
          COUNT(b.id) AS bags_count
        FROM receiving r
        JOIN small_boxes sb ON sb.receiving_id = r.id
        JOIN bags b ON b.small_box_id = sb.id
        LEFT JOIN tablet_types tt ON b.tablet_type_id = tt.id
        WHERE r.po_id = ?
        GROUP BY r.id, tt.id
        """,
        (po_id,),
    ).fetchall()
    agg: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        r = dict(row)
        rid = r["receive_id"]
        tid = r["tablet_type_id"]
        if tid is None:
            tid = -1
            name = "Unknown"
        else:
            tid = int(tid)
            name = r["tablet_type_name"] or "Unknown"
        key = (rid, tid)
        if key not in agg:
            agg[key] = {
                "received": int(r["received_tablets"] or 0),
                "bags": int(r["bags_count"] or 0),
                "flavor_name": name,
            }
        else:
            agg[key]["received"] += int(r["received_tablets"] or 0)
            agg[key]["bags"] += int(r["bags_count"] or 0)
    recv_meta = {r["id"]: r["label"] for r in get_receives_for_po(conn, po_id)}
    return agg, recv_meta


def _packed_by_flavor_receive(conn: sqlite3.Connection, po_id: int) -> dict[tuple[int | None, int], int]:
    """(tablet_type_id, receive_id) -> packed (receive_id -1 = unassigned)."""
    subs = _submission_report_rows(conn, po_id=po_id)
    packed: dict[tuple[int | None, int], int] = {}
    for sub in subs:
        st = (sub.get("submission_type") or "packaged").lower()
        if st in ("bag", "machine"):
            continue
        for tid, tablets, rid in packed_tablets_allocations(conn, sub):
            if tablets <= 0:
                continue
            tt_key = tid if tid is not None else -2
            key = (tt_key, rid)
            packed[key] = packed.get(key, 0) + tablets
    return packed


def build_po_overview(conn: sqlite3.Connection, po_id: int) -> dict[str, Any]:
    """Total view: per-flavor rows + grand totals."""
    po = conn.execute(
        "SELECT id, po_number, vendor_name, tablet_type FROM purchase_orders WHERE id = ?",
        (po_id,),
    ).fetchone()
    if not po:
        return {"success": False, "error": "PO not found"}
    po = dict(po)

    ordered_map = _ordered_by_flavor(conn, po_id)
    recv_bags, _ = _received_bags_by_flavor_receive(conn, po_id)
    packed_map = _packed_by_flavor_receive(conn, po_id)

    def _sort_name(tid: int) -> str:
        if tid == -2:
            return "ZZZ-Unmapped packed"
        if tid < 0:
            return ordered_map.get(tid, {}).get("name") or "Line item"
        name_row = conn.execute(
            "SELECT tablet_type_name FROM tablet_types WHERE id = ?",
            (tid,),
        ).fetchone()
        return (name_row["tablet_type_name"] if name_row else "") or ""

    # Totals per flavor (across receives)
    flavor_ids = set()
    for _rid, tid in recv_bags.keys():
        flavor_ids.add(tid)
    for ttid, _rr in packed_map.keys():
        flavor_ids.add(ttid)
    flavor_ids.update(t for t in ordered_map.keys() if t > 0)

    rows_out: list[dict[str, Any]] = []
    for tid in sorted(flavor_ids, key=_sort_name):
        if tid == -2:
            flavor_name = "Unmapped (no tablet type)"
        else:
            name_row = conn.execute(
                "SELECT tablet_type_name FROM tablet_types WHERE id = ?",
                (tid,),
            ).fetchone()
            flavor_name = name_row["tablet_type_name"] if name_row else ordered_map.get(tid, {}).get("name", "Unknown")

        ordered = int(ordered_map.get(tid, {}).get("ordered", 0))
        received = sum(v["received"] for (r, t), v in recv_bags.items() if t == tid)
        bags = sum(v["bags"] for (r, t), v in recv_bags.items() if t == tid)
        packed = sum(v for (tt, rr), v in packed_map.items() if tt == tid)
        rows_out.append(
            {
                "tablet_type_id": tid,
                "flavor": flavor_name,
                "ordered": ordered,
                "received": received,
                "packed": packed,
                "bags_received": bags,
                "avg_packed_per_bag": _safe_avg(packed, bags),
            }
        )

    # Include synthetic / unmapped ordered lines not in tablet_types
    for syn_id, data in ordered_map.items():
        if syn_id <= 0 or syn_id in flavor_ids:
            continue
        rows_out.append(
            {
                "tablet_type_id": syn_id,
                "flavor": data.get("name") or "Line item",
                "ordered": int(data.get("ordered", 0)),
                "received": 0,
                "packed": 0,
                "bags_received": 0,
                "avg_packed_per_bag": None,
            }
        )

    g_ordered = sum(r["ordered"] for r in rows_out)
    g_received = sum(r["received"] for r in rows_out)
    g_packed = sum(r["packed"] for r in rows_out)
    g_bags = sum(r["bags_received"] for r in rows_out)

    return {
        "success": True,
        "po": {
            "id": po["id"],
            "po_number": po["po_number"],
            "vendor_name": po.get("vendor_name"),
            "tablet_type": po.get("tablet_type"),
        },
        "totals": {
            "ordered": g_ordered,
            "received": g_received,
            "packed": g_packed,
            "bags_received": g_bags,
            "avg_packed_per_bag": _safe_avg(g_packed, g_bags),
        },
        "rows": rows_out,
    }


def build_po_shipments(conn: sqlite3.Connection, po_id: int) -> dict[str, Any]:
    """Per-receive (shipment) sections with flavor rows."""
    base = build_po_overview(conn, po_id)
    if not base.get("success"):
        return base

    receives = get_receives_for_po(conn, po_id)
    recv_bags, _ = _received_bags_by_flavor_receive(conn, po_id)
    packed_map = _packed_by_flavor_receive(conn, po_id)
    ordered_map = _ordered_by_flavor(conn, po_id)

    def _shipment_row_sort_name(tid: int) -> str:
        if tid == -2:
            return "ZZZ-Unmapped packed"
        if tid == -1:
            return "Unknown bag flavor"
        nm = conn.execute(
            "SELECT tablet_type_name FROM tablet_types WHERE id = ?",
            (tid,),
        ).fetchone()
        return (nm["tablet_type_name"] if nm else "") or ""

    shipments: list[dict[str, Any]] = []
    for rec in receives:
        rid = rec["id"]
        flavor_keys = set()
        for r, t in recv_bags.keys():
            if r == rid:
                flavor_keys.add(t)
        for tt, r in packed_map.keys():
            if r == rid:
                flavor_keys.add(tt)

        sec_rows: list[dict[str, Any]] = []
        for tid in sorted(flavor_keys, key=_shipment_row_sort_name):
            if tid == -2:
                flavor_name = "Unmapped (no tablet type)"
            elif tid == -1:
                flavor_name = "Unknown"
            else:
                nm = conn.execute(
                    "SELECT tablet_type_name FROM tablet_types WHERE id = ?",
                    (tid,),
                ).fetchone()
                flavor_name = nm["tablet_type_name"] if nm else "Unknown"
            rb = recv_bags.get((rid, tid), {"received": 0, "bags": 0, "flavor_name": flavor_name})
            packed = packed_map.get((tid, rid), 0)
            sec_rows.append(
                {
                    "tablet_type_id": tid,
                    "flavor": flavor_name,
                    "ordered": int(ordered_map.get(tid, {}).get("ordered", 0)),
                    "received": rb["received"],
                    "packed": packed,
                    "bags_received": rb["bags"],
                    "avg_packed_per_bag": _safe_avg(packed, rb["bags"]),
                }
            )

        sub_received = sum(x["received"] for x in sec_rows)
        sub_packed = sum(x["packed"] for x in sec_rows)
        sub_bags = sum(x["bags_received"] for x in sec_rows)
        shipments.append(
            {
                "receive_id": rid,
                "label": rec.get("label"),
                "date": rec.get("date"),
                "receive_name": rec.get("receive_name"),
                "rows": sec_rows,
                "totals": {
                    "received": sub_received,
                    "packed": sub_packed,
                    "bags_received": sub_bags,
                    "avg_packed_per_bag": _safe_avg(sub_packed, sub_bags),
                },
            }
        )

    return {
        "success": True,
        "po": base["po"],
        "shipments": shipments,
    }


def build_trends(
    conn: sqlite3.Connection,
    date_from: str,
    date_to: str,
    vendor_name: str | None = None,
    po_id: int | None = None,
    tablet_type_id: int | None = None,
    bucket: str = "day",
) -> dict[str, Any]:
    """Time series: packed tablets and received tablets (by receive date)."""
    df = _parse_date(date_from)
    dt = _parse_date(date_to)
    if not df or not dt:
        return {"success": False, "error": "date_from and date_to (YYYY-MM-DD) required"}

    subs = _submission_report_rows(
        conn,
        po_id=po_id,
        vendor_name=vendor_name,
        tablet_type_id=tablet_type_id,
        date_from=df,
        date_to=dt,
    )

    tpd_map = _tablets_per_display_by_flavor(conn)
    packed_by_day: dict[str, int] = {}
    packed_displays_by_day: dict[str, float] = {}
    for sub in subs:
        st = (sub.get("submission_type") or "packaged").lower()
        if st in ("bag", "machine"):
            continue
        d = str(sub.get("filter_date") or sub.get("created_at", ""))[:10]
        if not d:
            continue
        for tid, part, _rid in packed_tablets_allocations(conn, sub):
            if part <= 0:
                continue
            if tablet_type_id is not None and tid != tablet_type_id:
                continue
            packed_by_day[d] = packed_by_day.get(d, 0) + part
            tpd = tpd_map.get(tid)
            if tpd and tpd > 0:
                packed_displays_by_day[d] = packed_displays_by_day.get(d, 0.0) + (part / tpd)

    # Received by receiving date (bags sum)
    rclause = "r.received_date IS NOT NULL AND DATE(r.received_date) >= ? AND DATE(r.received_date) <= ?"
    rparams: list[Any] = [df, dt]
    if vendor_name:
        rclause += " AND po.vendor_name = ?"
        rparams.append(vendor_name)
    if po_id is not None:
        rclause += " AND r.po_id = ?"
        rparams.append(po_id)
    tt_join = ""
    if tablet_type_id is not None:
        tt_join = " AND b.tablet_type_id = ?"
        rparams.append(tablet_type_id)

    q = f"""
        SELECT DATE(r.received_date) AS d, SUM(COALESCE(b.bag_label_count, 0)) AS received
        FROM receiving r
        JOIN purchase_orders po ON po.id = r.po_id
        JOIN small_boxes sb ON sb.receiving_id = r.id
        JOIN bags b ON b.small_box_id = sb.id
        WHERE {rclause} {tt_join}
        GROUP BY DATE(r.received_date)
    """
    received_rows = conn.execute(q, tuple(rparams)).fetchall()
    received_by_day = {str(dict(x)["d"]): int(dict(x)["received"] or 0) for x in received_rows}

    all_days = sorted(set(packed_by_day.keys()) | set(received_by_day.keys()))
    series = []
    for d in all_days:
        series.append(
            {
                "date": d,
                "packed": packed_by_day.get(d, 0),
                "packed_displays": round(packed_displays_by_day.get(d, 0.0), 2),
                "received": received_by_day.get(d, 0),
            }
        )

    return {
        "success": True,
        "bucket": bucket,
        "series": series,
    }


def build_dimensions(
    conn: sqlite3.Connection,
    date_from: str,
    date_to: str,
    vendor_name: str | None = None,
    po_id: int | None = None,
    tablet_type_id: int | None = None,
) -> dict[str, Any]:
    """Flavor-first analytics: totals in window + optional single-flavor breakdown."""
    df = _parse_date(date_from)
    dt = _parse_date(date_to)
    if not df or not dt:
        return {"success": False, "error": "date_from and date_to (YYYY-MM-DD) required"}

    subs = _submission_report_rows(
        conn,
        po_id=po_id,
        vendor_name=vendor_name,
        tablet_type_id=tablet_type_id,
        date_from=df,
        date_to=dt,
    )
    tpd_map = _tablets_per_display_by_flavor(conn)
    by_flavor: dict[int, int] = {}
    by_flavor_displays: dict[int, float] = {}
    by_day_by_flavor: dict[int, dict[str, int]] = {}
    by_day_by_flavor_displays: dict[int, dict[str, float]] = {}
    ripped_cards_by_flavor: dict[int, int] = {}
    ripped_cards_by_day: dict[str, int] = {}
    ripped_cards_total = 0
    throughput_rows: list[tuple[str, float, float, int]] = []
    # tuple: (day, duration_minutes, tablets_per_hour, tablets_packed)
    throughput_groups: dict[str, dict[str, Any]] = {}
    for sub in subs:
        st = (sub.get("submission_type") or "packaged").lower()
        n = packed_output_tablets(conn, sub)
        day = str(sub.get("filter_date") or sub.get("created_at", ""))[:10]

        # Throughput can span multiple rows: machine/bag rows may capture start,
        # while packaged rows may capture end and packed output.
        group_key = None
        if sub.get("bag_id"):
            group_key = f"bag:{sub.get('bag_id')}"
        elif sub.get("receipt_number"):
            group_key = f"receipt:{sub.get('receipt_number')}"
        if group_key:
            if group_key not in throughput_groups:
                throughput_groups[group_key] = {
                    "start": None,
                    "end": None,
                    "day": day,
                    "tablets": 0,
                }
            g = throughput_groups[group_key]
            start_dt = _parse_dt(sub.get("bag_start_time"))
            end_dt = _parse_dt(sub.get("bag_end_time"))
            if start_dt and (g["start"] is None or start_dt < g["start"]):
                g["start"] = start_dt
            if end_dt and (g["end"] is None or end_dt > g["end"]):
                g["end"] = end_dt
                g["day"] = str(end_dt.date())
            if n > 0:
                g["tablets"] += n

        # Flavor/day packed totals: split variety-pack bottle deductions per bag flavor.
        if st in ("bag", "machine") or n <= 0:
            continue
        for tid, part, _rid in packed_tablets_allocations(conn, sub):
            if part <= 0:
                continue
            if tablet_type_id is not None and tid != tablet_type_id:
                continue
            by_flavor[tid] = by_flavor.get(tid, 0) + part
            tpd = tpd_map.get(tid)
            if tpd and tpd > 0:
                by_flavor_displays[tid] = by_flavor_displays.get(tid, 0.0) + (part / tpd)
            if tid not in by_day_by_flavor:
                by_day_by_flavor[tid] = {}
            by_day_by_flavor[tid][day] = by_day_by_flavor[tid].get(day, 0) + part
            if tpd and tpd > 0:
                if tid not in by_day_by_flavor_displays:
                    by_day_by_flavor_displays[tid] = {}
                by_day_by_flavor_displays[tid][day] = by_day_by_flavor_displays[tid].get(day, 0.0) + (part / tpd)

    # Packaging loss (cards ripped/re-opened) is stored in cards_reopened
    # on packaged/repack submissions and should be tracked separately from output.
    # Fallback to loose_tablets for legacy rows where cards_reopened was not used.
    for sub in subs:
        st = (sub.get("submission_type") or "packaged").lower()
        if st not in ("packaged", "repack"):
            continue
        ripped_cards = int(sub.get("cards_reopened") or 0)
        if ripped_cards <= 0:
            ripped_cards = int(sub.get("loose_tablets") or 0)
        if ripped_cards <= 0:
            continue
        tid, _fname = _flavor_id_name(sub, conn)
        if tid is None:
            tid = -2
        if tablet_type_id is not None and tid != tablet_type_id:
            continue
        day = str(sub.get("filter_date") or sub.get("created_at", ""))[:10]
        ripped_cards_total += ripped_cards
        ripped_cards_by_flavor[tid] = ripped_cards_by_flavor.get(tid, 0) + ripped_cards
        if day:
            ripped_cards_by_day[day] = ripped_cards_by_day.get(day, 0) + ripped_cards

    flavor_list = []
    for tid, total in sorted(
        by_flavor.items(),
        key=lambda x: -(by_flavor_displays.get(x[0], 0.0) or float(x[1])),
    ):
        label = None
        if tid >= 0:
            nm = conn.execute(
                "SELECT tablet_type_name FROM tablet_types WHERE id = ?",
                (tid,),
            ).fetchone()
            label = nm["tablet_type_name"] if nm else str(tid)
        else:
            label = "Unmapped"
        flavor_list.append(
            {
                "tablet_type_id": tid,
                "flavor": label,
                "packed": total,
                "packed_displays": round(by_flavor_displays.get(tid, 0.0), 2),
                "ripped_cards": int(ripped_cards_by_flavor.get(tid, 0)),
            }
        )

    selected_series = []
    if tablet_type_id is not None:
        days = sorted(by_day_by_flavor.get(tablet_type_id, {}).keys())
        for d in days:
            selected_series.append(
                {
                    "date": d,
                    "packed": by_day_by_flavor[tablet_type_id].get(d, 0),
                    "packed_displays": round(by_day_by_flavor_displays.get(tablet_type_id, {}).get(d, 0.0), 2),
                }
            )
    ripped_by_flavor = []
    for tid, cards in sorted(ripped_cards_by_flavor.items(), key=lambda x: -x[1]):
        if tid >= 0:
            nm = conn.execute(
                "SELECT tablet_type_name FROM tablet_types WHERE id = ?",
                (tid,),
            ).fetchone()
            label = nm["tablet_type_name"] if nm else str(tid)
        else:
            label = "Unmapped"
        ripped_by_flavor.append(
            {
                "tablet_type_id": tid,
                "flavor": label,
                "ripped_cards": int(cards),
            }
        )
    ripped_series = [
        {"date": d, "ripped_cards": int(ripped_cards_by_day[d])} for d in sorted(ripped_cards_by_day.keys())
    ]
    total_packed_displays = round(sum(by_flavor_displays.values()), 2)
    loss_rate_cards_per_display = None
    if total_packed_displays > 0:
        loss_rate_cards_per_display = round(ripped_cards_total / total_packed_displays, 4)

    # Finalize grouped throughput samples.
    for g in throughput_groups.values():
        if not g.get("start") or not g.get("end"):
            continue
        minutes = (g["end"] - g["start"]).total_seconds() / 60.0
        if minutes <= 0 or minutes > (12 * 60):
            continue
        tabs = int(g.get("tablets") or 0)
        if tabs <= 0:
            continue
        tph = tabs / (minutes / 60.0)
        throughput_rows.append((g["day"], minutes, tph, tabs))

    throughput_summary = {
        "samples": 0,
        "avg_minutes": None,
        "median_minutes": None,
        "avg_tablets_per_hour": None,
        "total_tablets_measured": 0,
    }
    throughput_series: list[dict[str, Any]] = []
    if throughput_rows:
        minutes_values = sorted(x[1] for x in throughput_rows)
        tph_values = [x[2] for x in throughput_rows]
        total_tabs = sum(x[3] for x in throughput_rows)

        median = minutes_values[len(minutes_values) // 2]
        if len(minutes_values) % 2 == 0:
            median = (minutes_values[len(minutes_values) // 2 - 1] + minutes_values[len(minutes_values) // 2]) / 2.0

        throughput_summary = {
            "samples": len(throughput_rows),
            "avg_minutes": round(sum(minutes_values) / len(minutes_values), 2),
            "median_minutes": round(median, 2),
            "avg_tablets_per_hour": round(sum(tph_values) / len(tph_values), 2),
            "total_tablets_measured": int(total_tabs),
        }

        by_day_t: dict[str, dict[str, float]] = {}
        for day, minutes, tph, _tabs in throughput_rows:
            if day not in by_day_t:
                by_day_t[day] = {"count": 0.0, "minutes_total": 0.0, "tph_total": 0.0}
            by_day_t[day]["count"] += 1.0
            by_day_t[day]["minutes_total"] += minutes
            by_day_t[day]["tph_total"] += tph
        for day in sorted(by_day_t.keys()):
            agg = by_day_t[day]
            throughput_series.append(
                {
                    "date": day,
                    "avg_minutes": round(agg["minutes_total"] / agg["count"], 2),
                    "avg_tablets_per_hour": round(agg["tph_total"] / agg["count"], 2),
                    "samples": int(agg["count"]),
                }
            )

    return {
        "success": True,
        "top_flavors": flavor_list[:25],
        "selected_flavor_series": selected_series,
        "ripped_cards_total": int(ripped_cards_total),
        "ripped_cards_by_flavor": ripped_by_flavor[:25],
        "ripped_cards_series": ripped_series,
        "total_packed_displays": total_packed_displays,
        "loss_rate_cards_per_display": loss_rate_cards_per_display,
        "throughput_summary": throughput_summary,
        "throughput_series": throughput_series,
    }


def _percentile_sorted(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    n = len(sorted_vals)
    idx = int(math.ceil(p * n) - 1)
    idx = max(0, min(idx, n - 1))
    return round(sorted_vals[idx], 6)


def _summary_stats(rates: list[float], loss_sum: int, den_sum: int) -> dict[str, Any]:
    if not rates:
        return {
            "n": 0,
            "mean": None,
            "weighted_mean": None,
            "median": None,
            "p90": None,
            "sum_loss": 0,
            "sum_den": 0,
        }
    sr = sorted(rates)
    wmean = (loss_sum / den_sum) if den_sum > 0 else None
    return {
        "n": len(rates),
        "mean": round(sum(rates) / len(rates), 6),
        "weighted_mean": round(wmean, 6) if wmean is not None else None,
        "median": _percentile_sorted(sr, 0.5),
        "p90": _percentile_sorted(sr, 0.9),
        "sum_loss": int(loss_sum),
        "sum_den": int(den_sum),
    }


def aggregate_stage_yield(
    conn: sqlite3.Connection,
    date_from: str,
    date_to: str,
    tablet_type_id: int | None = None,
    machine_id: int | None = None,
) -> dict[str, Any]:
    """
    Summarize per-bag stage-yield over a date window (one row per bag in window).
    Excludes anomalous negative transitions for aggregate rate stats.
    """
    from app.services.bag_check_totals import compute_bag_check_totals

    if not _parse_date(date_from) or not _parse_date(date_to):
        return {"success": False, "error": "date_from and date_to (YYYY-MM-DD) are required"}
    d0, d1 = _parse_date(date_from), _parse_date(date_to)

    rows = conn.execute(
        """
        SELECT DISTINCT ws.bag_id AS bag_id
        FROM warehouse_submissions ws
        WHERE ws.bag_id IS NOT NULL
          AND SUBSTR(COALESCE(ws.created_at, ''), 1, 10) >= ?
          AND SUBSTR(COALESCE(ws.created_at, ''), 1, 10) <= ?
        """,
        (d0, d1),
    ).fetchall()
    bag_ids = [r["bag_id"] for r in rows]

    # Per-transition accumulators: lists of per-bag rates, and sum(loss), sum(denom) for weighted mean
    def collect() -> dict[str, Any]:
        b_s_t_r: list[float] = []
        s_p_t_r: list[float] = []
        b_p_t_r: list[float] = []
        b_s_t_loss = b_s_t_den = 0
        s_p_t_loss = s_p_t_den = 0
        b_p_t_loss = b_p_t_den = 0

        b_s_c_r: list[float] = []
        s_p_c_r: list[float] = []
        b_p_c_r: list[float] = []
        b_s_c_loss = b_s_c_den = 0
        s_p_c_loss = s_p_c_den = 0
        b_p_c_loss = b_p_c_den = 0

        bags_included = 0
        bags_all_zero = 0

        for bid in bag_ids:
            if tablet_type_id is not None:
                bro = conn.execute(
                    "SELECT tablet_type_id FROM bags WHERE id = ?",
                    (bid,),
                ).fetchone()
                tid = dict(bro).get("tablet_type_id") if bro else None
                if tid is None or int(tid) != int(tablet_type_id):
                    continue
            m = compute_bag_check_totals(conn, bid)
            if not m:
                continue
            B = m.get("machine_blister_tablets_total", 0) or 0
            S = m.get("machine_sealing_tablets_total", 0) or 0
            P = m.get("packaged_tablets_total", 0) or 0
            if B == 0 and S == 0 and P == 0:
                bags_all_zero += 1
                continue
            if machine_id is not None:
                pb = m.get("primary_blister_machine_id")
                ps = m.get("primary_sealing_machine_id")
                if pb != machine_id and ps != machine_id:
                    continue
            q = m.get("stage_yield_quality") or {}
            rates_t = m.get("stage_transition_loss_rates") or {}
            rates_c = m.get("stage_transition_loss_rates_cards") or {}
            losses_t = m.get("stage_transition_losses_tablets") or {}
            losses_c = m.get("stage_transition_losses_cards") or {}
            bl = m.get("blisters_from_blister_counter", 0) or 0
            cs = m.get("cards_from_sealing_counter", 0) or 0

            bags_included += 1

            if B > 0 and S > 0 and not q.get("negative_blister_to_sealing"):
                r = rates_t.get("blister_to_sealing")
                if r is not None and losses_t.get("blister_to_sealing") is not None:
                    b_s_t_r.append(float(r))
                    b_s_t_loss += int(losses_t["blister_to_sealing"] or 0)
                    b_s_t_den += B
                rc = rates_c.get("blister_to_sealing")
                if rc is not None and losses_c.get("blister_to_sealing") is not None and bl > 0:
                    b_s_c_r.append(float(rc))
                    b_s_c_loss += int(losses_c["blister_to_sealing"] or 0)
                    b_s_c_den += bl

            if S > 0 and P > 0 and not q.get("negative_sealing_to_packaged"):
                r = rates_t.get("sealing_to_packaged")
                if r is not None and losses_t.get("sealing_to_packaged") is not None:
                    s_p_t_r.append(float(r))
                    s_p_t_loss += int(losses_t["sealing_to_packaged"] or 0)
                    s_p_t_den += S
                rc = rates_c.get("sealing_to_packaged")
                if rc is not None and cs > 0 and losses_c.get("sealing_to_packaged") is not None:
                    s_p_c_r.append(float(rc))
                    s_p_c_loss += int(losses_c["sealing_to_packaged"] or 0)
                    s_p_c_den += cs

            if B > 0 and P > 0 and not q.get("negative_blister_to_packaged"):
                r = rates_t.get("blister_to_packaged")
                if r is not None and losses_t.get("blister_to_packaged") is not None:
                    b_p_t_r.append(float(r))
                    b_p_t_loss += int(losses_t["blister_to_packaged"] or 0)
                    b_p_t_den += B
                rc = rates_c.get("blister_to_packaged")
                if rc is not None and bl > 0 and losses_c.get("blister_to_packaged") is not None:
                    b_p_c_r.append(float(rc))
                    b_p_c_loss += int(losses_c["blister_to_packaged"] or 0)
                    b_p_c_den += bl

        return {
            "date_from": d0,
            "date_to": d1,
            "bags_with_submissions_in_window": len(bag_ids),
            "bags_touched": bags_included,
            "bags_skipped_all_zero": bags_all_zero,
            "filters": {
                "tablet_type_id": tablet_type_id,
                "machine_id": machine_id,
            },
            "tablets": {
                "blister_to_sealing": _summary_stats(b_s_t_r, b_s_t_loss, b_s_t_den),
                "sealing_to_packaged": _summary_stats(s_p_t_r, s_p_t_loss, s_p_t_den),
                "blister_to_packaged": _summary_stats(b_p_t_r, b_p_t_loss, b_p_t_den),
            },
            "cards": {
                "blister_to_sealing": _summary_stats(b_s_c_r, b_s_c_loss, b_s_c_den),
                "sealing_to_packaged": _summary_stats(s_p_c_r, s_p_c_loss, s_p_c_den),
                "blister_to_packaged": _summary_stats(b_p_c_r, b_p_c_loss, b_p_c_den),
            },
        }

    return {"success": True, **collect()}
