"""Event-derived out-of-packaging facts shared by floor UI and terminal policy."""

from __future__ import annotations

from typing import Any

from app.services import workflow_constants as WC

OUT_OF_PACKAGING_REASON = "out_of_packaging"


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload") if isinstance(event, dict) else {}
    return payload if isinstance(payload, dict) else {}


def _metadata(payload: dict[str, Any]) -> dict[str, Any]:
    meta = payload.get("metadata")
    return meta if isinstance(meta, dict) else {}


def _is_out_of_packaging_payload(payload: dict[str, Any]) -> bool:
    meta = _metadata(payload)
    reason = str(
        payload.get("reason") or payload.get("pause_reason") or meta.get("reason") or ""
    ).strip()
    return reason == OUT_OF_PACKAGING_REASON


def _shortage_for_event(event: dict[str, Any]) -> dict[str, Any] | None:
    et = str(event.get("event_type") or "")
    payload = _payload(event)
    if not _is_out_of_packaging_payload(payload):
        return None

    meta = _metadata(payload)
    if et == WC.EVENT_SEALING_COMPLETE:
        return {
            "reason": OUT_OF_PACKAGING_REASON,
            "stage": "sealing",
            "material": str(meta.get("material_type") or "cards").strip() or "cards",
            "state": "blistered_not_fully_sealed",
            "blocking_finalize": True,
            "source_event_id": event.get("id"),
            "source_event_type": et,
            "occurred_at": event.get("occurred_at"),
        }
    if et == WC.EVENT_PACKAGING_SNAPSHOT:
        return {
            "reason": OUT_OF_PACKAGING_REASON,
            "stage": "packaging",
            "material": str(meta.get("material_type") or "display_boxes").strip()
            or "display_boxes",
            "state": "sealed_not_fully_packed",
            "blocking_finalize": True,
            "source_event_id": event.get("id"),
            "source_event_type": et,
            "occurred_at": event.get("occurred_at"),
        }
    return None


def active_out_of_packaging_shortages(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return unresolved out-of-packaging states from the event fold.

    A normal later submit in the same stage clears that stage's shortage. The finalizer treats these
    facts as blocking policy; the floor UI treats them as display/action facts.
    """
    active: dict[str, dict[str, Any]] = {}
    for event in events:
        et = str(event.get("event_type") or "")
        shortage = _shortage_for_event(event)
        if shortage:
            active[shortage["stage"]] = shortage
            continue

        if et == WC.EVENT_SEALING_COMPLETE:
            active.pop("sealing", None)
        elif et == WC.EVENT_PACKAGING_SNAPSHOT:
            active.pop("packaging", None)
        elif et == WC.EVENT_BAG_FINALIZED:
            active.clear()
    return list(active.values())


def has_blocking_out_of_packaging_shortage(events: list[dict[str, Any]]) -> bool:
    return any(s.get("blocking_finalize") for s in active_out_of_packaging_shortages(events))

