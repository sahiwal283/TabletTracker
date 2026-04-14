"""
Reporting analytics: PO flavor/shipment summaries, trends, and dimension slices.

Uses tablet_types.tablet_type_name as the primary "flavor" dimension for rows.
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.services.submission_query_service import apply_resolved_bag_fields, build_submission_base_query
from app.services.submission_calculator import calculate_submission_total_with_fallback


def _parse_date(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    try:
        datetime.strptime(s[:10], "%Y-%m-%d")
        return s[:10]
    except (ValueError, TypeError):
        return None


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
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


def _safe_avg(packed: int, bags: int) -> Optional[float]:
    if bags <= 0 or packed <= 0:
        return None
    return round(packed / bags, 2)


def _product_details_tuple(row: Dict[str, Any]) -> Tuple[Optional[Dict], Optional[Dict]]:
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


def packed_output_tablets(conn: sqlite3.Connection, sub: Dict[str, Any]) -> int:
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
    return int(
        calculate_submission_total_with_fallback(sub, pd_primary, pd_fallback)
    )


def _submission_report_rows(
    conn: sqlite3.Connection,
    po_id: Optional[int] = None,
    po_number: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    vendor_name: Optional[str] = None,
    tablet_type_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Load submission rows with joins for reporting (no row limit)."""
    query = build_submission_base_query(include_calculated_total=False)
    clauses = ["1=1"]
    params: List[Any] = []

    if po_id is not None:
        clauses.append("ws.assigned_po_id = ?")
        params.append(po_id)
    if po_number:
        clauses.append("po.po_number = ?")
        params.append(po_number)
    if vendor_name:
        clauses.append("po.vendor_name = ?")
        params.append(vendor_name)
    if tablet_type_id is not None:
        clauses.append("COALESCE(tt.id, tt_fallback.id, tt_bag.id) = ?")
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


def _flavor_id_name(
    sub: Dict[str, Any], conn: Optional[sqlite3.Connection] = None
) -> Tuple[Optional[int], str]:
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
        norm_expr = (
            "REPLACE(REPLACE(REPLACE(LOWER(TRIM({})), '-', ''), ' ', ''), '_', '')"
        )
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


def get_filter_metadata(conn: sqlite3.Connection) -> Dict[str, Any]:
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
    pos = [
        dict(r)
        for r in conn.execute(
            """
            SELECT id, po_number, COALESCE(vendor_name, '') AS vendor_name,
                   COALESCE(tablet_type, '') AS tablet_type,
                   COALESCE(internal_status, 'Active') AS internal_status
            FROM purchase_orders
            WHERE po_number IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 500
            """
        ).fetchall()
    ]
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
        "pos": pos,
        "date_bounds": {
            "min": b.get("dmin"),
            "max": b.get("dmax"),
        },
    }


def get_receives_for_po(conn: sqlite3.Connection, po_id: int) -> List[Dict[str, Any]]:
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


def _ordered_by_flavor(conn: sqlite3.Connection, po_id: int) -> Dict[int, Dict[str, Any]]:
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
    by_tt: Dict[int, Dict[str, Any]] = {}
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
) -> Tuple[Dict[Tuple[int, int], Dict[str, Any]], Dict[int, str]]:
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
    agg: Dict[Tuple[int, int], Dict[str, Any]] = {}
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


def _packed_by_flavor_receive(
    conn: sqlite3.Connection, po_id: int
) -> Dict[Tuple[Optional[int], int], int]:
    """(tablet_type_id, receive_id) -> packed (receive_id -1 = unassigned)."""
    subs = _submission_report_rows(conn, po_id=po_id)
    packed: Dict[Tuple[Optional[int], int], int] = {}
    for sub in subs:
        st = (sub.get("submission_type") or "packaged").lower()
        if st in ("bag", "machine"):
            continue
        tablets = packed_output_tablets(conn, sub)
        if tablets <= 0:
            continue
        tid, _ = _flavor_id_name(sub, conn)
        rid = sub.get("receive_id")
        if rid is None:
            rid = -1
        else:
            rid = int(rid)
        tt_key = tid if tid is not None else -2
        key = (tt_key, rid)
        packed[key] = packed.get(key, 0) + tablets
    return packed


def build_po_overview(conn: sqlite3.Connection, po_id: int) -> Dict[str, Any]:
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
    for (_rid, tid) in recv_bags.keys():
        flavor_ids.add(tid)
    for ttid, _rr in packed_map.keys():
        flavor_ids.add(ttid)
    flavor_ids.update(t for t in ordered_map.keys() if t > 0)

    rows_out: List[Dict[str, Any]] = []
    for tid in sorted(flavor_ids, key=_sort_name):
        if tid == -2:
            flavor_name = "Unmapped (no tablet type)"
        else:
            name_row = conn.execute(
                "SELECT tablet_type_name FROM tablet_types WHERE id = ?",
                (tid,),
            ).fetchone()
            flavor_name = (
                name_row["tablet_type_name"]
                if name_row
                else ordered_map.get(tid, {}).get("name", "Unknown")
            )

        ordered = int(ordered_map.get(tid, {}).get("ordered", 0))
        received = sum(
            v["received"] for (r, t), v in recv_bags.items() if t == tid
        )
        bags = sum(v["bags"] for (r, t), v in recv_bags.items() if t == tid)
        packed = sum(
            v for (tt, rr), v in packed_map.items() if tt == tid
        )
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


def build_po_shipments(conn: sqlite3.Connection, po_id: int) -> Dict[str, Any]:
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

    shipments: List[Dict[str, Any]] = []
    for rec in receives:
        rid = rec["id"]
        flavor_keys = set()
        for (r, t) in recv_bags.keys():
            if r == rid:
                flavor_keys.add(t)
        for (tt, r) in packed_map.keys():
            if r == rid:
                flavor_keys.add(tt)

        sec_rows: List[Dict[str, Any]] = []
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
    vendor_name: Optional[str] = None,
    po_id: Optional[int] = None,
    tablet_type_id: Optional[int] = None,
    bucket: str = "day",
) -> Dict[str, Any]:
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

    packed_by_day: Dict[str, int] = {}
    for sub in subs:
        st = (sub.get("submission_type") or "packaged").lower()
        if st in ("bag", "machine"):
            continue
        d = str(sub.get("filter_date") or sub.get("created_at", ""))[:10]
        if not d:
            continue
        n = packed_output_tablets(conn, sub)
        if n <= 0:
            continue
        packed_by_day[d] = packed_by_day.get(d, 0) + n

    # Received by receiving date (bags sum)
    rclause = "r.received_date IS NOT NULL AND DATE(r.received_date) >= ? AND DATE(r.received_date) <= ?"
    rparams: List[Any] = [df, dt]
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
    vendor_name: Optional[str] = None,
    po_id: Optional[int] = None,
    tablet_type_id: Optional[int] = None,
) -> Dict[str, Any]:
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
    by_flavor: Dict[int, int] = {}
    by_day_by_flavor: Dict[int, Dict[str, int]] = {}
    throughput_rows: List[Tuple[str, float, float, int]] = []
    # tuple: (day, duration_minutes, tablets_per_hour, tablets_packed)
    for sub in subs:
        st = (sub.get("submission_type") or "packaged").lower()
        if st in ("bag", "machine"):
            continue
        n = packed_output_tablets(conn, sub)
        if n <= 0:
            continue
        tid, fname = _flavor_id_name(sub, conn)
        if tid is None:
            tid = -2
        by_flavor[tid] = by_flavor.get(tid, 0) + n
        day = str(sub.get("filter_date") or sub.get("created_at", ""))[:10]
        if tid not in by_day_by_flavor:
            by_day_by_flavor[tid] = {}
        by_day_by_flavor[tid][day] = by_day_by_flavor[tid].get(day, 0) + n

        # Throughput derived from bag start/end times (when available).
        start_dt = _parse_dt(sub.get("bag_start_time"))
        end_dt = _parse_dt(sub.get("bag_end_time"))
        if not start_dt or not end_dt:
            continue
        minutes = (end_dt - start_dt).total_seconds() / 60.0
        # Guardrails against invalid/outlier durations.
        if minutes <= 0 or minutes > (12 * 60):
            continue
        tph = (n / (minutes / 60.0)) if minutes > 0 else 0.0
        throughput_rows.append((day, minutes, tph, n))

    flavor_list = []
    for tid, total in sorted(by_flavor.items(), key=lambda x: -x[1]):
        label = None
        if tid >= 0:
            nm = conn.execute(
                "SELECT tablet_type_name FROM tablet_types WHERE id = ?",
                (tid,),
            ).fetchone()
            label = nm["tablet_type_name"] if nm else str(tid)
        else:
            label = "Unmapped"
        flavor_list.append({"tablet_type_id": tid, "flavor": label, "packed": total})

    selected_series = []
    if tablet_type_id is not None:
        days = sorted(by_day_by_flavor.get(tablet_type_id, {}).keys())
        for d in days:
            selected_series.append(
                {"date": d, "packed": by_day_by_flavor[tablet_type_id].get(d, 0)}
            )

    throughput_summary = {
        "samples": 0,
        "avg_minutes": None,
        "median_minutes": None,
        "avg_tablets_per_hour": None,
        "total_tablets_measured": 0,
    }
    throughput_series: List[Dict[str, Any]] = []
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

        by_day_t: Dict[str, Dict[str, float]] = {}
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
        "throughput_summary": throughput_summary,
        "throughput_series": throughput_series,
    }
