"""Apply incremental good/damaged deltas to po_lines and purchase_orders (SQLite)."""


def apply_po_line_delta(conn, po_id: int, inventory_item_id: str, good_delta: int, damaged_delta: int = 0) -> bool:
    """Increment po_lines and refresh purchase_orders header. Returns False if no matching line."""
    row = conn.execute(
        """
        SELECT id FROM po_lines
        WHERE po_id = ? AND inventory_item_id = ?
        LIMIT 1
        """,
        (po_id, inventory_item_id),
    ).fetchone()
    if not row:
        return False
    conn.execute(
        """
        UPDATE po_lines
        SET good_count = good_count + ?, damaged_count = damaged_count + ?
        WHERE id = ?
        """,
        (good_delta, damaged_delta, row["id"]),
    )
    totals = conn.execute(
        """
        SELECT
            COALESCE(SUM(quantity_ordered), 0) AS total_ordered,
            COALESCE(SUM(good_count), 0) AS total_good,
            COALESCE(SUM(damaged_count), 0) AS total_damaged
        FROM po_lines
        WHERE po_id = ?
        """,
        (po_id,),
    ).fetchone()
    rem = totals["total_ordered"] - totals["total_good"] - totals["total_damaged"]
    conn.execute(
        """
        UPDATE purchase_orders
        SET ordered_quantity = ?, current_good_count = ?, current_damaged_count = ?,
            remaining_quantity = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            totals["total_ordered"],
            totals["total_good"],
            totals["total_damaged"],
            rem,
            po_id,
        ),
    )
    return True
