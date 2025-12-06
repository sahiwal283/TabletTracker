"""
Purchase Order business logic service
"""
from typing import Dict, List, Optional
from app.utils.db_utils import db_query, db_execute, db_connection
from app.utils.calculations import calculate_tablet_totals


class POService:
    """Service for Purchase Order operations"""
    
    @staticmethod
    def get_all_pos(include_overs: bool = True) -> List[Dict]:
        """Get all purchase orders, optionally organized with overs POs"""
        with db_connection() as conn:
            all_pos = db_query('''
                SELECT po.*, 
                       COUNT(DISTINCT pl.id) as line_count,
                       COALESCE(SUM(pl.quantity_ordered), 0) as total_ordered,
                       COALESCE(po.internal_status, 'Active') as status_display,
                       (SELECT COUNT(DISTINCT ws.id) 
                        FROM warehouse_submissions ws 
                        WHERE ws.assigned_po_id = po.id) as submission_count
                FROM purchase_orders po
                LEFT JOIN po_lines pl ON po.id = pl.po_id
                GROUP BY po.id
                ORDER BY po.po_number DESC
            ''', fetch_all=True)
            
            if not include_overs:
                return [dict(po) for po in all_pos]
            
            # Organize POs: group overs POs under their parents
            organized_pos = []
            overs_pos = {}
            
            # First pass: separate overs POs
            for po in all_pos:
                po_dict = dict(po)
                if po_dict.get('parent_po_number'):
                    parent_num = po_dict['parent_po_number']
                    if parent_num not in overs_pos:
                        overs_pos[parent_num] = []
                    overs_pos[parent_num].append(po_dict)
            
            # Second pass: add parent POs and their overs
            for po in all_pos:
                po_dict = dict(po)
                if not po_dict.get('parent_po_number'):
                    po_dict['is_overs'] = False
                    organized_pos.append(po_dict)
                    
                    if po_dict['po_number'] in overs_pos:
                        for overs_po in overs_pos[po_dict['po_number']]:
                            overs_po['is_overs'] = True
                            organized_pos.append(overs_po)
            
            return organized_pos
    
    @staticmethod
    def get_po_by_id(po_id: int) -> Optional[Dict]:
        """Get a single PO by ID"""
        return db_query(
            'SELECT * FROM purchase_orders WHERE id = ?',
            (po_id,),
            fetch_one=True
        )
    
    @staticmethod
    def get_po_lines(po_id: int) -> List[Dict]:
        """Get all lines for a PO"""
        return db_query(
            'SELECT * FROM po_lines WHERE po_id = ? ORDER BY id',
            (po_id,),
            fetch_all=True
        )
    
    @staticmethod
    def update_po_counts(po_id: int):
        """Recalculate and update PO header counts from line items"""
        with db_connection() as conn:
            totals = db_query('''
                SELECT 
                    COALESCE(SUM(quantity_ordered), 0) as total_ordered,
                    COALESCE(SUM(good_count), 0) as total_good,
                    COALESCE(SUM(damaged_count), 0) as total_damaged,
                    COALESCE(SUM(machine_good_count), 0) as total_machine_good,
                    COALESCE(SUM(machine_damaged_count), 0) as total_machine_damaged
                FROM po_lines 
                WHERE po_id = ?
            ''', (po_id,), fetch_one=True)
            
            remaining = totals['total_ordered'] - totals['total_good'] - totals['total_damaged']
            
            db_execute('''
                UPDATE purchase_orders 
                SET ordered_quantity = ?, 
                    current_good_count = ?, 
                    current_damaged_count = ?,
                    machine_good_count = ?,
                    machine_damaged_count = ?,
                    remaining_quantity = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (
                totals['total_ordered'],
                totals['total_good'],
                totals['total_damaged'],
                totals['total_machine_good'],
                totals['total_machine_damaged'],
                remaining,
                po_id
            ))

