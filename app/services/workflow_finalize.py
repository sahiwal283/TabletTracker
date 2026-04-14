
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
) -> Tuple[int, int]:
    """
    Claim one idle card, insert workflow_bags, emit CARD_ASSIGNED, update qr_cards — one txn.
    """
    from app.services.workflow_append import utc_ms_now

    with immediate_transaction(conn):
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
            INSERT INTO workflow_bags (created_at, product_id, box_number, bag_number, receipt_number)
            VALUES (?, ?, ?, ?, ?)
            """,
            (now, product_id, box_number, bag_number, receipt_number),
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
