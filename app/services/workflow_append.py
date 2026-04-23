"""Single write path for workflow_events rows."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from app.services.workflow_payloads import normalize_payload


def utc_ms_now() -> int:
    return int(time.time() * 1000)


def append_workflow_event(
    conn: sqlite3.Connection,
    event_type: str,
    payload: dict[str, Any],
    workflow_bag_id: int,
    *,
    station_id: int | None = None,
    user_id: int | None = None,
    device_id: str | None = None,
) -> int:
    """Insert one workflow_events row (caller controls transaction boundaries)."""
    p = normalize_payload(event_type, payload)
    occurred_at = utc_ms_now()
    cur = conn.execute(
        """
        INSERT INTO workflow_events (
            event_type, payload, occurred_at, workflow_bag_id, station_id, user_id, device_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_type,
            json.dumps(p),
            occurred_at,
            workflow_bag_id,
            station_id,
            user_id,
            device_id,
        ),
    )
    return int(cur.lastrowid)
