
"""Terminal policy: evaluate_finalization + try_finalize + force-release + bag creation."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Dict, Optional, Tuple

from app.services import workflow_constants as WC
from app.services.workflow_append import append_workflow_event
from app.services.workflow_bag_lock import bag_write_lock
from app.services.workflow_read import (
    card_idle_fact_from_fold,
    card_lifecycle_events_for_card,
    load_events_for_bag,
    mechanical_bag_facts,
)
from app.services.workflow_txn import immediate_transaction, run_with_busy_retry
from app.utils.db_utils import BagRepository

LOGGER = logging.getLogger(__name__)


def evaluate_finalization(events: list) -> Tuple[bool, str, Dict[str, Any]]:
    """Pure: may emit BAG_FINALIZED?"""
    type_set = {e["event_type"] for e in events}
    if WC.EVENT_BAG_FINALIZED in type_set:
        return False, "already_finalized", {}
    has_blister = WC.EVENT_BLISTER_COMPLETE in type_set
    has_seal = WC.EVENT_SEALING_COMPLETE in type_set
    has_pack = WC.EVENT_PACKAGING_SNAPSHOT in type_set
    if has_blister and has_seal and has_pack:
        return True, "eligible", {}
    reasons = []
    if not has_blister:
        reasons.append("missing_blister")
    if not has_seal:
        reasons.append("missing_sealing")
    if not has_pack:
        reasons.append("missing_packaging")
    return False, "not_eligible", {"reasons": reasons}


def _qr_card_id_for_bag_assignment(events: list) -> Optional[int]:
    for e in reversed(events):
        if e["event_type"] == WC.EVENT_CARD_ASSIGNED:
            return int(e["payload"]["qr_card_id"])
    return None


def _dup_finalize_payload(conn: sqlite3.Connection, workflow_bag_id: int) -> Dict[str, Any]:
    facts = mechanical_bag_facts(conn, workflow_bag_id)
    fin = [e for e in facts["events"] if e["event_type"] == WC.EVENT_BAG_FINALIZED][0]
    return {
        "idempotent_duplicate": True,
        "bag": facts,
        "finalize_event": fin,
    }


def try_finalize(
    conn: sqlite3.Connection,
    workflow_bag_id: int,
    *,
    station_id: Optional[int] = None,
    user_id: Optional[int] = None,
    device_id: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Emit BAG_FINALIZED + release card in one transaction (or idempotent duplicate)."""
    lock = bag_write_lock(workflow_bag_id)

    def _inner() -> Tuple[str, Dict[str, Any]]:
        with lock:
            try:
                with immediate_transaction(conn):
                    events = load_events_for_bag(conn, workflow_bag_id)
                    ok, reason, details = evaluate_finalization(events)
                    if reason == "already_finalized":
                        LOGGER.info(
                            "workflow_finalize idempotent_duplicate bag_id=%s", workflow_bag_id
                        )
                        return ("duplicate", _dup_finalize_payload(conn, workflow_bag_id))
                    if not ok:
                        return (
                            "reject",
                            {
                                "code": "WORKFLOW_VALIDATION",
                                "details": {"reason": reason, **details},
                            },
                        )
                    qr_card_id = _qr_card_id_for_bag_assignment(events)
                    if qr_card_id is None:
                        return (
                            "reject",
                            {
                                "code": "WORKFLOW_VALIDATION",
                                "details": {"reason": "no_card_assignment"},
                            },
                        )
                    payload = {"finalization_rule_version": WC.FINALIZATION_RULE_VERSION}
                    append_workflow_event(
                        conn,
                        WC.EVENT_BAG_FINALIZED,
                        payload,
                        workflow_bag_id,
                        station_id=station_id,
                        user_id=user_id,
                        device_id=device_id,
                    )
                    conn.execute(
                        """
                        UPDATE qr_cards
                        SET status = ?, assigned_workflow_bag_id = NULL
                        WHERE id = ? AND assigned_workflow_bag_id = ?
                        """,
                        (WC.QR_CARD_STATUS_IDLE, qr_card_id, workflow_bag_id),
                    )
            except sqlite3.IntegrityError:
                LOGGER.info(
                    "workflow_finalize idempotent_duplicate IntegrityError bag_id=%s",
                    workflow_bag_id,
                )
                with immediate_transaction(conn):
                    return ("duplicate", _dup_finalize_payload(conn, workflow_bag_id))
            facts = mechanical_bag_facts(conn, workflow_bag_id)
            fin = [e for e in facts["events"] if e["event_type"] == WC.EVENT_BAG_FINALIZED][-1]
            LOGGER.info("workflow_finalize fresh_success bag_id=%s", workflow_bag_id)
            return (
                "ok",
                {
                    "idempotent_duplicate": False,
                    "bag": facts,
                    "finalize_event": fin,
                },
            )

    return run_with_busy_retry(_inner, op_name="try_finalize")


def force_release_card(
    conn: sqlite3.Connection,
    *,
    workflow_bag_id: int,
    qr_card_id: int,
    reason: str,
    user_id: Optional[int],
) -> Tuple[str, Dict[str, Any]]:
    """Admin: CARD_FORCE_RELEASED + qr_cards update; idempotent if already idle."""
    lock = bag_write_lock(workflow_bag_id)

    def _inner() -> Tuple[str, Dict[str, Any]]:
        with lock:
            with immediate_transaction(conn):
                events = load_events_for_bag(conn, workflow_bag_id)
                if any(e["event_type"] == WC.EVENT_BAG_FINALIZED for e in events):
                    return (
                        "reject",
                        {"code": "WORKFLOW_ALREADY_FINALIZED", "details": {}},
                    )
                fold = card_lifecycle_events_for_card(conn, qr_card_id)
                if card_idle_fact_from_fold(fold):
                    LOGGER.info(
                        "force_release idempotent_duplicate bag_id=%s card_id=%s",
                        workflow_bag_id,
                        qr_card_id,
                    )
                    return (
                        "duplicate",
                        {"idempotent_duplicate": True, "message": "already_released"},
                    )
                append_workflow_event(
                    conn,
                    WC.EVENT_CARD_FORCE_RELEASED,
                    {
                        "qr_card_id": qr_card_id,
                        "workflow_bag_id": workflow_bag_id,
                        "reason": reason,
                    },
                    workflow_bag_id,
                    user_id=user_id,
                )
                conn.execute(
                    """
                    UPDATE qr_cards
                    SET status = ?, assigned_workflow_bag_id = NULL
                    WHERE id = ? AND assigned_workflow_bag_id = ?
                    """,
                    (WC.QR_CARD_STATUS_IDLE, qr_card_id, workflow_bag_id),
                )
        LOGGER.info(
            "force_release fresh_success bag_id=%s card_id=%s", workflow_bag_id, qr_card_id
        )
        return ("ok", {"idempotent_duplicate": False})

    return run_with_busy_retry(_inner, op_name="force_release")


def create_workflow_bag_with_card(
    conn: sqlite3.Connection,
    *,
    product_id: Optional[int],
    box_number: Optional[str],
    bag_number: Optional[str],
    receipt_number: Optional[str],
    user_id: Optional[int],
    inventory_bag_id: Optional[int] = None,
    qr_card_id: Optional[int] = None,
) -> Tuple[int, int]:
    """
    Claim a specific idle card (or next idle), insert workflow_bags, emit CARD_ASSIGNED,
    update qr_cards — one txn.
    """
    from app.services.workflow_append import utc_ms_now

    with immediate_transaction(conn):
        if qr_card_id is None:
            row = conn.execute(
                """
                SELECT id FROM qr_cards WHERE status = ? ORDER BY id LIMIT 1
                """,
                (WC.QR_CARD_STATUS_IDLE,),
            ).fetchone()
            if row is None:
                raise RuntimeError("no_idle_card")
            qr_card_id = int(row["id"])
        now = utc_ms_now()
        cur = conn.execute(
            """
            INSERT INTO workflow_bags (
                created_at, product_id, box_number, bag_number, receipt_number, inventory_bag_id
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (now, product_id, box_number, bag_number, receipt_number, inventory_bag_id),
        )
        bag_id = int(cur.lastrowid)
        upd = conn.execute(
            """
            UPDATE qr_cards
            SET status = ?, assigned_workflow_bag_id = ?
            WHERE id = ? AND status = ?
            """,
            (WC.QR_CARD_STATUS_ASSIGNED, bag_id, qr_card_id, WC.QR_CARD_STATUS_IDLE),
        )
        if upd.rowcount != 1:
            raise RuntimeError("card_claim_failed")
        append_workflow_event(
            conn,
            WC.EVENT_CARD_ASSIGNED,
            {"qr_card_id": qr_card_id, "workflow_bag_id": bag_id},
            bag_id,
            user_id=user_id,
        )
    return bag_id, qr_card_id


def _normalize_workflow_receipt(raw: Optional[str]) -> Optional[str]:
    """Strip and cap length for ``workflow_bags.receipt_number``; empty → None."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    return s[:128]


def assign_inventory_bag_to_card(
    conn: sqlite3.Connection,
    *,
    inventory_bag_id: int,
    product_id: int,
    user_id: Optional[int],
    card_scan_token: Optional[str] = None,
    receipt_number_override: Optional[str] = None,
) -> Tuple[int, int]:
    """
    Link a receiving/shipment bag (``bags`` row) to the next idle QR card.

    Creates ``workflow_bags`` with ``inventory_bag_id`` set; denormalizes box/bag/receipt from receiving.
    """
    dup = conn.execute(
        "SELECT id FROM workflow_bags WHERE inventory_bag_id = ?",
        (inventory_bag_id,),
    ).fetchone()
    if dup is not None:
        raise RuntimeError("inventory_bag_already_assigned")

    inv = BagRepository.get_by_id(conn, inventory_bag_id)
    if not inv:
        raise RuntimeError("inventory_bag_not_found")
    if inv.get("tablet_type_id") is None:
        raise RuntimeError("inventory_bag_missing_tablet_type")

    prow = conn.execute(
        """
        SELECT tablet_type_id FROM product_details
        WHERE id = ? AND COALESCE(is_variety_pack, 0) = 0
        AND (is_bottle_product = 0 OR is_bottle_product IS NULL)
        """,
        (product_id,),
    ).fetchone()
    if prow is None:
        raise RuntimeError("invalid_product")
    if int(prow["tablet_type_id"]) != int(inv["tablet_type_id"]):
        raise RuntimeError("product_bag_tablet_type_mismatch")

    box_number = str(inv["box_number"]) if inv.get("box_number") is not None else None
    bag_number = str(inv["bag_number"]) if inv.get("bag_number") is not None else None
    override = _normalize_workflow_receipt(receipt_number_override)
    if override is not None:
        receipt_number = override
    else:
        receipt_number = (inv.get("receive_name") or "").strip() or None

    selected_qr_card_id: Optional[int] = None
    tok = (card_scan_token or "").strip()
    if tok:
        card = conn.execute(
            """
            SELECT id, status, assigned_workflow_bag_id
            FROM qr_cards
            WHERE scan_token = ?
            """,
            (tok,),
        ).fetchone()
        if card is None:
            raise RuntimeError("card_token_not_found")
        if card["status"] != WC.QR_CARD_STATUS_IDLE or card["assigned_workflow_bag_id"] is not None:
            raise RuntimeError("card_not_idle")
        selected_qr_card_id = int(card["id"])

    return create_workflow_bag_with_card(
        conn,
        product_id=product_id,
        box_number=box_number,
        bag_number=bag_number,
        receipt_number=receipt_number,
        user_id=user_id,
        inventory_bag_id=inventory_bag_id,
        qr_card_id=selected_qr_card_id,
    )
