"""Resolve receiving ``bags`` rows for workflow QR assignment (flavor + box + bag #)."""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List


def find_unassigned_inventory_bags_by_flavor_box_bag(
    conn: sqlite3.Connection,
    *,
    tablet_type_id: int,
    box_number: int,
    bag_number: int,
) -> List[Dict[str, Any]]:
    """
    Bags matching tablet type + small-box number + bag number, on open published receives,
    excluding closed bags. Includes bags marked ``reserved_for_bottles`` (variety/bottle deduction
    preference does not block QR workflow assignment).
    Only bags not yet linked to ``workflow_bags.inventory_bag_id``.
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
        LEFT JOIN workflow_bags wb ON wb.inventory_bag_id = b.id
        WHERE wb.id IS NULL
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
