"""
Purchase Order API routes.

This module handles all purchase order-related API endpoints.
"""
from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
import traceback
from app.utils.db_utils import db_read_only, db_transaction
from app.utils.auth_utils import role_required
from app.services.zoho_service import zoho_api

bp = Blueprint('api_purchase_orders', __name__)


@bp.route('/api/sync_zoho_pos', methods=['GET', 'POST'])
@role_required('dashboard')
def sync_zoho_pos():
    """Sync Purchase Orders from Zoho Inventory"""
    try:
        current_app.logger.info("🔄 Starting Zoho PO sync...")
        with db_transaction() as conn:
            current_app.logger.info("✅ Database connection established")
            
            current_app.logger.info("📡 Calling Zoho API sync function...")
            success, message = zoho_api.sync_tablet_pos_to_db(conn)
            current_app.logger.info(f"✅ Sync completed. Success: {success}, Message: {message}")
            
            if success:
                return jsonify({'message': message, 'success': True})
            else:
                return jsonify({'error': message, 'success': False}), 400
    except Exception as e:
        error_trace = traceback.format_exc()
        current_app.logger.error(f"❌ Sync Zoho POs error: {str(e)}")
        current_app.logger.error(f"Traceback: {error_trace}")
        return jsonify({'error': f'Sync failed: {str(e)}', 'success': False}), 500


@bp.route('/api/create_overs_po/<int:po_id>', methods=['POST'])
@role_required('dashboard')
def create_overs_po(po_id):
    """Create an overs PO in Zoho for a parent PO"""
    conn = None
    try:
        with db_transaction() as conn:
            # Get parent PO details
            parent_po = conn.execute('''
            SELECT po_number, tablet_type, ordered_quantity, current_good_count, 
                   current_damaged_count, remaining_quantity, zoho_po_id
            FROM purchase_orders
            WHERE id = ?
        ''', (po_id,)).fetchone()
        
        if not parent_po:
            return jsonify({'error': 'Parent PO not found'}), 404
        
        # Calculate overs (negative remaining_quantity means overs)
        overs_quantity = abs(min(0, parent_po['remaining_quantity']))
        
        if overs_quantity == 0:
            return jsonify({'error': 'No overs found for this PO'}), 400
        
        # Get line items with overs (negative remaining means overs)
        lines_with_overs = conn.execute('''
            SELECT pl.*, 
                   (pl.quantity_ordered - pl.good_count - pl.damaged_count) as line_remaining
            FROM po_lines pl
            WHERE pl.po_id = ? 
            AND (pl.quantity_ordered - pl.good_count - pl.damaged_count) < 0
        ''', (po_id,)).fetchall()
        
        if not lines_with_overs:
            return jsonify({'error': 'No line items with overs found'}), 400
        
        # Generate overs PO number
        overs_po_number = f"{parent_po['po_number']}-OVERS"
        
        # Get parent PO details from Zoho to use as template
        parent_zoho_po = None
        if parent_po['zoho_po_id']:
            parent_zoho_po = zoho_api.get_purchase_order_details(parent_po['zoho_po_id'])
        
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
            return jsonify({
                'success': True,
                'message': f'Overs PO "{overs_po_number}" created successfully in Zoho!',
                'overs_po_number': overs_po_number,
                'zoho_po_id': created_po.get('purchaseorder_id'),
                'total_overs': overs_quantity,
                'instructions': 'The overs PO has been created in Zoho. You can now sync POs to import it into the app.'
            })
        else:
            error_msg = result.get('message', 'Unknown error') if result else 'No response from Zoho API'
            return jsonify({
                'success': False,
                'error': f'Failed to create PO in Zoho: {error_msg}'
            }), 500
    except Exception as e:
        current_app.logger.error(f"Error creating overs PO: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/create_overs_po_info/<int:po_id>')
@role_required('dashboard')
def get_overs_po_info(po_id):
    """Get information needed to create an overs PO for a parent PO (for preview)"""
    try:
        with db_read_only() as conn:
            # Get parent PO details
            parent_po = conn.execute('''
                SELECT po_number, tablet_type, ordered_quantity, current_good_count, 
                       current_damaged_count, remaining_quantity
                FROM purchase_orders
                WHERE id = ?
            ''', (po_id,)).fetchone()
            
            if not parent_po:
                return jsonify({'error': 'Parent PO not found'}), 404
            
            # Calculate overs (negative remaining_quantity means overs)
            overs_quantity = abs(min(0, parent_po['remaining_quantity']))
            
            # Get line items with overs (negative remaining means overs)
            lines_with_overs = conn.execute('''
                SELECT pl.*, 
                       (pl.quantity_ordered - pl.good_count - pl.damaged_count) as line_remaining
                FROM po_lines pl
                WHERE pl.po_id = ? 
                AND (pl.quantity_ordered - pl.good_count - pl.damaged_count) < 0
            ''', (po_id,)).fetchall()
            
            # Generate overs PO number
            overs_po_number = f"{parent_po['po_number']}-OVERS"
            
            # Prepare line items for overs PO
            overs_line_items = []
            total_overs = 0
            for line in lines_with_overs:
                line_overs = abs(line['line_remaining'])
                total_overs += line_overs
                overs_line_items.append({
                    'inventory_item_id': line['inventory_item_id'],
                    'line_item_name': line['line_item_name'],
                    'overs_quantity': line_overs,
                    'original_ordered': line['quantity_ordered']
                })
            
            return jsonify({
                'success': True,
                'parent_po_number': parent_po['po_number'],
                'overs_po_number': overs_po_number,
                'tablet_type': parent_po['tablet_type'],
                'total_overs': overs_quantity,
                'line_items': overs_line_items,
                'instructions': f'Click "Create in Zoho" to automatically create this overs PO in Zoho, or copy details to create manually.'
            })
    except Exception as e:
        current_app.logger.error(f"Error getting overs PO info: {str(e)}")
        return jsonify({'error': str(e)}), 500


@bp.route('/api/po_lines/<int:po_id>')
def get_po_lines(po_id):
    """Get line items for a specific PO"""
    try:
        with db_read_only() as conn:
            lines = conn.execute('''
                SELECT * FROM po_lines WHERE po_id = ? ORDER BY line_item_name
            ''', (po_id,)).fetchall()
            
            # Count unverified submissions for this PO
            unverified_query = '''
                SELECT COUNT(*) as count
                FROM warehouse_submissions
                WHERE assigned_po_id = ? AND COALESCE(po_assignment_verified, 0) = 0
            '''
            unverified_count_row = conn.execute(unverified_query, (po_id,)).fetchone()
            unverified_count = dict(unverified_count_row) if unverified_count_row else None
            
            # Get current PO details including status and parent
            current_po_row = conn.execute('''
                SELECT po_number, closed, internal_status, zoho_status, parent_po_number
                FROM purchase_orders WHERE id = ?
            ''', (po_id,)).fetchone()
            current_po = dict(current_po_row) if current_po_row else None
            current_po_number = current_po.get('po_number') if current_po else None
            po_status = None
            if current_po:
                # Determine status: cancelled takes priority, then closed, then internal_status, then zoho_status
                if current_po.get('internal_status') == 'Cancelled':
                    po_status = 'Cancelled'
                elif current_po.get('closed'):
                    po_status = 'Closed'
                elif current_po.get('internal_status'):
                    po_status = current_po.get('internal_status')
                elif current_po.get('zoho_status'):
                    po_status = current_po.get('zoho_status')
                else:
                    po_status = 'Open'
            
            # Check if there's an overs PO linked to this parent PO
            overs_po = None
            if current_po_number:
                overs_po_record_row = conn.execute('''
                    SELECT id, po_number 
                    FROM purchase_orders 
                    WHERE parent_po_number = ?
                ''', (current_po_number,)).fetchone()
                if overs_po_record_row:
                    overs_po_record = dict(overs_po_record_row)
                    overs_po = {
                        'id': overs_po_record.get('id'),
                        'po_number': overs_po_record.get('po_number')
                    }
            
            # Check if this is an overs PO (has a parent)
            parent_po = None
            if current_po and current_po.get('parent_po_number'):
                parent_po_record_row = conn.execute('''
                    SELECT id, po_number 
                    FROM purchase_orders 
                    WHERE po_number = ?
                ''', (current_po.get('parent_po_number'),)).fetchone()
                if parent_po_record_row:
                    parent_po_record = dict(parent_po_record_row)
                    parent_po = {
                        'id': parent_po_record.get('id'),
                        'po_number': parent_po_record.get('po_number')
                    }
            
            # Calculate round numbers, received counts, and submission counts for each line item
            lines_with_rounds = []
            for line in lines:
                line_dict = dict(line)
                round_number = None
                
                if line_dict.get('inventory_item_id') and current_po_number:
                    # Find all POs containing this inventory_item_id, ordered by PO number (oldest first)
                    pos_with_item = conn.execute('''
                        SELECT DISTINCT po.po_number, po.id
                        FROM purchase_orders po
                        JOIN po_lines pl ON po.id = pl.po_id
                        WHERE pl.inventory_item_id = ?
                        ORDER BY po.po_number ASC
                    ''', (line_dict['inventory_item_id'],)).fetchall()
                    
                    # Find the position of current PO in this list (1-indexed = round number)
                    for idx, po_row in enumerate(pos_with_item, start=1):
                        if po_row['po_number'] == current_po_number:
                            round_number = idx
                            break
                
                line_dict['round_number'] = round_number
                
                # Get received count from bags (bag_label_count sum for this PO and inventory_item_id)
                received_count_row = conn.execute('''
                    SELECT COALESCE(SUM(b.bag_label_count), 0) as total_received
                    FROM bags b
                    JOIN small_boxes sb ON b.small_box_id = sb.id
                    JOIN receiving r ON sb.receiving_id = r.id
                    JOIN tablet_types tt ON b.tablet_type_id = tt.id
                    WHERE r.po_id = ? AND tt.inventory_item_id = ?
                ''', (po_id, line_dict.get('inventory_item_id'))).fetchone()
                
                received_count = dict(received_count_row) if received_count_row else None
                line_dict['received_count'] = received_count.get('total_received', 0) if received_count else 0
                
                # Get machine count (from warehouse_submissions)
                machine_count_row = conn.execute('''
                    SELECT COALESCE(SUM(COALESCE(ws.tablets_pressed_into_cards, ws.loose_tablets, 0)), 0) as total_machine
                    FROM warehouse_submissions ws
                    WHERE ws.assigned_po_id = ? 
                    AND ws.inventory_item_id = ? 
                    AND ws.submission_type = 'machine'
                ''', (po_id, line_dict.get('inventory_item_id'))).fetchone()
                
                machine_count = dict(machine_count_row) if machine_count_row else None
                line_dict['machine_count'] = machine_count.get('total_machine', 0) if machine_count else 0
                
                # Get packaged count (from packaged submissions only, NOT bag counts)
                packaged_count_row = conn.execute('''
                    SELECT COALESCE(SUM(
                        (COALESCE(ws.displays_made, 0) * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
                        (COALESCE(ws.packs_remaining, 0) * COALESCE(pd.tablets_per_package, 0)) +
                        COALESCE(ws.loose_tablets, 0)
                    ), 0) as total_packaged
                    FROM warehouse_submissions ws
                    LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                    WHERE ws.assigned_po_id = ? 
                    AND ws.inventory_item_id = ? 
                    AND ws.submission_type = 'packaged'
                ''', (po_id, line_dict.get('inventory_item_id'))).fetchone()
                
                packaged_count = dict(packaged_count_row) if packaged_count_row else None
                
                # Get bag count separately (from bag count submissions only)
                bag_count_row = conn.execute('''
                    SELECT COALESCE(SUM(COALESCE(ws.loose_tablets, 0)), 0) as total_bag
                    FROM warehouse_submissions ws
                    WHERE ws.assigned_po_id = ? 
                    AND ws.inventory_item_id = ? 
                    AND ws.submission_type = 'bag'
                ''', (po_id, line_dict.get('inventory_item_id'))).fetchone()
                
                bag_count = dict(bag_count_row) if bag_count_row else None
                line_dict['packaged_count'] = packaged_count.get('total_packaged', 0) if packaged_count else 0
                line_dict['bag_count'] = bag_count.get('total_bag', 0) if bag_count else 0
                
                lines_with_rounds.append(line_dict)
            
            result = {
                'lines': lines_with_rounds,
                'has_unverified_submissions': unverified_count.get('count', 0) > 0 if unverified_count else False,
                'unverified_count': unverified_count.get('count', 0) if unverified_count else 0,
                'po_status': po_status,
                'overs_po': overs_po,
                'parent_po': parent_po
            }
            
            return jsonify(result)
    except Exception as e:
        current_app.logger.error(f"Error getting PO lines: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': f'Failed to get PO lines: {str(e)}'}), 500

