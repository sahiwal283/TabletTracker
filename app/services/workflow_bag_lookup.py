"""Resolve receiving ``bags`` rows for workflow QR assignment (flavor + box + bag #)."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.services.product_tablet_allowlist import allowed_tablet_type_ids_for_product


def find_unassigned_inventory_bags_by_flavor_box_bag(
    conn: sqlite3.Connection,
    *,
    tablet_type_id: int,
    box_number: int,
    bag_number: int,
) -> list[dict[str, Any]]:
    """
    Bags matching tablet type + small-box number + bag number, on open published receives,
    excluding closed bags. Includes bags marked ``reserved_for_bottles`` (variety/bottle deduction
    preference does not block QR workflow assignment).
    Only bags not currently linked to an active QR card are excluded; finalized/released prior
    workflow links do not block reuse when tablets remain.
    """
    rows = conn.execute(
        """
        SELECT b.id, b.bag_number, sb.box_number, b.tablet_type_id,
               tt.tablet_type_name, r.id AS receiving_id, po.po_number, r.received_date
        FROM bags b
        JOIN small_boxes sb ON b.small_box_id = sb.id
        JOIN receiving r ON sb.receiving_id = r.id
        LEFT JOIN purchase_orders po ON r.po_id = po.id
        JOIN tablet_types tt ON b.tablet_type_id = tt.id
        WHERE NOT EXISTS (
            SELECT 1
            FROM workflow_bags wb
            JOIN qr_cards qc ON qc.assigned_workflow_bag_id = wb.id
            WHERE wb.inventory_bag_id = b.id
              AND qc.status = 'assigned'
        )
          AND b.tablet_type_id = ?
          AND sb.box_number = ?
          AND b.bag_number = ?
          AND COALESCE(b.status, 'Available') != 'Closed'
          AND COALESCE(r.closed, 0) = 0
          AND COALESCE(r.status, 'published') = 'published'
        ORDER BY r.received_date DESC, b.id
        """,
        (tablet_type_id, box_number, bag_number),
    ).fetchall()
    return [dict(r) for r in rows]


def find_unassigned_inventory_bags_for_product(
    conn: sqlite3.Connection,
    *,
    product_id: int,
    box_number: int,
    bag_number: int,
) -> list[dict[str, Any]]:
    """Union of unassigned bags for each allowed tablet type for this finished product."""
    seen: dict[int, dict[str, Any]] = {}
    for tid in allowed_tablet_type_ids_for_product(conn, int(product_id)):
        for row in find_unassigned_inventory_bags_by_flavor_box_bag(
            conn,
            tablet_type_id=tid,
            box_number=box_number,
            bag_number=bag_number,
        ):
            seen[int(row["id"])] = row
    out = list(seen.values())
    out.sort(key=lambda m: (str(m.get("received_date") or ""), int(m.get("id") or 0)), reverse=True)
    return out


def find_unassigned_inventory_bags_for_tablet(
    conn: sqlite3.Connection,
    *,
    tablet_type_id: int,
    box_number: int,
    bag_number: int,
) -> list[dict[str, Any]]:
    """Unassigned receiving bags for a selected physical tablet/flavor."""
    rows = find_unassigned_inventory_bags_by_flavor_box_bag(
        conn,
        tablet_type_id=int(tablet_type_id),
        box_number=box_number,
        bag_number=bag_number,
    )
    rows.sort(key=lambda m: (str(m.get("received_date") or ""), int(m.get("id") or 0)), reverse=True)
    return rows
