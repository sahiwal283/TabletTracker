"""Shared helpers for the QR-card bag assignment form."""

from __future__ import annotations

from typing import Any

from flask import url_for

# Hidden form field value: embedded assign forms redirect back to Command Center after POST.
ASSIGN_BAG_RETURN_COMMAND_CENTER = "command_center"


def load_workflow_products(conn) -> list[dict[str, Any]]:
    """Products eligible for QR workflow bag assignment.

    Category must match product config / admin: ``COALESCE(TRIM(pd.category), tt.category)``.
    Using raw ``pd.category`` OR ``tt.category`` alone mislabels groups (e.g. ``MIT A`` vs ``Hyroxi MIT A``).
    """
    rows = conn.execute(
        """
        SELECT pd.id, pd.product_name, pd.tablet_type_id,
               COALESCE(NULLIF(TRIM(pd.category), ''), tt.category) AS category,
               COALESCE(pd.is_bottle_product, 0) AS is_bottle_product,
               COALESCE(pd.is_variety_pack, 0) AS is_variety_pack
        FROM product_details pd
        LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
        ORDER BY
            COALESCE(NULLIF(TRIM(pd.category), ''), tt.category, 'ZZZ'),
            COALESCE(pd.is_variety_pack, 0),
            pd.product_name
        LIMIT 500
        """
    ).fetchall()
    return [dict(p) for p in rows]


def load_workflow_tablet_types(conn) -> list[dict[str, Any]]:
    """Tablet/flavor choices for raw-material QR bag assignment."""
    rows = conn.execute(
        """
        SELECT id, tablet_type_name, category, inventory_item_id
        FROM tablet_types
        ORDER BY COALESCE(NULLIF(TRIM(category), ''), 'ZZZ'), tablet_type_name
        LIMIT 500
        """
    ).fetchall()
    return [dict(t) for t in rows]


def parse_nonnegative_int(raw: object) -> int | None:
    """Parse an optional non-negative integer form field."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        value = int(s)
    except ValueError:
        return None
    if value < 0:
        return None
    return value


def build_assign_bag_context(
    *,
    products: list[dict[str, Any]],
    tablet_types: list[dict[str, Any]] | None = None,
    ambiguous_matches: list[dict[str, Any]] | None = None,
    form_product_id: int | None = None,
    form_tablet_type_id: int | None = None,
    form_box_number: int | None = None,
    form_bag_number: int | None = None,
    form_card_scan_token: str | None = None,
    form_receipt_number: str | None = None,
    form_hand_packed: bool = False,
    return_to: str = "",
    restart_url: str | None = None,
    products_load_failed: bool = False,
) -> dict[str, Any]:
    """Template context for the shared QR-card bag assignment form."""
    return {
        "products": products,
        "tablet_types": tablet_types or [],
        "ambiguous_matches": ambiguous_matches,
        "form_product_id": form_product_id,
        "form_tablet_type_id": form_tablet_type_id,
        "form_box_number": form_box_number,
        "form_bag_number": form_bag_number,
        "form_card_scan_token": form_card_scan_token,
        "form_receipt_number": form_receipt_number,
        "form_hand_packed": bool(form_hand_packed),
        "return_to": return_to,
        "restart_url": restart_url or url_for("workflow_staff.new_bag"),
        "products_load_failed": bool(products_load_failed),
    }
