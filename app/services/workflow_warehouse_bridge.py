"""
Sync QR workflow packaging counts into warehouse_submissions (packaged) for bag / PO totals.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Any, Dict, Optional

from app.services import workflow_constants as WC
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


def upsert_packaged_from_workflow_packaging(
    conn: sqlite3.Connection,
    workflow_bag_id: int,
    *,
    displays_made: int,
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
) -> Optional[Dict[str, Any]]:
    """If event is PACKAGING_SNAPSHOT, upsert packaged row. Returns bridge result or None."""
    if event_type != WC.EVENT_PACKAGING_SNAPSHOT:
        return None
    try:
        dm = int(payload.get("display_count") or 0)
    except (TypeError, ValueError):
        dm = 0
    return upsert_packaged_from_workflow_packaging(
        conn, workflow_bag_id, displays_made=dm
    )
