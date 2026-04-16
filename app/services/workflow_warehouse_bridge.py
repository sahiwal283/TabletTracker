"""
Sync QR workflow packaging counts into warehouse_submissions (packaged) for bag / PO totals.

Also syncs sealing and blister station scans into ``warehouse_submissions`` / ``machine_counts``
(machine submission rows) keyed by receipt ``WORKFLOW-<workflow_bag_id>-seal`` / ``-blister``.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.services import workflow_constants as WC
from app.services.production_submission_helpers import (
    execute_machine_submission,
    refresh_purchase_order_header_aggregates,
)
from app.utils.eastern_datetime import utc_now_naive_string
from app.utils.receive_tracking import find_bag_for_submission

LOGGER = logging.getLogger(__name__)

WORKFLOW_RECEIPT_PREFIX = "WORKFLOW-"


def workflow_packaged_receipt_number(workflow_bag_id: int) -> str:
    return f"{WORKFLOW_RECEIPT_PREFIX}{int(workflow_bag_id)}"


def _coerce_int_opt(val) -> Optional[int]:
    if val is None or val == "":
        return None
    try:
        return int(str(val).strip())
    except (ValueError, TypeError):
        return None


def _utc_naive_from_event_ms(occurred_at_ms: Optional[int]) -> Optional[str]:
    if not occurred_at_ms:
        return None
    try:
        ms = int(occurred_at_ms)
    except (TypeError, ValueError):
        return None
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    return dt.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")


def _event_occurred_at_ms(conn: sqlite3.Connection, event_id: Optional[int]) -> Optional[int]:
    if not event_id:
        return None
    try:
        row = conn.execute(
            "SELECT occurred_at FROM workflow_events WHERE id = ?",
            (int(event_id),),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row:
        return None
    return int(dict(row).get("occurred_at") or 0) or None


def _station_claim_occurred_at_ms(
    conn: sqlite3.Connection,
    workflow_bag_id: int,
    station_id: Optional[int],
    up_to_occurred_at_ms: Optional[int],
) -> Optional[int]:
    if not station_id:
        return None
    try:
        if up_to_occurred_at_ms:
            row = conn.execute(
                """
                SELECT occurred_at
                FROM workflow_events
                WHERE workflow_bag_id = ?
                  AND station_id = ?
                  AND event_type = ?
                  AND occurred_at <= ?
                ORDER BY occurred_at DESC, id DESC
                LIMIT 1
                """,
                (
                    int(workflow_bag_id),
                    int(station_id),
                    WC.EVENT_BAG_CLAIMED,
                    int(up_to_occurred_at_ms),
                ),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT occurred_at
                FROM workflow_events
                WHERE workflow_bag_id = ?
                  AND station_id = ?
                  AND event_type = ?
                ORDER BY occurred_at DESC, id DESC
                LIMIT 1
                """,
                (int(workflow_bag_id), int(station_id), WC.EVENT_BAG_CLAIMED),
            ).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row:
        return None
    return int(dict(row).get("occurred_at") or 0) or None


def _update_receipt_station_times(
    conn: sqlite3.Connection,
    *,
    receipt_number: str,
    submission_type: str,
    bag_start_time: Optional[str],
    bag_end_time: Optional[str],
) -> None:
    # Some older schemas may not have both columns; degrade gracefully.
    try:
        conn.execute(
            """
            UPDATE warehouse_submissions
            SET bag_start_time = ?, bag_end_time = ?
            WHERE receipt_number = ? AND submission_type = ?
            """,
            (bag_start_time, bag_end_time, receipt_number, submission_type),
        )
        return
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute(
            """
            UPDATE warehouse_submissions
            SET bag_start_time = ?
            WHERE receipt_number = ? AND submission_type = ?
            """,
            (bag_start_time, receipt_number, submission_type),
        )
    except sqlite3.OperationalError:
        return


def upsert_packaged_from_workflow_packaging(
    conn: sqlite3.Connection,
    workflow_bag_id: int,
    *,
    displays_made: int,
    station_row: Optional[Dict[str, Any]] = None,
    event_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Replace the single packaged submission for this workflow bag (receipt WORKFLOW-<id>).

    Counts feed the same aggregates as the production form (displays × packages/display × tablets/package).
    """
    if displays_made < 0:
        return {"ok": False, "reason": "invalid_displays_made", "skipped": True}

    wb = conn.execute(
        "SELECT * FROM workflow_bags WHERE id = ?", (workflow_bag_id,)
    ).fetchone()
    if not wb:
        return {"ok": False, "reason": "workflow_bag_not_found", "skipped": True}
    wb = dict(wb)

    product_id = wb.get("product_id")
    if not product_id:
        LOGGER.warning(
            "workflow warehouse bridge: workflow_bag %s has no product_id; skip packaged upsert",
            workflow_bag_id,
        )
        return {"ok": False, "reason": "no_product_id", "skipped": True}

    product = conn.execute(
        """
        SELECT pd.id, pd.product_name, pd.packages_per_display, pd.tablets_per_package,
               tt.inventory_item_id, tt.id AS tablet_type_id
        FROM product_details pd
        JOIN tablet_types tt ON pd.tablet_type_id = tt.id
        WHERE pd.id = ?
        """,
        (product_id,),
    ).fetchone()
    if not product:
        return {"ok": False, "reason": "product_not_found", "skipped": True}
    product = dict(product)

    inv = product.get("inventory_item_id")
    if not inv:
        LOGGER.warning(
            "workflow warehouse bridge: product %s missing inventory_item_id", product_id
        )
        return {"ok": False, "reason": "no_inventory_item_id", "skipped": True}

    ppd = product.get("packages_per_display")
    tpp = product.get("tablets_per_package")
    if not ppd or not tpp or int(ppd) <= 0 or int(tpp) <= 0:
        LOGGER.warning(
            "workflow warehouse bridge: product %s missing package configuration", product_id
        )
        return {"ok": False, "reason": "incomplete_product_config", "skipped": True}

    tablet_type_id = int(product["tablet_type_id"])
    product_name = product["product_name"]

    bag_id = None
    assigned_po_id = None
    bag_label_count = 0
    needs_review = False
    box_number = wb.get("box_number")
    bag_number = wb.get("bag_number")
    box_i = _coerce_int_opt(box_number)
    bag_i = _coerce_int_opt(bag_number)

    inv_bid = wb.get("inventory_bag_id")
    if inv_bid:
        b = conn.execute(
            """
            SELECT b.id, b.bag_label_count, r.po_id AS recv_po_id
            FROM bags b
            LEFT JOIN small_boxes sb ON b.small_box_id = sb.id
            LEFT JOIN receiving r ON sb.receiving_id = r.id
            WHERE b.id = ?
            """,
            (inv_bid,),
        ).fetchone()
        if b:
            b = dict(b)
            bag_id = b["id"]
            assigned_po_id = b.get("recv_po_id")
            try:
                po_row = conn.execute(
                    "SELECT po_id FROM bags WHERE id = ?", (inv_bid,)
                ).fetchone()
                if po_row is not None:
                    pk = dict(po_row) if hasattr(po_row, "keys") else None
                    if pk and pk.get("po_id") is not None:
                        assigned_po_id = pk["po_id"]
                    elif po_row[0] is not None:
                        assigned_po_id = po_row[0]
            except sqlite3.OperationalError:
                pass
            lbl = b.get("bag_label_count")
            if lbl is None:
                try:
                    p2 = conn.execute(
                        "SELECT pill_count FROM bags WHERE id = ?", (inv_bid,)
                    ).fetchone()
                    lbl = p2["pill_count"] if p2 else 0
                except sqlite3.OperationalError:
                    lbl = 0
            bag_label_count = int(lbl or 0)
        else:
            LOGGER.warning(
                "workflow warehouse bridge: inventory_bag_id %s not found for workflow_bag %s",
                inv_bid,
                workflow_bag_id,
            )
    if bag_id is None and bag_i is not None:
        bag, needs_review, _err = find_bag_for_submission(
            conn, tablet_type_id, bag_i, box_i, submission_type="packaged"
        )
        if bag:
            bag_id = bag["id"]
            assigned_po_id = bag.get("po_id")
            bag_label_count = int(bag.get("bag_label_count") or 0)
            box_number = bag.get("box_number") or box_number
            bag_number = bag.get("bag_number") or bag_number

    if bag_id is None:
        LOGGER.warning(
            "workflow warehouse bridge: could not resolve receiving bag for workflow_bag %s",
            workflow_bag_id,
        )
        return {"ok": False, "reason": "no_bag_resolution", "skipped": True}

    receipt = workflow_packaged_receipt_number(workflow_bag_id)
    conn.execute(
        """
        DELETE FROM warehouse_submissions
        WHERE receipt_number = ? AND submission_type = 'packaged'
        """,
        (receipt,),
    )

    submission_date = datetime.now().date().isoformat()
    admin_notes = f"QR workflow packaging sync (workflow_bag_id={workflow_bag_id})"

    conn.execute(
        """
        INSERT INTO warehouse_submissions
        (employee_name, product_name, inventory_item_id, box_number, bag_number, bag_label_count,
         displays_made, packs_remaining, loose_tablets, damaged_tablets, submission_date, admin_notes,
         submission_type, bag_id, assigned_po_id, needs_review, receipt_number, bag_end_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'packaged', ?, ?, ?, ?, ?)
        """,
        (
            "QR workflow",
            product_name,
            inv,
            box_number,
            bag_number,
            bag_label_count,
            int(displays_made),
            0,
            0,
            0,
            submission_date,
            admin_notes,
            bag_id,
            assigned_po_id,
            1 if needs_review else 0,
            receipt,
            utc_now_naive_string(),
        ),
    )
    sid = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    station_id = int(station_row.get("id")) if station_row and station_row.get("id") else None
    end_ms = _event_occurred_at_ms(conn, event_id)
    start_ms = _station_claim_occurred_at_ms(conn, workflow_bag_id, station_id, end_ms)
    _update_receipt_station_times(
        conn,
        receipt_number=receipt,
        submission_type="packaged",
        bag_start_time=_utc_naive_from_event_ms(start_ms),
        bag_end_time=_utc_naive_from_event_ms(end_ms) or utc_now_naive_string(),
    )
    LOGGER.info(
        "workflow warehouse bridge: upsert packaged submission id=%s bag_id=%s workflow_bag=%s displays=%s",
        sid,
        bag_id,
        workflow_bag_id,
        displays_made,
    )
    return {
        "ok": True,
        "warehouse_submission_id": sid,
        "bag_id": bag_id,
        "assigned_po_id": assigned_po_id,
        "receipt_number": receipt,
    }


def sync_if_packaging_snapshot(
    conn: sqlite3.Connection,
    workflow_bag_id: int,
    event_type: str,
    payload: Dict[str, Any],
    station_row: Optional[Dict[str, Any]] = None,
    event_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """If event is PACKAGING_SNAPSHOT, upsert packaged row. Returns bridge result or None."""
    if event_type != WC.EVENT_PACKAGING_SNAPSHOT:
        return None
    try:
        dm = int(payload.get("display_count") or 0)
    except (TypeError, ValueError):
        dm = 0
    return upsert_packaged_from_workflow_packaging(
        conn,
        workflow_bag_id,
        displays_made=dm,
        station_row=station_row,
        event_id=event_id,
    )


def workflow_machine_lane_receipt_number(workflow_bag_id: int, lane: str) -> str:
    """Stable receipt for one workflow bag + lane (``seal`` or ``blister``)."""
    key = (lane or "").strip().lower()
    if key not in ("seal", "blister"):
        raise ValueError("lane must be 'seal' or 'blister'")
    return f"{WORKFLOW_RECEIPT_PREFIX}{int(workflow_bag_id)}-{key}"


def _tablet_type_for_product(conn: sqlite3.Connection, product_id: int) -> Optional[int]:
    row = conn.execute(
        "SELECT tablet_type_id FROM product_details WHERE id = ?",
        (int(product_id),),
    ).fetchone()
    if not row:
        return None
    r = dict(row)
    tid = r.get("tablet_type_id")
    return int(tid) if tid is not None else None


def _machine_role(conn: sqlite3.Connection, machine_id: Optional[int]) -> Optional[str]:
    if not machine_id:
        return None
    row = conn.execute(
        "SELECT machine_role FROM machines WHERE id = ?",
        (int(machine_id),),
    ).fetchone()
    if not row:
        return None
    return (dict(row).get("machine_role") or "sealing").strip().lower()


def _delete_matching_workflow_machine_count(
    conn: sqlite3.Connection,
    tablet_type_id: int,
    ws_row: Dict[str, Any],
) -> None:
    """Remove the ``machine_counts`` row most likely paired with this warehouse submission."""
    mid = ws_row.get("machine_id")
    mc_n = ws_row.get("displays_made")
    emp = ws_row.get("employee_name") or "QR workflow"
    cdate = ws_row.get("submission_date")
    box = ws_row.get("box_number")
    bag = ws_row.get("bag_number")

    if mid is not None:
        try:
            conn.execute(
                """
                DELETE FROM machine_counts WHERE id = (
                    SELECT id FROM machine_counts
                    WHERE tablet_type_id = ?
                      AND machine_id = ?
                      AND machine_count = ?
                      AND employee_name = ?
                      AND count_date = ?
                      AND COALESCE(CAST(box_number AS TEXT), '') = COALESCE(CAST(? AS TEXT), '')
                      AND COALESCE(CAST(bag_number AS TEXT), '') = COALESCE(CAST(? AS TEXT), '')
                    ORDER BY id DESC LIMIT 1
                )
                """,
                (tablet_type_id, mid, mc_n, emp, cdate, box, bag),
            )
            return
        except sqlite3.OperationalError:
            conn.execute(
                """
                DELETE FROM machine_counts WHERE id = (
                    SELECT id FROM machine_counts
                    WHERE tablet_type_id = ?
                      AND machine_id = ?
                      AND machine_count = ?
                      AND employee_name = ?
                      AND count_date = ?
                    ORDER BY id DESC LIMIT 1
                )
                """,
                (tablet_type_id, mid, mc_n, emp, cdate),
            )
            return

    try:
        conn.execute(
            """
            DELETE FROM machine_counts WHERE id = (
                SELECT id FROM machine_counts
                WHERE tablet_type_id = ?
                  AND machine_id IS NULL
                  AND machine_count = ?
                  AND employee_name = ?
                  AND count_date = ?
                  AND COALESCE(CAST(box_number AS TEXT), '') = COALESCE(CAST(? AS TEXT), '')
                  AND COALESCE(CAST(bag_number AS TEXT), '') = COALESCE(CAST(? AS TEXT), '')
                ORDER BY id DESC LIMIT 1
            )
            """,
            (tablet_type_id, mc_n, emp, cdate, box, bag),
        )
    except sqlite3.OperationalError:
        conn.execute(
            """
            DELETE FROM machine_counts WHERE id = (
                SELECT id FROM machine_counts
                WHERE tablet_type_id = ?
                  AND machine_id IS NULL
                  AND machine_count = ?
                  AND employee_name = ?
                  AND count_date = ?
                ORDER BY id DESC LIMIT 1
            )
            """,
            (tablet_type_id, mc_n, emp, cdate),
        )


def _reverse_po_line_for_tablets(conn: sqlite3.Connection, assigned_po_id: int, inventory_item_id, tablets: int) -> None:
    if not assigned_po_id or not inventory_item_id or not tablets or tablets <= 0:
        return
    line = conn.execute(
        """
        SELECT id, machine_good_count FROM po_lines
        WHERE po_id = ? AND inventory_item_id = ?
        LIMIT 1
        """,
        (int(assigned_po_id), inventory_item_id),
    ).fetchone()
    if not line:
        return
    lid = dict(line)["id"]
    conn.execute(
        """
        UPDATE po_lines
        SET machine_good_count = CASE
            WHEN machine_good_count >= ? THEN machine_good_count - ?
            ELSE 0
        END
        WHERE id = ?
        """,
        (tablets, tablets, lid),
    )


def _delete_workflow_machine_lane_rows(conn: sqlite3.Connection, receipt_number: str, tablet_type_id: int) -> Dict[str, Any]:
    """Remove machine submissions for this receipt, reverse PO deltas, drop paired machine_counts."""
    rows = conn.execute(
        """
        SELECT id, tablets_pressed_into_cards, assigned_po_id, inventory_item_id,
               displays_made, machine_id, submission_date, employee_name,
               box_number, bag_number
        FROM warehouse_submissions
        WHERE receipt_number = ? AND submission_type = 'machine'
        """,
        (receipt_number,),
    ).fetchall()
    po_ids: set = set()
    deleted_ws = 0
    for row in rows:
        r = dict(row)
        tid = int(r.get("tablets_pressed_into_cards") or 0)
        apo = r.get("assigned_po_id")
        inv = r.get("inventory_item_id")
        _reverse_po_line_for_tablets(conn, int(apo) if apo is not None else 0, inv, tid)
        _delete_matching_workflow_machine_count(conn, tablet_type_id, r)
        if apo:
            po_ids.add(int(apo))
        deleted_ws += 1

    conn.execute(
        """
        DELETE FROM warehouse_submissions
        WHERE receipt_number = ? AND submission_type = 'machine'
        """,
        (receipt_number,),
    )
    for po_id in po_ids:
        refresh_purchase_order_header_aggregates(conn, po_id)

    return {"deleted_warehouse_rows": deleted_ws, "po_ids_refreshed": sorted(po_ids)}


def upsert_machine_from_workflow_scan(
    conn: sqlite3.Connection,
    workflow_bag_id: int,
    *,
    count_total: int,
    station_row: Dict[str, Any],
    lane: str,
    expected_machine_role: str,
    event_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Replace the single machine submission for this workflow bag + lane (sealing or blister).

    ``station_row`` must include ``machine_id``, ``station_kind`` when available, and ``id``.
    """
    key = (lane or "").strip().lower()
    if key not in ("seal", "blister"):
        return {"ok": False, "reason": "invalid_lane", "skipped": True}
    exp = (expected_machine_role or "").strip().lower()
    if exp not in ("sealing", "blister"):
        return {"ok": False, "reason": "invalid_expected_role", "skipped": True}

    wb = conn.execute(
        "SELECT * FROM workflow_bags WHERE id = ?", (workflow_bag_id,)
    ).fetchone()
    if not wb:
        return {"ok": False, "reason": "workflow_bag_not_found", "skipped": True}
    wb = dict(wb)
    product_id = wb.get("product_id")
    if not product_id:
        LOGGER.warning(
            "workflow warehouse bridge: workflow_bag %s has no product_id; skip machine sync",
            workflow_bag_id,
        )
        return {"ok": False, "reason": "no_product_id", "skipped": True}

    tablet_type_id = _tablet_type_for_product(conn, int(product_id))
    if not tablet_type_id:
        return {"ok": False, "reason": "product_not_found", "skipped": True}

    station_kind = (station_row.get("station_kind") or "sealing").strip().lower()
    if key == "seal" and station_kind not in ("sealing", "combined"):
        return {
            "ok": False,
            "reason": "station_kind_mismatch",
            "skipped": True,
            "detail": "sealing event requires a sealing or combined station",
        }
    if key == "blister" and station_kind not in ("blister", "combined"):
        return {
            "ok": False,
            "reason": "station_kind_mismatch",
            "skipped": True,
            "detail": "blister event requires a blister or combined station",
        }

    machine_id = station_row.get("machine_id")
    if machine_id is None or machine_id == "":
        LOGGER.warning(
            "workflow warehouse bridge: station %s has no machine_id; skip machine sync",
            station_row.get("id"),
        )
        return {"ok": False, "reason": "no_station_machine_id", "skipped": True}
    machine_id = int(machine_id)

    role = _machine_role(conn, machine_id) or "sealing"
    if role != exp:
        return {
            "ok": False,
            "reason": "machine_role_mismatch",
            "skipped": True,
            "detail": f"station machine role is {role}, expected {exp}",
        }

    receipt = workflow_machine_lane_receipt_number(workflow_bag_id, key)
    lane_label = "sealing" if key == "seal" else "blister"
    admin_notes = (
        f"QR workflow {lane_label} sync (workflow_bag_id={workflow_bag_id}, station_id={station_row.get('id')})"
    )

    if count_total < 0:
        return {"ok": False, "reason": "invalid_count_total", "skipped": True}

    if count_total == 0:
        cleared = _delete_workflow_machine_lane_rows(conn, receipt, tablet_type_id)
        return {"ok": True, "cleared": True, "receipt_number": receipt, **cleared}

    box_number = wb.get("box_number")
    bag_number = wb.get("bag_number")
    _delete_workflow_machine_lane_rows(conn, receipt, tablet_type_id)

    data: Dict[str, Any] = {
        "product_id": int(product_id),
        "box_number": box_number,
        "bag_number": bag_number,
        "count_date": datetime.now().date().isoformat(),
        "machine_id": machine_id,
        "receipt_number": receipt,
        "confirm_reserved_override": True,
        "confirm_unassigned_submit": True,
        "machine_admin_notes": admin_notes,
    }

    entries = [{"machine_id": machine_id, "machine_count": int(count_total)}]
    result = execute_machine_submission(conn, data, "QR workflow", entries)
    if not result.get("success"):
        return {"ok": False, "reason": "execute_machine_failed", "detail": result}

    station_id = int(station_row.get("id")) if station_row.get("id") is not None else None
    end_ms = _event_occurred_at_ms(conn, event_id)
    start_ms = _station_claim_occurred_at_ms(conn, workflow_bag_id, station_id, end_ms)
    _update_receipt_station_times(
        conn,
        receipt_number=receipt,
        submission_type="machine",
        bag_start_time=_utc_naive_from_event_ms(start_ms),
        bag_end_time=_utc_naive_from_event_ms(end_ms) or utc_now_naive_string(),
    )

    LOGGER.info(
        "workflow warehouse bridge: machine %s sync workflow_bag=%s receipt=%s count=%s",
        lane_label,
        workflow_bag_id,
        receipt,
        count_total,
    )
    return {
        "ok": True,
        "receipt_number": receipt,
        "machine_id": machine_id,
        "count_total": int(count_total),
    }


def sync_workflow_warehouse_events(
    conn: sqlite3.Connection,
    workflow_bag_id: int,
    event_type: str,
    payload: Dict[str, Any],
    station_row: Dict[str, Any],
    *,
    event_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Run packaging and/or machine bridges for floor events.

    ``station_row`` is the resolved ``workflow_stations`` row (dict), including ``machine_id`` when set.
    """
    out: Dict[str, Any] = {}

    packaged = sync_if_packaging_snapshot(
        conn,
        workflow_bag_id,
        event_type,
        payload,
        station_row=station_row,
        event_id=event_id,
    )
    if packaged is not None:
        out["packaged"] = packaged

    try:
        ct = int(payload.get("count_total") or 0)
    except (TypeError, ValueError):
        ct = 0

    if event_type == WC.EVENT_SEALING_COMPLETE:
        out["machine_sealing"] = upsert_machine_from_workflow_scan(
            conn,
            workflow_bag_id,
            count_total=ct,
            station_row=station_row,
            lane="seal",
            expected_machine_role="sealing",
            event_id=event_id,
        )
    elif event_type == WC.EVENT_BLISTER_COMPLETE:
        out["machine_blister"] = upsert_machine_from_workflow_scan(
            conn,
            workflow_bag_id,
            count_total=ct,
            station_row=station_row,
            lane="blister",
            expected_machine_role="blister",
            event_id=event_id,
        )

    if not out:
        return None
    if len(out) == 1:
        return next(iter(out.values()))
    return out


def delete_synced_warehouse_artifacts_for_workflow_bag(
    conn: sqlite3.Connection, workflow_bag_id: int
) -> None:
    """
    Remove packaged + machine warehouse rows keyed by this bag's WORKFLOW-<id> receipts.

    Call before deleting a ``workflow_bags`` row so PO aggregates and paired ``machine_counts``
    stay consistent with the bridge's upsert/delete behavior.
    """
    wf = int(workflow_bag_id)
    packaged_receipt = workflow_packaged_receipt_number(wf)
    rows = conn.execute(
        """
        SELECT assigned_po_id FROM warehouse_submissions
        WHERE receipt_number = ? AND submission_type = 'packaged'
        """,
        (packaged_receipt,),
    ).fetchall()
    po_ids: set = set()
    for row in rows:
        r = dict(row)
        apo = r.get("assigned_po_id")
        if apo is not None:
            po_ids.add(int(apo))
    conn.execute(
        """
        DELETE FROM warehouse_submissions
        WHERE receipt_number = ? AND submission_type = 'packaged'
        """,
        (packaged_receipt,),
    )
    for po_id in po_ids:
        refresh_purchase_order_header_aggregates(conn, po_id)

    wb = conn.execute(
        "SELECT product_id FROM workflow_bags WHERE id = ?", (wf,)
    ).fetchone()
    pid = None
    if wb:
        pid = dict(wb).get("product_id")
    tid = _tablet_type_for_product(conn, int(pid)) if pid else None
    seal_r = workflow_machine_lane_receipt_number(wf, "seal")
    blist_r = workflow_machine_lane_receipt_number(wf, "blister")
    if tid:
        _delete_workflow_machine_lane_rows(conn, seal_r, tid)
        _delete_workflow_machine_lane_rows(conn, blist_r, tid)
        return
    for r in (seal_r, blist_r):
        n = conn.execute(
            """
            SELECT COUNT(*) AS c FROM warehouse_submissions
            WHERE receipt_number = ? AND submission_type = 'machine'
            """,
            (r,),
        ).fetchone()
        if not n or int(n["c"]) == 0:
            continue
        LOGGER.warning(
            "workflow warehouse bridge: bag %s has machine rows but no tablet_type_id; "
            "dropping receipt %s without full PO/machine_count pairing",
            wf,
            r,
        )
        conn.execute(
            """
            DELETE FROM warehouse_submissions
            WHERE receipt_number = ? AND submission_type = 'machine'
            """,
            (r,),
        )
