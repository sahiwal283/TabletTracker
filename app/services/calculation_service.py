"""
Business logic for tablet calculations and PO allocation
"""

from ..models.database import get_db

class CalculationService:
    """Service for tablet calculations and business logic"""
    
    @staticmethod
    def calculate_total_tablets(displays_made, packs_remaining, loose_tablets, damaged_tablets, 
                               packages_per_display, tablets_per_package):
        """Calculate total tablets from form inputs"""
        return (
            (displays_made * packages_per_display * tablets_per_package) +
            (packs_remaining * tablets_per_package) + 
            loose_tablets + 
            damaged_tablets
        )
    
    @staticmethod
    def find_matching_po(inventory_item_id):
        """Find the oldest open PO with matching inventory item ID (FIFO allocation)"""
        conn = get_db()
        matching_po = conn.execute('''
            SELECT po.id, po.po_number
            FROM purchase_orders po
            JOIN po_lines pl ON po.id = pl.po_id
            WHERE pl.inventory_item_id = ? 
            AND po.closed = FALSE
            AND po.remaining_quantity > 0
            ORDER BY po.po_number ASC
            LIMIT 1
        ''', (inventory_item_id,)).fetchone()
        conn.close()
        return matching_po
    
    @staticmethod
    def update_po_quantities(po_id, good_tablets, damaged_tablets):
        """Update PO quantities after submission"""
        from datetime import datetime
        conn = get_db()
        conn.execute('''
            UPDATE purchase_orders 
            SET current_good_count = current_good_count + ?,
                current_damaged_count = current_damaged_count + ?,
                remaining_quantity = ordered_quantity - current_good_count - current_damaged_count,
                updated_at = ?
            WHERE id = ?
        ''', (good_tablets, damaged_tablets, datetime.now(), po_id))
        conn.commit()
        conn.close()
