
"""Anonymous floor JSON API + station HTML (no CSRF on JSON)."""

from __future__ import annotations

import json
import logging
import sqlite3

from flask import Blueprint, render_template, request, session

from app.services import workflow_constants as WC
from app.services.production_submission_helpers import ProductionSubmissionError
from app.services.workflow_append import append_workflow_event
from app.services.workflow_finalize import try_finalize
from app.services.workflow_http import rate_limit_floor, read_json_body, workflow_json
from app.services.workflow_product_mapping import (
    ensure_workflow_bag_product_for_flow,
    production_flow_for_event_or_station,
)
from app.services.workflow_read import (
    display_stage_label,
    floor_bag_verification,
    mechanical_bag_facts,
    production_flow_for_bag,
    progress_summary,
)
from app.services.workflow_txn import run_with_busy_retry
from app.services.workflow_warehouse_bridge import sync_workflow_warehouse_events
from app.utils.db_utils import get_db

LOGGER = logging.getLogger(__name__)

bp = Blueprint("workflow_floor", __name__, url_prefix="/workflow")


def _log_floor_correlation(route: str, data: dict) -> None:
    """Log device_id / page_session_id for support correlation only (not identity)."""
    device_id = (data.get("device_id") or "").strip() or None
    page_session_id = (data.get("page_session_id") or "").strip() or None
    if device_id or page_session_id:
        LOGGER.info(
            "workflow_floor %s device_id=%s page_session_id=%s",
            route,
            device_id,
            page_session_id,
        )


def _resolve_station(conn, station_token: str):
    """Resolve station row; includes linked production machine name when ``machine_id`` is set."""
    try:
        return conn.execute(
            """
            SELECT ws.id, ws.label, ws.station_scan_token, ws.machine_id AS machine_id,
                   m.machine_name AS machine_name,
                   COALESCE(ws.station_kind, 'sealing') AS station_kind
            FROM workflow_stations ws
            LEFT JOIN machines m ON m.id = ws.machine_id
            WHERE ws.station_scan_token = ?
            """,
            (station_token,),
        ).fetchone()
    except sqlite3.OperationalError:
        return conn.execute(
            """
            SELECT id, label, station_scan_token, NULL AS machine_id, NULL AS machine_name,
                   'sealing' AS station_kind
            FROM workflow_stations
            WHERE station_scan_token = ?
            """,
            (station_token,),
        ).fetchone()


def _resolve_card(conn, card_token: str):
    return conn.execute(
        "SELECT * FROM qr_cards WHERE scan_token = ?",
        (card_token,),
    ).fetchone()


def _is_pause_workflow_event(event_type: str, payload: dict) -> bool:
    """True if this event represents an end-of-day / paused handoff at the station."""
    if event_type == WC.EVENT_PACKAGING_SNAPSHOT:
        return (payload.get("reason") or "").strip() == "paused_end_of_day"
    if event_type in (
        WC.EVENT_BLISTER_COMPLETE,
        WC.EVENT_SEALING_COMPLETE,
        WC.EVENT_BOTTLE_HANDPACK_COMPLETE,
        WC.EVENT_BOTTLE_CAP_SEAL_COMPLETE,
        WC.EVENT_BOTTLE_STICKER_COMPLETE,
    ):
        meta = payload.get("metadata")
        if isinstance(meta, dict):
            if meta.get("paused") or meta.get("reason") == "end_of_day":
                return True
        return False
    return False


def _occupancy_lane_finished_at_station(
    conn: sqlite3.Connection,
    *,
    station_id: int,
    workflow_bag_id: int,
    station_kind: str,
) -> bool:
    """
    True when the active session at this station has completed the lane step for this station type
    (non-pause machine submit), so the physical station should show idle for the next bag.

    Without this, occupancy stayed forever on the latest BAG_CLAIMED row even after BLISTER_COMPLETE,
    blocking new scans at blister/sealing lanes.
    """
    kind = (station_kind or "sealing").strip().lower()
    rows = conn.execute(
        """
        SELECT event_type, payload
        FROM workflow_events
        WHERE workflow_bag_id = ? AND station_id = ?
        ORDER BY occurred_at ASC, id ASC
        """,
        (workflow_bag_id, station_id),
    ).fetchall()
    session_active = False
    for row in rows:
        et = row["event_type"]
        try:
            pl = json.loads(row["payload"]) if row["payload"] else {}
        except (json.JSONDecodeError, TypeError):
            pl = {}
        if not isinstance(pl, dict):
            pl = {}
        if et in (WC.EVENT_BAG_CLAIMED, WC.EVENT_STATION_RESUMED):
            session_active = True
            continue
        if not session_active:
            continue
        if kind == "blister":
            if et == WC.EVENT_BLISTER_COMPLETE and not _is_pause_workflow_event(et, pl):
                return True
        elif kind == "sealing":
            if et == WC.EVENT_SEALING_COMPLETE and not _is_pause_workflow_event(et, pl):
                return True
        elif kind == "combined":
            if et == WC.EVENT_SEALING_COMPLETE and not _is_pause_workflow_event(et, pl):
                return True
        elif kind == "packaging":
            if et == WC.EVENT_PACKAGING_TAKEN_FOR_ORDER:
                return True
            if et == WC.EVENT_PACKAGING_SNAPSHOT and not _is_pause_workflow_event(et, pl):
                return True
        elif kind == "bottle_handpack":
            if et == WC.EVENT_BOTTLE_HANDPACK_COMPLETE and not _is_pause_workflow_event(et, pl):
                return True
        elif kind == "bottle_cap_seal":
            if et == WC.EVENT_BOTTLE_CAP_SEAL_COMPLETE and not _is_pause_workflow_event(et, pl):
                return True
        elif kind == "bottle_stickering":
            if et == WC.EVENT_BOTTLE_STICKER_COMPLETE and not _is_pause_workflow_event(et, pl):
                return True
    return False


def _station_pause_at_ms(
    conn: sqlite3.Connection, workflow_bag_id: int, station_id: int
) -> int | None:
    """When resume is required, Unix ms of the pause-style submit that caused it."""
    if not _station_needs_resume(conn, workflow_bag_id, station_id):
        return None
    rows = conn.execute(
        """
        SELECT event_type, payload, occurred_at
        FROM workflow_events
        WHERE workflow_bag_id = ? AND station_id = ?
        ORDER BY occurred_at ASC, id ASC
        """,
        (workflow_bag_id, station_id),
    ).fetchall()
    last_pause: int | None = None
    for row in rows:
        et = row["event_type"]
        try:
            pl = json.loads(row["payload"]) if row["payload"] else {}
        except (json.JSONDecodeError, TypeError):
            pl = {}
        if not isinstance(pl, dict):
            pl = {}
        if et == WC.EVENT_BAG_CLAIMED:
            last_pause = None
        elif et == WC.EVENT_STATION_RESUMED:
            last_pause = None
        elif et in (
            WC.EVENT_BLISTER_COMPLETE,
            WC.EVENT_SEALING_COMPLETE,
            WC.EVENT_BOTTLE_HANDPACK_COMPLETE,
            WC.EVENT_BOTTLE_CAP_SEAL_COMPLETE,
            WC.EVENT_BOTTLE_STICKER_COMPLETE,
            WC.EVENT_PACKAGING_SNAPSHOT,
        ):
            if _is_pause_workflow_event(et, pl):
                try:
                    last_pause = int(row["occurred_at"])
                except (TypeError, ValueError):
                    last_pause = None
            else:
                last_pause = None
    return last_pause


def _station_needs_resume(conn: sqlite3.Connection, workflow_bag_id: int, station_id: int) -> bool:
    """
    After a pause-style count/snapshot, operators must emit STATION_RESUMED before more counts.
    Walk station-scoped events in order; last pause without a later resume means resume is required.
    """
    rows = conn.execute(
        """
        SELECT event_type, payload
        FROM workflow_events
        WHERE workflow_bag_id = ? AND station_id = ?
        ORDER BY occurred_at ASC, id ASC
        """,
        (workflow_bag_id, station_id),
    ).fetchall()
    needs_resume = False
    for row in rows:
        et = row["event_type"]
        try:
            pl = json.loads(row["payload"]) if row["payload"] else {}
        except (json.JSONDecodeError, TypeError):
            pl = {}
        if not isinstance(pl, dict):
            pl = {}
        if et == WC.EVENT_BAG_CLAIMED:
            needs_resume = False
        elif et == WC.EVENT_STATION_RESUMED:
            needs_resume = False
        elif et in (
            WC.EVENT_BLISTER_COMPLETE,
            WC.EVENT_SEALING_COMPLETE,
            WC.EVENT_BOTTLE_HANDPACK_COMPLETE,
            WC.EVENT_BOTTLE_CAP_SEAL_COMPLETE,
            WC.EVENT_BOTTLE_STICKER_COMPLETE,
            WC.EVENT_PACKAGING_SNAPSHOT,
        ):
            if _is_pause_workflow_event(et, pl):
                needs_resume = True
            else:
                needs_resume = False
    return needs_resume


def _station_has_claimed_bag(
    conn: sqlite3.Connection, workflow_bag_id: int, station_id: int
) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM workflow_events
        WHERE workflow_bag_id = ?
          AND event_type = ?
          AND station_id = ?
        LIMIT 1
        """,
        (workflow_bag_id, WC.EVENT_BAG_CLAIMED, station_id),
    ).fetchone()
    return bool(row)


def _station_occupancy_started_at(
    conn: sqlite3.Connection, workflow_bag_id: int, station_id: int
) -> int | None:
    row = conn.execute(
        """
        SELECT occurred_at
        FROM workflow_events
        WHERE workflow_bag_id = ?
          AND station_id = ?
          AND event_type IN (?, ?)
        ORDER BY occurred_at DESC, id DESC
        LIMIT 1
        """,
        (workflow_bag_id, station_id, WC.EVENT_BAG_CLAIMED, WC.EVENT_STATION_RESUMED),
    ).fetchone()
    if not row:
        return None
    try:
        return int(row["occurred_at"])
    except (TypeError, ValueError):
        return None


def _assigned_card_token_for_bag(conn: sqlite3.Connection, workflow_bag_id: int) -> str | None:
    row = conn.execute(
        """
        SELECT scan_token
        FROM qr_cards
        WHERE assigned_workflow_bag_id = ?
          AND status = ?
        ORDER BY id ASC
        LIMIT 1
        """,
        (workflow_bag_id, WC.QR_CARD_STATUS_ASSIGNED),
    ).fetchone()
    if not row:
        return None
    token = row["scan_token"]
    return str(token).strip() if token else None


def _current_station_occupancy(conn: sqlite3.Connection, station_id: int) -> dict | None:
    sk_row = conn.execute(
        """
        SELECT COALESCE(station_kind, 'sealing') AS station_kind
        FROM workflow_stations
        WHERE id = ?
        """,
        (station_id,),
    ).fetchone()
    station_kind = (sk_row["station_kind"] if sk_row else None) or "sealing"

    row = conn.execute(
        """
        SELECT we.workflow_bag_id, we.occurred_at, qc.scan_token AS card_token
        FROM workflow_events we
        JOIN qr_cards qc
          ON qc.assigned_workflow_bag_id = we.workflow_bag_id
         AND qc.status = ?
        WHERE we.station_id = ?
          AND we.event_type IN (?, ?)
        ORDER BY we.occurred_at DESC, we.id DESC
        LIMIT 1
        """,
        (
            WC.QR_CARD_STATUS_ASSIGNED,
            station_id,
            WC.EVENT_BAG_CLAIMED,
            WC.EVENT_STATION_RESUMED,
        ),
    ).fetchone()
    if not row:
        return None
    bag_id = int(row["workflow_bag_id"])
    if _occupancy_lane_finished_at_station(
        conn,
        station_id=station_id,
        workflow_bag_id=bag_id,
        station_kind=station_kind,
    ):
        return None
    started_at = int(row["occurred_at"])
    facts = _station_facts_payload(conn, bag_id, station_id)
    status = "paused" if facts.get("resume_required") else "occupied"
    pause_at = (
        _station_pause_at_ms(conn, bag_id, station_id) if status == "paused" else None
    )
    return {
        "status": status,
        "workflow_bag_id": bag_id,
        "card_token": row["card_token"],
        "occupancy_started_at_ms": started_at,
        "paused_at_ms": pause_at,
        "facts": facts,
    }


def _station_facts_payload(
    conn: sqlite3.Connection, workflow_bag_id: int, station_id: int
) -> dict:
    facts = mechanical_bag_facts(conn, workflow_bag_id)
    station_claimed = _station_has_claimed_bag(conn, workflow_bag_id, station_id)
    station_needs_resume = _station_needs_resume(conn, workflow_bag_id, station_id)
    occupancy_started_at = _station_occupancy_started_at(conn, workflow_bag_id, station_id)
    return {
        "event_counts_by_type": facts["event_counts_by_type"],
        "latest_event_type": facts["latest_event_type"],
        "display_stage_label": display_stage_label(facts),
        "progress_summary": progress_summary(facts),
        "station_claimed": station_claimed,
        "claim_required": not station_claimed,
        "station_needs_resume": station_needs_resume,
        "resume_required": bool(station_claimed and station_needs_resume),
        "occupancy_started_at_ms": occupancy_started_at,
        "occupying_card_token": _assigned_card_token_for_bag(conn, workflow_bag_id),
        "bag_verification": floor_bag_verification(conn, workflow_bag_id),
        "production_flow": production_flow_for_bag(conn, workflow_bag_id),
    }


def _is_event_allowed_for_station(station_kind: str, event_type: str) -> bool:
    kind = (station_kind or "sealing").strip().lower()
    et = (event_type or "").strip().upper()
    if et in (WC.EVENT_BAG_CLAIMED, WC.EVENT_STATION_RESUMED):
        return True
    allowed = {
        "blister": {WC.EVENT_BLISTER_COMPLETE, WC.EVENT_OPERATOR_CHANGE},
        "sealing": {WC.EVENT_SEALING_COMPLETE},
        "packaging": {WC.EVENT_PACKAGING_SNAPSHOT, WC.EVENT_PACKAGING_TAKEN_FOR_ORDER},
        "combined": {WC.EVENT_BLISTER_COMPLETE, WC.EVENT_SEALING_COMPLETE},
        "bottle_handpack": {WC.EVENT_BOTTLE_HANDPACK_COMPLETE},
        "bottle_cap_seal": {WC.EVENT_BOTTLE_CAP_SEAL_COMPLETE},
        "bottle_stickering": {WC.EVENT_BOTTLE_STICKER_COMPLETE},
    }
    return et in allowed.get(kind, set())


def _event_flow(event_type: str) -> str | None:
    et = (event_type or "").strip().upper()
    if et in {
        WC.EVENT_BLISTER_COMPLETE,
        WC.EVENT_SEALING_COMPLETE,
    }:
        return "card"
    if et in {
        WC.EVENT_BOTTLE_HANDPACK_COMPLETE,
        WC.EVENT_BOTTLE_CAP_SEAL_COMPLETE,
        WC.EVENT_BOTTLE_STICKER_COMPLETE,
    }:
        return "bottle"
    return None


def _selected_product_id_from_payload(payload: dict) -> int | None:
    """Optional operator-selected product for ambiguous tablet-to-SKU mappings."""
    if not isinstance(payload, dict):
        return None
    raw = payload.get("product_id")
    if raw is None:
        meta = payload.get("metadata")
        if isinstance(meta, dict):
            raw = meta.get("product_id") or meta.get("selected_product_id")
    try:
        return int(raw) if raw is not None and str(raw).strip() else None
    except (TypeError, ValueError):
        return None


def _coerce_nonnegative_int(raw) -> int:
    try:
        n = int(raw or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, n)


def _packaging_displays_per_case(conn: sqlite3.Connection, workflow_bag_id: int) -> int | None:
    try:
        row = conn.execute(
            """
            SELECT pd.displays_per_case
            FROM workflow_bags wb
            LEFT JOIN product_details pd ON pd.id = wb.product_id
            WHERE wb.id = ?
            """,
            (int(workflow_bag_id),),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row:
        return None
    try:
        dpc = int(dict(row).get("displays_per_case") or 0)
    except (TypeError, ValueError):
        return None
    return dpc if dpc > 0 else None


def _normalize_packaging_snapshot_payload(
    conn: sqlite3.Connection, workflow_bag_id: int, payload: dict
) -> dict:
    """Normalize packaging payload; display_count remains loose displays (not full cases)."""
    out = dict(payload or {})
    has_case_fields = "case_count" in out or "loose_display_count" in out
    if not has_case_fields:
        return out
    cases = _coerce_nonnegative_int(out.get("case_count"))
    loose_displays = _coerce_nonnegative_int(
        out.get("display_count") if "display_count" in out else out.get("loose_display_count")
    )
    out["case_count"] = cases
    out["loose_display_count"] = loose_displays
    out["display_count"] = loose_displays
    return out


def _workflow_bag_product_flags(conn: sqlite3.Connection, workflow_bag_id: int) -> dict:
    try:
        row = conn.execute(
            """
            SELECT wb.product_id, COALESCE(pd.is_bottle_product, 0) AS is_bottle_product,
                   COALESCE(pd.is_variety_pack, 0) AS is_variety_pack
            FROM workflow_bags wb
            LEFT JOIN product_details pd ON pd.id = wb.product_id
            WHERE wb.id = ?
            """,
            (int(workflow_bag_id),),
        ).fetchone()
    except sqlite3.OperationalError:
        row = None
    if not row:
        return {"product_id": None, "is_bottle_product": False, "is_variety_pack": False}
    r = dict(row)
    return {
        "product_id": r.get("product_id"),
        "is_bottle_product": bool(int(r.get("is_bottle_product") or 0)),
        "is_variety_pack": bool(int(r.get("is_variety_pack") or 0)),
    }


def _workflow_bag_has_product(conn: sqlite3.Connection, workflow_bag_id: int) -> bool:
    row = conn.execute(
        "SELECT product_id FROM workflow_bags WHERE id = ?",
        (int(workflow_bag_id),),
    ).fetchone()
    return bool(row and row["product_id"] is not None)


def _list_from_payload(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(x) for x in raw if str(x or "").strip()]
    return []


def _normalize_bottle_handpack_sources(
    conn: sqlite3.Connection,
    *,
    workflow_bag_id: int,
    main_card_token: str,
    payload: dict,
) -> dict:
    """Resolve scanned source card tokens to active workflow/source inventory ids for variety packs."""
    flags = _workflow_bag_product_flags(conn, workflow_bag_id)
    if not flags.get("is_variety_pack"):
        return payload
    out = dict(payload or {})
    tokens: list[str] = []
    seen_tokens: set[str] = set()
    for token in _list_from_payload(out.get("source_card_tokens")):
        t = str(token or "").strip()
        if not t or t == str(main_card_token or "").strip() or t in seen_tokens:
            continue
        seen_tokens.add(t)
        tokens.append(t)
    if not tokens:
        raise ValueError("Scan at least one source bag QR for this variety pack.")
    qmarks = ",".join("?" for _ in tokens)
    rows = conn.execute(
        f"""
        SELECT qc.id AS qr_card_id, qc.scan_token, qc.assigned_workflow_bag_id,
               wb.inventory_bag_id, wb.product_id
        FROM qr_cards qc
        JOIN workflow_bags wb ON wb.id = qc.assigned_workflow_bag_id
        WHERE qc.status = ?
          AND qc.scan_token IN ({qmarks})
        """,
        (WC.QR_CARD_STATUS_ASSIGNED, *tokens),
    ).fetchall()
    by_token = {str(r["scan_token"]): dict(r) for r in rows}
    missing = [t for t in tokens if t not in by_token]
    if missing:
        raise ValueError(f"Source bag QR not assigned: {missing[0]}")
    qr_card_ids: list[int] = []
    workflow_ids: list[int] = []
    inventory_ids: list[int] = []
    for token in tokens:
        r = by_token[token]
        if r.get("inventory_bag_id") is None:
            raise ValueError("Source bag QR is not linked to a receiving bag.")
        qr_card_ids.append(int(r["qr_card_id"]))
        workflow_ids.append(int(r["assigned_workflow_bag_id"]))
        inventory_ids.append(int(r["inventory_bag_id"]))
    out["source_card_tokens"] = tokens
    out["source_qr_card_ids"] = qr_card_ids
    out["source_workflow_bag_ids"] = workflow_ids
    out["source_inventory_bag_ids"] = inventory_ids
    return out


@bp.route("/manual")
def manual_station():
    """Paste station / card tokens without scanning."""
    return render_template("workflow_manual.html")


@bp.route("/station/<path:station_token>")
def station_page(station_token: str):
    """Per-station floor UI (camera allowed via Permissions-Policy)."""
    conn = get_db()
    try:
        row = _resolve_station(conn, station_token)
        if not row:
            return render_template("error.html", error_message="Unknown station token"), 404
        r = dict(row)
        return render_template(
            "workflow_station.html",
            station_token=station_token,
            station_id=int(row["id"]),
            station_label=row["label"],
            machine_name=r.get("machine_name"),
            station_kind=r.get("station_kind") or "sealing",
            is_admin_user=bool(
                session.get("admin_authenticated")
                or (session.get("employee_role") == "admin")
            ),
        )
    finally:
        conn.close()


@bp.route("/floor/api/station", methods=["POST"])
@rate_limit_floor
def api_resolve_station():
    data = read_json_body(request)
    _log_floor_correlation("api_resolve_station", data)
    token = (data.get("station_token") or "").strip()
    if not token:
        return workflow_json("WORKFLOW_VALIDATION", "station_token required")
    conn = get_db()
    try:
        row = _resolve_station(conn, token)
        if not row:
            return workflow_json("WORKFLOW_STATION_INVALID", "Unknown station token", status=404)
        payload = {
            "ok": True,
            "station_id": row["id"],
            "label": row["label"],
        }
        r = dict(row)
        if r.get("machine_name"):
            payload["machine_name"] = r["machine_name"]
        if r.get("station_kind"):
            payload["station_kind"] = r["station_kind"]
        if r.get("machine_id") is not None:
            payload["machine_id"] = int(r["machine_id"])
        occupancy = _current_station_occupancy(conn, int(row["id"]))
        payload["occupancy"] = occupancy or {"status": "idle"}
        return payload
    finally:
        conn.close()


@bp.route("/floor/api/bag", methods=["POST"])
@rate_limit_floor
def api_bag_status():
    data = read_json_body(request)
    _log_floor_correlation("api_bag_status", data)
    station_token = (data.get("station_token") or "").strip()
    card_token = (data.get("card_token") or "").strip()
    if not station_token or not card_token:
        return workflow_json("WORKFLOW_VALIDATION", "station_token and card_token required")
    conn = get_db()
    try:
        st = _resolve_station(conn, station_token)
        if not st:
            return workflow_json("WORKFLOW_STATION_INVALID", "Unknown station", status=404)
        card = _resolve_card(conn, card_token)
        if not card:
            return workflow_json("WORKFLOW_BAG_NOT_FOUND", "Unknown card token", status=404)
        if card["status"] != WC.QR_CARD_STATUS_ASSIGNED or card["assigned_workflow_bag_id"] is None:
            return workflow_json(
                "WORKFLOW_VALIDATION",
                "Card is not assigned to a bag",
                details={"status": card["status"]},
            )
        bag_id = int(card["assigned_workflow_bag_id"])
        station_id = int(st["id"])
        payload = {
            "ok": True,
            "workflow_bag_id": bag_id,
            "qr_card_id": int(card["id"]),
            "station_id": station_id,
            "facts": _station_facts_payload(conn, bag_id, station_id),
        }
        return payload
    finally:
        conn.close()


@bp.route("/floor/api/event", methods=["POST"])
@rate_limit_floor
def api_append_event():
    data = read_json_body(request)
    _log_floor_correlation("api_append_event", data)
    station_token = (data.get("station_token") or "").strip()
    card_token = (data.get("card_token") or "").strip()
    event_type = (data.get("event_type") or "").strip()
    payload = data.get("payload") or {}
    device_id = (data.get("device_id") or "").strip() or None

    if not station_token or not card_token or not event_type:
        return workflow_json("WORKFLOW_VALIDATION", "station_token, card_token, event_type required")

    if event_type in (WC.EVENT_BAG_FINALIZED, WC.EVENT_CARD_FORCE_RELEASED):
        return workflow_json(
            "WORKFLOW_VALIDATION",
            "Use /floor/api/finalize or staff force-release for terminal events",
        )

    conn = get_db()
    try:
        st = _resolve_station(conn, station_token)
        if not st:
            return workflow_json("WORKFLOW_STATION_INVALID", "Unknown station", status=404)
        card = _resolve_card(conn, card_token)
        if not card:
            return workflow_json("WORKFLOW_BAG_NOT_FOUND", "Unknown card", status=404)
        if card["assigned_workflow_bag_id"] is None:
            return workflow_json("WORKFLOW_VALIDATION", "Card not assigned")
        bag_id = int(card["assigned_workflow_bag_id"])
        st_dict = dict(st)
        station_kind = (st_dict.get("station_kind") or "sealing").strip().lower()
        if not _is_event_allowed_for_station(station_kind, event_type):
            return workflow_json(
                "WORKFLOW_VALIDATION",
                f"{event_type} is not allowed for station type '{station_kind}'",
                details={
                    "reason": "wrong_station_type",
                    "station_kind": station_kind,
                    "event_type": event_type,
                },
                status=400,
            )
        ev_flow = _event_flow(event_type)
        mapping_flow = production_flow_for_event_or_station(event_type, station_kind)
        if mapping_flow:
            map_status, map_body = ensure_workflow_bag_product_for_flow(
                conn,
                workflow_bag_id=bag_id,
                production_flow=mapping_flow,
                selected_product_id=_selected_product_id_from_payload(
                    payload if isinstance(payload, dict) else {}
                ),
                station_id=int(st["id"]),
                device_id=device_id,
            )
            if map_status == "reject":
                reason = map_body.get("reason")
                if reason == "wrong_production_flow":
                    return workflow_json(
                        "WORKFLOW_VALIDATION",
                        f"{event_type} is not allowed for {map_body.get('production_flow')} workflow bags.",
                        details={
                            **map_body,
                            "event_type": event_type,
                        },
                        status=400,
                    )
                if reason == "ambiguous_product_mapping":
                    return workflow_json(
                        "WORKFLOW_PRODUCT_MAPPING",
                        "Choose which product this tablet is running as on this station.",
                        details=map_body,
                        status=409,
                    )
                if reason == "no_product_mapping":
                    return workflow_json(
                        "WORKFLOW_PRODUCT_MAPPING",
                        "No product is configured for this tablet on this station type.",
                        details=map_body,
                        status=400,
                    )
                return workflow_json(
                    "WORKFLOW_PRODUCT_MAPPING",
                    "Could not map this tablet to a product for this station.",
                    details=map_body,
                    status=400,
                )

        bag_flow = production_flow_for_bag(conn, bag_id)
        if ev_flow and ev_flow != bag_flow:
            return workflow_json(
                "WORKFLOW_VALIDATION",
                f"{event_type} is not allowed for {bag_flow} workflow bags.",
                details={
                    "reason": "wrong_production_flow",
                    "production_flow": bag_flow,
                    "event_flow": ev_flow,
                    "event_type": event_type,
                },
                status=400,
            )
        if (
            event_type == WC.EVENT_BAG_CLAIMED
            and station_kind == "packaging"
            and not _workflow_bag_has_product(conn, bag_id)
        ):
            return workflow_json(
                "WORKFLOW_PRODUCT_MAPPING",
                "Scan this bag at a card or bottle station before packaging.",
                details={"reason": "product_not_mapped", "station_kind": station_kind},
                status=400,
            )
        if event_type in (
            WC.EVENT_PACKAGING_SNAPSHOT,
            WC.EVENT_PACKAGING_TAKEN_FOR_ORDER,
        ) and not _workflow_bag_has_product(conn, bag_id):
            return workflow_json(
                "WORKFLOW_PRODUCT_MAPPING",
                "This bag must be scanned through its card or bottle production station before packaging.",
                details={"reason": "product_not_mapped", "station_kind": station_kind},
                status=400,
            )
        station_id = int(st["id"])
        if event_type == WC.EVENT_PACKAGING_SNAPSHOT:
            payload = _normalize_packaging_snapshot_payload(conn, bag_id, payload)
        if event_type == WC.EVENT_BOTTLE_HANDPACK_COMPLETE:
            try:
                payload = _normalize_bottle_handpack_sources(
                    conn,
                    workflow_bag_id=bag_id,
                    main_card_token=card_token,
                    payload=payload if isinstance(payload, dict) else {},
                )
            except ValueError as ve:
                return workflow_json(
                    "WORKFLOW_VALIDATION",
                    str(ve),
                    details={"reason": "invalid_source_bag"},
                    status=400,
                )
        station_claimed = _station_has_claimed_bag(conn, bag_id, station_id)
        if event_type != WC.EVENT_BAG_CLAIMED and not station_claimed:
            return workflow_json(
                "WORKFLOW_VALIDATION",
                "Bag must be claimed at this station before submitting counts.",
                details={"reason": "claim_required", "station_kind": station_kind},
                status=400,
            )
        if event_type == WC.EVENT_BAG_CLAIMED and station_claimed:
            return {
                "ok": True,
                "workflow_bag_id": bag_id,
                "facts": _station_facts_payload(conn, bag_id, station_id),
                "idempotent_duplicate": True,
            }
        station_needs_resume = _station_needs_resume(conn, bag_id, station_id)
        if event_type == WC.EVENT_STATION_RESUMED and not station_needs_resume:
            return {
                "ok": True,
                "workflow_bag_id": bag_id,
                "facts": _station_facts_payload(conn, bag_id, station_id),
                "idempotent_duplicate": True,
            }
        if station_needs_resume and event_type in (
            WC.EVENT_BLISTER_COMPLETE,
            WC.EVENT_SEALING_COMPLETE,
            WC.EVENT_OPERATOR_CHANGE,
            WC.EVENT_BOTTLE_HANDPACK_COMPLETE,
            WC.EVENT_BOTTLE_CAP_SEAL_COMPLETE,
            WC.EVENT_BOTTLE_STICKER_COMPLETE,
            WC.EVENT_PACKAGING_SNAPSHOT,
            WC.EVENT_PACKAGING_TAKEN_FOR_ORDER,
        ):
            return workflow_json(
                "WORKFLOW_VALIDATION",
                "Resume this bag at this station before submitting counts (tap Resume).",
                details={"reason": "resume_required", "station_kind": station_kind},
                status=400,
            )
        if event_type == WC.EVENT_PACKAGING_TAKEN_FOR_ORDER:
            try:
                _dt = int((payload or {}).get("displays_taken") or 0)
            except (TypeError, ValueError):
                _dt = 0
            if _dt < 1:
                return workflow_json(
                    "WORKFLOW_VALIDATION",
                    "displays_taken must be at least 1 for taken-for-order.",
                    status=400,
                )
        if event_type == WC.EVENT_BLISTER_COMPLETE:
            is_handpack_rest = bool(
                isinstance(payload, dict)
                and isinstance(payload.get("metadata"), dict)
                and payload.get("metadata", {}).get("handpack_rest")
            )
            if is_handpack_rest and not (
                session.get("admin_authenticated")
                or (session.get("employee_role") == "admin")
            ):
                return workflow_json(
                    "WORKFLOW_VALIDATION",
                    "Hand pack the rest is restricted to admin users.",
                    details={"reason": "admin_required", "action": "handpack_rest"},
                    status=403,
                )
        try:
            event_id = append_workflow_event(
                conn,
                event_type,
                payload,
                bag_id,
                station_id=station_id,
                device_id=device_id,
            )
        except ValueError as ve:
            return workflow_json("WORKFLOW_VALIDATION", str(ve), details={"hint": "payload_keys"})
        pl = payload if isinstance(payload, dict) else {}
        bridge_result = None
        try:
            bridge_result = sync_workflow_warehouse_events(
                conn, bag_id, event_type, pl, st_dict, event_id=event_id
            )
        except ProductionSubmissionError as pse:
            conn.rollback()
            body = pse.body if isinstance(pse.body, dict) else {}
            msg = body.get("error") or "Machine submission could not be saved."
            return workflow_json(
                "WORKFLOW_MACHINE_SYNC",
                msg,
                status=pse.status_code or 400,
                details={k: v for k, v in body.items() if k != "error"},
            )
        except Exception as sync_exc:
            LOGGER.exception(
                "workflow warehouse bridge failed workflow_bag_id=%s: %s", bag_id, sync_exc
            )
            conn.rollback()
            return workflow_json(
                "WORKFLOW_WAREHOUSE_SYNC",
                "Could not sync workflow to warehouse submissions.",
                status=500,
            )
        conn.commit()
        out = {
            "ok": True,
            "workflow_bag_id": bag_id,
            "facts": _station_facts_payload(conn, bag_id, station_id),
        }
        if bridge_result is not None:
            out["warehouse_sync"] = bridge_result
        return out
    except sqlite3.OperationalError as oe:
        conn.rollback()
        if "locked" in str(oe).lower():
            LOGGER.error("WORKFLOW_BUSY_RETRY event append: %s", oe)
            return workflow_json(
                "WORKFLOW_BUSY_RETRY",
                "Database busy; retry once after a short wait",
                status=503,
            )
        raise
    finally:
        conn.close()


@bp.route("/floor/api/finalize", methods=["POST"])
@rate_limit_floor
def api_finalize():
    data = read_json_body(request)
    _log_floor_correlation("api_finalize", data)
    station_token = (data.get("station_token") or "").strip()
    card_token = (data.get("card_token") or "").strip()
    device_id = (data.get("device_id") or "").strip() or None
    if not station_token or not card_token:
        return workflow_json("WORKFLOW_VALIDATION", "station_token and card_token required")

    conn = get_db()
    try:
        st = _resolve_station(conn, station_token)
        if not st:
            return workflow_json("WORKFLOW_STATION_INVALID", "Unknown station", status=404)
        station_kind = (st["station_kind"] or "sealing").strip().lower()
        if station_kind != "packaging":
            return workflow_json(
                "WORKFLOW_VALIDATION",
                "Finalize is only allowed from packaging stations.",
                status=400,
            )
        card = _resolve_card(conn, card_token)
        if not card or card["assigned_workflow_bag_id"] is None:
            return workflow_json("WORKFLOW_VALIDATION", "Card not assigned to a bag")
        bag_id = int(card["assigned_workflow_bag_id"])

        def _run():
            return try_finalize(
                conn,
                bag_id,
                station_id=int(st["id"]),
                device_id=device_id,
            )

        try:
            status, body = run_with_busy_retry(_run, op_name="floor_finalize")
        except sqlite3.OperationalError as oe:
            if "locked" in str(oe).lower():
                return workflow_json(
                    "WORKFLOW_BUSY_RETRY",
                    "Database busy; retry once after a short wait",
                    status=503,
                )
            raise

        if status == "reject":
            code = body.get("code", "WORKFLOW_VALIDATION")
            if code == "WORKFLOW_ALREADY_FINALIZED":
                return workflow_json(code, "Already finalized", status=400)
            return workflow_json(code, "Cannot finalize", details=body.get("details"), status=400)
        if status == "duplicate":
            return {"ok": True, **body}
        if status == "ok":
            conn.commit()
            return {"ok": True, **body}
        return workflow_json("WORKFLOW_VALIDATION", "Unexpected finalize state")
    finally:
        try:
            conn.close()
        except Exception:
            pass
