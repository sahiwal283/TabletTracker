"""Deferred finished-product mapping for tablet-first QR workflow bags."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.services import workflow_constants as WC
from app.services.product_tablet_allowlist import (
    eligible_products_for_tablet_type,
    product_allows_tablet_type,
)
from app.services.workflow_append import append_workflow_event

_CARD_STATION_KINDS = {"blister", "sealing", "combined"}
_BOTTLE_STATION_KINDS = {"bottle_handpack", "bottle_cap_seal", "bottle_stickering"}


def production_flow_for_station_kind(station_kind: str | None) -> str | None:
    """Map a floor station kind to the product family it proves."""
    kind = (station_kind or "").strip().lower()
    if kind in _CARD_STATION_KINDS:
        return "card"
    if kind in _BOTTLE_STATION_KINDS:
        return "bottle"
    return None


def production_flow_for_event_or_station(event_type: str, station_kind: str | None) -> str | None:
    """Use explicit event flow first, then station kind for claim/resume events."""
    et = (event_type or "").strip().upper()
    if et in {WC.EVENT_BLISTER_COMPLETE, WC.EVENT_SEALING_COMPLETE, WC.EVENT_OPERATOR_CHANGE}:
        return "card"
    if et in {
        WC.EVENT_BOTTLE_HANDPACK_COMPLETE,
        WC.EVENT_BOTTLE_CAP_SEAL_COMPLETE,
        WC.EVENT_BOTTLE_STICKER_COMPLETE,
    }:
        return "bottle"
    if et in {WC.EVENT_BAG_CLAIMED, WC.EVENT_STATION_RESUMED}:
        return production_flow_for_station_kind(station_kind)
    return None


def _bag_mapping_context(conn: sqlite3.Connection, workflow_bag_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT wb.id AS workflow_bag_id, wb.product_id, wb.inventory_bag_id,
               b.tablet_type_id, tt.tablet_type_name,
               pd.product_name AS current_product_name,
               COALESCE(pd.is_bottle_product, 0) AS current_is_bottle_product,
               COALESCE(pd.is_variety_pack, 0) AS current_is_variety_pack
        FROM workflow_bags wb
        LEFT JOIN bags b ON b.id = wb.inventory_bag_id
        LEFT JOIN tablet_types tt ON tt.id = b.tablet_type_id
        LEFT JOIN product_details pd ON pd.id = wb.product_id
        WHERE wb.id = ?
        """,
        (int(workflow_bag_id),),
    ).fetchone()
    return dict(row) if row else None


def _product_flow(row: dict[str, Any]) -> str:
    return "bottle" if int(row.get("is_bottle_product") or 0) == 1 else "card"


def _current_product_flow(ctx: dict[str, Any]) -> str:
    if int(ctx.get("current_is_bottle_product") or 0) == 1 or int(ctx.get("current_is_variety_pack") or 0) == 1:
        return "bottle"
    return "card"


def _candidate_payload(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in candidates:
        out.append(
            {
                "id": int(c["id"]),
                "product_id": int(c["id"]),
                "product_name": c.get("product_name"),
                "production_flow": _product_flow(c),
                "category": c.get("category"),
            }
        )
    return out


def ensure_workflow_bag_product_for_flow(
    conn: sqlite3.Connection,
    *,
    workflow_bag_id: int,
    production_flow: str | None,
    selected_product_id: int | None = None,
    station_id: int | None = None,
    user_id: int | None = None,
    device_id: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Ensure ``workflow_bags.product_id`` is set once the floor proves card/bottle flow.

    Returns ``ok`` when already mapped or freshly mapped. Returns ``reject`` with a
    machine-readable reason when the tablet cannot be mapped without human/config help.
    """
    flow = (production_flow or "").strip().lower()
    if flow not in {"card", "bottle"}:
        return "ok", {"mapped": False, "reason": "flow_not_applicable"}

    ctx = _bag_mapping_context(conn, int(workflow_bag_id))
    if not ctx:
        return "reject", {"reason": "workflow_bag_not_found"}

    current_product_id = ctx.get("product_id")
    if current_product_id is not None:
        current_flow = _current_product_flow(ctx)
        if current_flow != flow:
            return "reject", {
                "reason": "wrong_production_flow",
                "production_flow": current_flow,
                "event_flow": flow,
                "product_id": int(current_product_id),
                "product_name": ctx.get("current_product_name"),
            }
        return "ok", {
            "mapped": False,
            "reason": "already_mapped",
            "product_id": int(current_product_id),
            "product_name": ctx.get("current_product_name"),
            "production_flow": current_flow,
        }

    if ctx.get("inventory_bag_id") is None or ctx.get("tablet_type_id") is None:
        return "reject", {"reason": "missing_inventory_tablet", "production_flow": flow}

    tablet_type_id = int(ctx["tablet_type_id"])
    candidates = eligible_products_for_tablet_type(
        conn,
        tablet_type_id=tablet_type_id,
        production_flow=flow,
    )

    resolution = "single_match"
    chosen: dict[str, Any] | None = None
    if selected_product_id is not None:
        selected = int(selected_product_id)
        for c in candidates:
            if int(c["id"]) == selected:
                chosen = c
                resolution = "operator_selected"
                break
        if chosen is None:
            return "reject", {
                "reason": "selected_product_not_allowed",
                "production_flow": flow,
                "tablet_type_id": tablet_type_id,
                "tablet_type_name": ctx.get("tablet_type_name"),
                "candidates": _candidate_payload(candidates),
            }
    elif len(candidates) == 1:
        chosen = candidates[0]
    elif len(candidates) > 1:
        return "reject", {
            "reason": "ambiguous_product_mapping",
            "production_flow": flow,
            "tablet_type_id": tablet_type_id,
            "tablet_type_name": ctx.get("tablet_type_name"),
            "candidates": _candidate_payload(candidates),
        }
    else:
        return "reject", {
            "reason": "no_product_mapping",
            "production_flow": flow,
            "tablet_type_id": tablet_type_id,
            "tablet_type_name": ctx.get("tablet_type_name"),
        }

    product_id = int(chosen["id"])
    if not product_allows_tablet_type(conn, product_id, tablet_type_id):
        return "reject", {
            "reason": "product_bag_tablet_type_mismatch",
            "production_flow": flow,
            "tablet_type_id": tablet_type_id,
            "product_id": product_id,
        }

    conn.execute(
        "UPDATE workflow_bags SET product_id = ? WHERE id = ? AND product_id IS NULL",
        (product_id, int(workflow_bag_id)),
    )
    append_workflow_event(
        conn,
        WC.EVENT_PRODUCT_MAPPED,
        {
            "product_id": product_id,
            "product_name": chosen.get("product_name"),
            "tablet_type_id": tablet_type_id,
            "tablet_type_name": ctx.get("tablet_type_name"),
            "production_flow": flow,
            "resolution": resolution,
            "station_id": station_id,
        },
        int(workflow_bag_id),
        station_id=station_id,
        user_id=user_id,
        device_id=device_id,
    )
    return "ok", {
        "mapped": True,
        "product_id": product_id,
        "product_name": chosen.get("product_name"),
        "production_flow": flow,
        "resolution": resolution,
    }
