"""Workflow-aware corrections for QR-synced warehouse submission rows."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.services import workflow_constants as WC
from app.services.workflow_append import append_workflow_event
from app.services.workflow_warehouse_bridge import (
    sync_if_packaging_snapshot,
    upsert_machine_from_workflow_scan,
)

_EVENT_SUFFIX_RE = re.compile(r"(?:^|-)e(\d+)$")
_WORKFLOW_BASE_RE = re.compile(r"^WORKFLOW-(\d+)")


def _parse_payload(raw: str | None) -> dict[str, Any]:
    try:
        val = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return val if isinstance(val, dict) else {}


def _event_ms_from_utc_like(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if not s:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(s[:26], fmt)
                break
            except ValueError:
                dt = None
        if dt is None:
            return None
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _candidate_workflow_bag_id(conn: sqlite3.Connection, receipt: str) -> int | None:
    m = _WORKFLOW_BASE_RE.match(receipt)
    if m:
        return int(m.group(1))
    row = conn.execute(
        """
        SELECT id
        FROM workflow_bags
        WHERE TRIM(COALESCE(receipt_number, '')) = TRIM(?)
        ORDER BY id DESC
        LIMIT 1
        """,
        (receipt,),
    ).fetchone()
    return int(row["id"]) if row else None


def _event_type_for_submission(row: dict[str, Any]) -> str | None:
    st = (row.get("submission_type") or "packaged").strip().lower()
    if st in {"packaged", "bottle"}:
        return WC.EVENT_PACKAGING_SNAPSHOT
    if st == "machine":
        role = (row.get("machine_role") or "sealing").strip().lower()
        return WC.EVENT_BLISTER_COMPLETE if role == "blister" else WC.EVENT_SEALING_COMPLETE
    return None


def _target_event_id_from_receipt(receipt: str) -> int | None:
    m = _EVENT_SUFFIX_RE.search(receipt)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


def _find_target_event(
    conn: sqlite3.Connection,
    *,
    workflow_bag_id: int,
    event_type: str,
    submission_row: dict[str, Any],
) -> dict[str, Any] | None:
    target_id = _target_event_id_from_receipt(submission_row.get("receipt_number") or "")
    if target_id:
        row = conn.execute(
            """
            SELECT id, event_type, payload, occurred_at, workflow_bag_id, station_id
            FROM workflow_events
            WHERE id = ? AND workflow_bag_id = ? AND event_type = ?
            """,
            (target_id, workflow_bag_id, event_type),
        ).fetchone()
        return dict(row) if row else None

    rows = conn.execute(
        """
        SELECT id, event_type, payload, occurred_at, workflow_bag_id, station_id
        FROM workflow_events
        WHERE workflow_bag_id = ? AND event_type = ?
        ORDER BY occurred_at DESC, id DESC
        """,
        (workflow_bag_id, event_type),
    ).fetchall()
    if not rows:
        return None
    if _target_event_id_from_receipt(submission_row.get("receipt_number") or "") is None and len(rows) > 1:
        # Manual receipt rows can share one receipt across multiple QR events. Without
        # an event suffix we cannot safely know which warehouse row maps to which event.
        return None
    target_ms = (
        _event_ms_from_utc_like(submission_row.get("bag_end_time"))
        or _event_ms_from_utc_like(submission_row.get("created_at"))
    )
    if target_ms is None:
        return dict(rows[0])
    return dict(min(rows, key=lambda r: abs(int(r["occurred_at"] or 0) - target_ms)))


def resolve_qr_synced_submission(
    conn: sqlite3.Connection, submission_id: int
) -> dict[str, Any] | None:
    """Return workflow target context for a warehouse row, or ``None`` for legacy rows."""
    row = conn.execute(
        """
        SELECT ws.*, COALESCE(ws.submission_type, 'packaged') AS submission_type,
               COALESCE(m.machine_role, 'sealing') AS machine_role
        FROM warehouse_submissions ws
        LEFT JOIN machines m ON m.id = ws.machine_id
        WHERE ws.id = ?
        """,
        (int(submission_id),),
    ).fetchone()
    if not row:
        return None
    sub = dict(row)
    receipt = (sub.get("receipt_number") or "").strip()
    if not receipt:
        return None
    workflow_bag_id = _candidate_workflow_bag_id(conn, receipt)
    if not workflow_bag_id:
        return None
    event_type = _event_type_for_submission(sub)
    if not event_type:
        return None
    event = _find_target_event(
        conn,
        workflow_bag_id=workflow_bag_id,
        event_type=event_type,
        submission_row=sub,
    )
    if not event:
        return None
    return {
        "submission": sub,
        "workflow_bag_id": workflow_bag_id,
        "event": event,
        "event_payload": _parse_payload(event.get("payload")),
        "event_type": event_type,
    }


def _corrected_payload_for_submission(
    original: dict[str, Any],
    submission_type: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    corrected = dict(original)
    employee = (data.get("employee_name") or corrected.get("employee_name") or "QR workflow")
    corrected["employee_name"] = str(employee)[:128]

    if submission_type == "machine":
        corrected["count_total"] = max(0, int(data.get("displays_made") or 0))
        return corrected

    if submission_type == "bottle":
        corrected["display_count"] = max(0, int(data.get("displays_made") or 0))
        corrected["packs_remaining"] = max(0, int(data.get("packs_remaining") or 0))
        return corrected

    corrected["display_count"] = max(0, int(data.get("displays_made") or 0))
    corrected["case_count"] = max(0, int(data.get("case_count") or 0))
    corrected["loose_display_count"] = max(0, int(data.get("loose_display_count") or corrected["display_count"]))
    corrected["packs_remaining"] = max(0, int(data.get("packs_remaining") or 0))
    corrected["cards_reopened"] = max(0, int(data.get("cards_reopened") or 0))
    return corrected


def _station_row_for_event(conn: sqlite3.Connection, event: dict[str, Any]) -> dict[str, Any]:
    sid = event.get("station_id")
    if sid is None:
        return {}
    row = conn.execute("SELECT * FROM workflow_stations WHERE id = ?", (int(sid),)).fetchone()
    return dict(row) if row else {"id": sid}


def apply_qr_submission_correction(
    conn: sqlite3.Connection,
    submission_id: int,
    data: dict[str, Any],
    *,
    corrected_by: str | None = None,
) -> dict[str, Any] | None:
    """Append a QR correction event and resync the mirrored warehouse row.

    Returns ``None`` when the row is not QR-synced, allowing callers to fall back
    to legacy direct edits.
    """
    ctx = resolve_qr_synced_submission(conn, submission_id)
    if not ctx:
        return None

    sub = ctx["submission"]
    submission_type = (sub.get("submission_type") or "packaged").strip().lower()
    if submission_type not in {"packaged", "bottle", "machine"}:
        return None

    target = ctx["event"]
    event_type = ctx["event_type"]
    corrected_payload = _corrected_payload_for_submission(
        ctx["event_payload"], submission_type, data
    )
    note = (data.get("admin_notes") or "").strip() or None
    correction_payload = {
        "target_event_id": int(target["id"]),
        "corrected_event_type": event_type,
        "corrected_payload": corrected_payload,
        "warehouse_submission_id": int(submission_id),
        "corrected_by": (corrected_by or "Submission edit")[:128],
        "note": note,
    }
    correction_event_id = append_workflow_event(
        conn,
        WC.EVENT_SUBMISSION_CORRECTED,
        correction_payload,
        int(ctx["workflow_bag_id"]),
        station_id=target.get("station_id"),
    )

    station = _station_row_for_event(conn, target)
    if event_type == WC.EVENT_PACKAGING_SNAPSHOT:
        sync = sync_if_packaging_snapshot(
            conn,
            int(ctx["workflow_bag_id"]),
            event_type,
            corrected_payload,
            station_row=station,
            event_id=int(target["id"]),
        )
    else:
        lane = "blister" if event_type == WC.EVENT_BLISTER_COMPLETE else "seal"
        expected = "blister" if lane == "blister" else "sealing"
        sync = upsert_machine_from_workflow_scan(
            conn,
            int(ctx["workflow_bag_id"]),
            count_total=int(corrected_payload.get("count_total") or 0),
            station_row=station,
            lane=lane,
            expected_machine_role=expected,
            event_id=int(target["id"]),
            employee_name=corrected_payload.get("employee_name") or "QR workflow",
        )

    return {
        "success": True,
        "workflow_bag_id": int(ctx["workflow_bag_id"]),
        "target_event_id": int(target["id"]),
        "correction_event_id": correction_event_id,
        "warehouse_sync": sync,
    }
