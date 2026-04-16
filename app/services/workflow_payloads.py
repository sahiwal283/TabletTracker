
"""Per-event-type allowed top-level payload keys (v1 guardrails)."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, FrozenSet, Optional, Tuple

from flask import current_app

from app.services import workflow_constants as WC

LOGGER = logging.getLogger(__name__)

# Keys always allowed in addition to documented fields
_EXTRA_KEYS: FrozenSet[str] = frozenset({"metadata", "extra"})

_ALLOWED: Dict[str, FrozenSet[str]] = {
    WC.EVENT_CARD_ASSIGNED: frozenset({"qr_card_id", "workflow_bag_id"}),
    WC.EVENT_BAG_CLAIMED: frozenset({"station_id", "station_kind", "note"}),
    WC.EVENT_STATION_RESUMED: frozenset({"station_id", "station_kind", "note"}),
    WC.EVENT_BLISTER_COMPLETE: frozenset({"count_total", "employee_name"}),
    WC.EVENT_SEALING_COMPLETE: frozenset({"station_id", "count_total", "employee_name"}),
    WC.EVENT_PACKAGING_SNAPSHOT: frozenset(
        {"display_count", "reason", "employee_name", "packs_remaining", "damaged_tablets"}
    ),
    WC.EVENT_PACKAGING_TAKEN_FOR_ORDER: frozenset(
        {"displays_taken", "employee_name", "note"}
    ),
    WC.EVENT_BAG_FINALIZED: frozenset({"finalization_rule_version"}),
    WC.EVENT_CARD_FORCE_RELEASED: frozenset({"qr_card_id", "workflow_bag_id", "reason"}),
    WC.EVENT_STATION_SCAN_TOKEN_ROTATED: frozenset(
        {"station_id", "old_token_prefix", "new_token_prefix"}
    ),
}


def _is_debug_fail_loud() -> bool:
    try:
        return bool(current_app and current_app.debug)
    except RuntimeError:
        return False


def normalize_payload(event_type: str, payload: Any) -> Dict[str, Any]:
    """Validate top-level keys; return a plain dict (copy)."""
    if not isinstance(payload, dict):
        msg = "payload must be a JSON object"
        if _is_debug_fail_loud():
            raise ValueError(msg)
        raise ValueError(msg)

    allowed = _ALLOWED.get(event_type)
    if allowed is None:
        msg = f"unknown event_type for payload validation: {event_type}"
        if _is_debug_fail_loud():
            raise ValueError(msg)
        raise ValueError(msg)

    keys = set(payload.keys())
    legal = allowed | _EXTRA_KEYS
    unknown = sorted(keys - legal)
    if unknown:
        diff = {"unknown_top_level_keys": unknown, "allowed": sorted(legal)}
        LOGGER.warning(
            "workflow payload rejected: event_type=%s diff=%s",
            event_type,
            json.dumps(diff),
        )
        if _is_debug_fail_loud():
            raise ValueError(f"Unknown keys for {event_type}: {unknown}")
        raise ValueError("invalid payload keys")

    return dict(payload)


def payload_diff_for_log(event_type: str, payload: Any) -> str:
    try:
        normalize_payload(event_type, payload)
        return ""
    except ValueError as e:
        return str(e)
