"""
Purchase Order service for business logic related to purchase orders.
"""
from typing import Dict, List, Optional, Any
from app.utils.db_utils import db_read_only, db_transaction, PurchaseOrderRepository
from app.services.zoho_service import zoho_api
from datetime import datetime


def get_purchase_order_with_details(po_id: int) -> Optional[Dict[str, Any]]:
    """
    Get purchase order with all related details.
    
    Args:
        po_id: Purchase order ID
    
    Returns:
        Dictionary with PO details or None if not found
    """
    with db_read_only() as conn:
        po = PurchaseOrderRepository.get_by_id(conn, po_id)
        if not po:
            return None
        
        po_dict = dict(po)
        
        # Get line items
        lines = conn.execute('''
            SELECT * FROM po_lines WHERE po_id = ? ORDER BY line_item_name
        ''', (po_id,)).fetchall()
        po_dict['lines'] = [dict(line) for line in lines]
        
        # Get shipment info
        shipment = conn.execute('''
            SELECT * FROM shipments WHERE po_id = ? ORDER BY shipped_date DESC LIMIT 1
        ''', (po_id,)).fetchone()
        if shipment:
            po_dict['shipment'] = dict(shipment)
        
        return po_dict


def calculate_po_totals(po_id: int) -> Dict[str, Any]:
    """
    Calculate totals for a purchase order.
    
    Args:
        po_id: Purchase order ID
    
    Returns:
        Dictionary with calculated totals:
            - total_ordered
            - total_good
            - total_damaged
            - total_remaining
            - line_totals (list of line item totals)
    """
    with db_read_only() as conn:
        po = PurchaseOrderRepository.get_by_id(conn, po_id)
        if not po:
            return {}
        
        # Get line items
        lines = conn.execute('''
            SELECT * FROM po_lines WHERE po_id = ?
        ''', (po_id,)).fetchall()
        
        total_ordered = 0
        total_good = 0
        total_damaged = 0
        line_totals = []
        
        for line in lines:
            line_dict = dict(line)
            ordered = line_dict.get('quantity_ordered', 0) or 0
            good = line_dict.get('good_count', 0) or 0
            damaged = line_dict.get('damaged_count', 0) or 0
            remaining = ordered - good - damaged
            
            total_ordered += ordered
            total_good += good
            total_damaged += damaged
            
            line_totals.append({
                'inventory_item_id': line_dict.get('inventory_item_id'),
                'line_item_name': line_dict.get('line_item_name'),
                'ordered': ordered,
                'good': good,
                'damaged': damaged,
                'remaining': remaining
            })
        
        return {
            'total_ordered': total_ordered,
            'total_good': total_good,
            'total_damaged': total_damaged,
            'total_remaining': total_ordered - total_good - total_damaged,
            'line_totals': line_totals
        }


def sync_po_from_zoho(po_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Sync purchase orders from Zoho.
    
    Args:
        po_id: Optional specific PO ID to sync (if None, syncs all)
    
    Returns:
        Dictionary with sync results:
            - success (bool)
            - message (str)
            - synced_count (int)
    """
    try:
        with db_transaction() as conn:
            success, message = zoho_api.sync_tablet_pos_to_db(conn)
            
            if success:
                # Count synced POs
                synced_count = conn.execute('''
                    SELECT COUNT(*) as count FROM purchase_orders WHERE zoho_po_id IS NOT NULL
                ''').fetchone()['count']
                
                return {
                    'success': True,
                    'message': message,
                    'synced_count': synced_count
                }
            else:
                return {
                    'success': False,
                    'message': message,
                    'synced_count': 0
                }
    except Exception as e:
        return {
            'success': False,
            'message': f'Sync failed: {str(e)}',
            'synced_count': 0
        }


def create_overs_po(parent_po_id: int) -> Dict[str, Any]:
    """
    Create an overs PO in Zoho for a parent PO.
    
    Args:
        parent_po_id: ID of the parent PO
    
    Returns:
        Dictionary with creation results:
            - success (bool)
            - overs_po_number (str)
            - zoho_po_id (str, optional)
            - total_overs (int)
            - error (str, optional)
    """
    with db_transaction() as conn:
        # Get parent PO details
        parent_po = PurchaseOrderRepository.get_by_id(conn, parent_po_id)
        if not parent_po:
            return {
                'success': False,
                'error': 'Parent PO not found'
            }
        
        # Calculate overs (negative remaining_quantity means overs)
        remaining = parent_po.get('remaining_quantity', 0) or 0
        overs_quantity = abs(min(0, remaining))
        
        if overs_quantity == 0:
            return {
                'success': False,
                'error': 'No overs found for this PO'
            }
        
        # Get line items with overs
        lines_with_overs = conn.execute('''
            SELECT pl.*, 
                   (pl.quantity_ordered - pl.good_count - pl.damaged_count) as line_remaining
            FROM po_lines pl
            WHERE pl.po_id = ? 
            AND (pl.quantity_ordered - pl.good_count - pl.damaged_count) < 0
        ''', (parent_po_id,)).fetchall()
        
        if not lines_with_overs:
            return {
                'success': False,
                'error': 'No line items with overs found'
            }
        
        # Generate overs PO number
        overs_po_number = f"{parent_po['po_number']}-OVERS"
        
        # Get parent PO details from Zoho to use as template
        parent_zoho_po = None
        zoho_po_id = parent_po.get('zoho_po_id')
        if zoho_po_id:
            parent_zoho_po = zoho_api.get_purchase_order_details(zoho_po_id)
        
        # Build line items for overs PO
        line_items = []
        for line in lines_with_overs:
            line_overs = abs(line['line_remaining'])
            line_items.append({
                'item_id': line['inventory_item_id'],
                'name': line['line_item_name'],
                'quantity': line_overs,
                'rate': 0  # Free/overs items typically have $0 rate
            })
        
        # Build PO data for Zoho
        po_data = {
            'purchaseorder_number': overs_po_number,
            'date': datetime.now().date().isoformat(),
            'line_items': line_items,
            'cf_tablets': True,  # Mark as tablet PO
            'notes': f'Overs PO for {parent_po["po_number"]} - {overs_quantity:,} tablets',
            'status': 'draft'  # Create as draft so it can be reviewed
        }
        
        # Copy vendor and other details from parent PO if available
        if parent_zoho_po and 'purchaseorder' in parent_zoho_po:
            parent_data = parent_zoho_po['purchaseorder']
            if 'vendor_id' in parent_data:
                po_data['vendor_id'] = parent_data['vendor_id']
            if 'vendor_name' in parent_data:
                po_data['vendor_name'] = parent_data['vendor_name']
            if 'currency_code' in parent_data:
                po_data['currency_code'] = parent_data['currency_code']
        
        # Create PO in Zoho
        result = zoho_api.create_purchase_order(po_data)
        
        if result and 'purchaseorder' in result:
            created_po = result['purchaseorder']
            return {
                'success': True,
                'overs_po_number': overs_po_number,
                'zoho_po_id': created_po.get('purchaseorder_id'),
                'total_overs': overs_quantity
            }
        else:
            error_msg = result.get('message', 'Unknown error') if result else 'No response from Zoho API'
            return {
                'success': False,
                'error': f'Failed to create PO in Zoho: {error_msg}'
            }

