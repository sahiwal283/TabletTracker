"""
Purchase Order API routes.

This module handles all purchase order-related API endpoints.
"""
from flask import Blueprint, request, jsonify, current_app, session
from datetime import datetime
import traceback
from app.utils.db_utils import db_read_only, db_transaction
from app.utils.auth_utils import role_required
from app.services.zoho_service import zoho_api
from app.services.purchase_order_service import create_overs_po as create_overs_po_service
from app.services.purchase_order_service import get_overs_po_preview
from app.services.purchase_order_service import create_or_update_overs_po_for_push

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
    try:
        result = create_overs_po_service(po_id)
        if result.get('success'):
            instructions = (
                'The overs PO has been created in Zoho. You can now sync POs to import it into the app.'
            )
            if result.get('zoho_note'):
                instructions += ' ' + result['zoho_note']
            return jsonify({
                'success': True,
                'message': f'Overs PO "{result["overs_po_number"]}" created successfully in Zoho!',
                'overs_po_number': result['overs_po_number'],
                'zoho_po_id': result.get('zoho_po_id'),
                'total_overs': result.get('total_overs', 0),
                'instructions': instructions,
            })
        error = result.get('error', 'Failed to create overs PO')
        status_code = 404 if error == 'Parent PO not found' else 400 if 'No overs found' in error or 'No line items with overs found' in error else 500
        return jsonify({'success': False, 'error': error}), status_code
    except Exception as e:
        current_app.logger.error(f"Error creating overs PO: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/create_overs_po_info/<int:po_id>')
@role_required('dashboard')
def get_overs_po_info(po_id):
    """Get information needed to create an overs PO for a parent PO (for preview)"""
    try:
        preview = get_overs_po_preview(po_id)
        if not preview.get('success'):
            return jsonify({'error': preview.get('error', 'Failed to load preview')}), 404
        return jsonify(preview)
    except Exception as e:
        current_app.logger.error(f"Error getting overs PO info: {str(e)}")
        return jsonify({'error': str(e)}), 500


@bp.route('/api/purchase_orders/<int:po_id>/overs_for_zoho_push', methods=['POST'])
@role_required('dashboard')
def overs_for_zoho_push(po_id):
    """Create or update draft overs PO in Zoho using overage from a failed Zoho push (quantity limit)."""
    user_role = session.get('employee_role')
    is_admin = session.get('admin_authenticated')
    if user_role not in ['manager', 'admin'] and not is_admin:
        return jsonify({'success': False, 'error': 'Only managers and admins can create overs POs'}), 403
    try:
        body = request.get_json() or {}
        overage = body.get('overage_tablets')
        inventory_item_id = (body.get('inventory_item_id') or '').strip()
        line_item_name = (body.get('line_item_name') or 'Line item').strip()
        try:
            overage_int = int(overage)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'overage_tablets must be a positive integer'}), 400
        if overage_int <= 0:
            return jsonify({'success': False, 'error': 'overage_tablets must be positive'}), 400
        if not inventory_item_id:
            return jsonify({'success': False, 'error': 'inventory_item_id is required'}), 400

        result = create_or_update_overs_po_for_push(
            po_id,
            overage_int,
            inventory_item_id,
            line_item_name,
        )
        if result.get('success'):
            instructions = (
                'Sync Zoho POs to import the overs PO line, then push the bag again.'
            )
            if result.get('zoho_note'):
                instructions += ' ' + result['zoho_note']
            return jsonify({
                'success': True,
                'message': (
                    f'Overs PO "{result["overs_po_number"]}" '
                    f'{"updated" if result.get("action") == "updated" else "created"} in Zoho.'
                ),
                'overs_po_number': result['overs_po_number'],
                'zoho_po_id': result.get('zoho_po_id'),
                'action': result.get('action'),
                'total_overs_added': result.get('total_overs_added', 0),
                'instructions': instructions,
            })
        err = result.get('error', 'Failed to create or update overs PO')
        status = 404 if 'not found' in err.lower() else 400
        return jsonify({'success': False, 'error': err}), status
    except Exception as e:
        current_app.logger.error(f"overs_for_zoho_push: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


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

