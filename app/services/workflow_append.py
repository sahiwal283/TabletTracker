
"""Single write path for workflow_events rows."""

from __future__ import annotations

import json
import time
import sqlite3
from typing import Any, Dict, Optional

from app.services.workflow_payloads import normalize_payload


def utc_ms_now() -> int:
    return int(time.time() * 1000)


def append_workflow_event(
    conn: sqlite3.Connection,
    event_type: str,
    payload: Dict[str, Any],
    workflow_bag_id: int,
    *,
    station_id: Optional[int] = None,
    user_id: Optional[int] = None,
    device_id: Optional[str] = None,
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
