"""
Receiving and Shipping API routes.

This module handles all receiving, shipping, and bag-related endpoints.
"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session, current_app
from datetime import datetime
import traceback
import os
import json
from werkzeug.utils import secure_filename
from app.utils.db_utils import db_read_only, db_transaction, ReceivingRepository, BagRepository
from app.utils.auth_utils import admin_required, role_required, employee_required
from app.services.tracking_service import refresh_shipment_row
from app.services.bag_matching_service import find_matching_bags_with_receive_names
from app.services.receiving_service import (
    get_receiving_with_details, 
    close_receiving,
    get_bag_with_packaged_count,
    extract_shipment_number,
    build_zoho_receive_notes
)
from app.services.zoho_service import zoho_api
from app.services.chart_service import generate_bag_chart_image
from config import Config

bp = Blueprint('api_receiving', __name__)


@bp.route('/api/receive/<int:receive_id>/details', methods=['GET'])
@role_required('shipping')
def get_receiving_details(receive_id):
    """Get receiving details with submission counts (similar to PO details modal)"""
    try:
        receiving = get_receiving_with_details(receive_id)
        if not receiving:
            return jsonify({'error': 'Receive not found'}), 404
        
        with db_read_only() as conn:
            receive_dict = receiving
            bags = receiving.get('bags', [])
            
            # Group by product -> box -> bag
            products = {}
            for bag in bags:
                inventory_item_id = bag.get('inventory_item_id')
                tablet_type_name = bag.get('tablet_type_name')
                box_number = bag.get('box_number')
                bag_number = bag.get('bag_number')
                bag_label_count = bag.get('bag_label_count', 0) or 0
                
                if not inventory_item_id:
                    continue
                    
                if inventory_item_id not in products:
                    products[inventory_item_id] = {
                        'tablet_type_name': tablet_type_name,
                        'inventory_item_id': inventory_item_id,
                        'boxes': {}
                    }
                
                if box_number not in products[inventory_item_id]['boxes']:
                    products[inventory_item_id]['boxes'][box_number] = {}
                
                # Get submission counts for this specific bag
                bag_id = bag.get('id')
                po_id = receive_dict.get('po_id')
                
                # Machine submissions
                machine_submissions = conn.execute('''
                    SELECT ws.tablets_pressed_into_cards, ws.loose_tablets, ws.packs_remaining,
                           COALESCE(pd.tablets_per_package, pd_fallback.tablets_per_package) as tablets_per_package_final,
                           ws.inventory_item_id
                    FROM warehouse_submissions ws
                    LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                    LEFT JOIN tablet_types tt_fallback ON ws.inventory_item_id = tt_fallback.inventory_item_id
                    LEFT JOIN product_details pd_fallback ON tt_fallback.id = pd_fallback.tablet_type_id
                    LEFT JOIN bags b_verify ON ws.bag_id = b_verify.id
                    LEFT JOIN small_boxes sb_verify ON b_verify.small_box_id = sb_verify.id
                    WHERE ws.submission_type = 'machine'
                    AND (
                        (ws.bag_id = ? AND ws.assigned_po_id = ? AND sb_verify.receiving_id = ?)
                        OR (
                            ws.bag_id IS NULL AND ws.inventory_item_id = ? AND ws.bag_number = ?
                            AND ws.assigned_po_id = ? AND (ws.box_number = ? OR ws.box_number IS NULL)
                        )
                    )
                ''', (bag_id, po_id, receive_id, inventory_item_id, bag_number, po_id, box_number)).fetchall()
                
                machine_total = 0
                for machine_sub in machine_submissions:
                    msub = dict(machine_sub)
                    tablets_per_package = msub.get('tablets_per_package_final') or 0
                    
                    if not tablets_per_package and msub.get('inventory_item_id'):
                        tpp_row = conn.execute('''
                            SELECT pd.tablets_per_package
                            FROM tablet_types tt
                            JOIN product_details pd ON tt.id = pd.tablet_type_id
                            WHERE tt.inventory_item_id = ?
                            LIMIT 1
                        ''', (msub['inventory_item_id'],)).fetchone()
                        if tpp_row:
                            tablets_per_package = dict(tpp_row).get('tablets_per_package', 0) or 0
                    
                    sub_total = (msub.get('tablets_pressed_into_cards') or
                                msub.get('loose_tablets') or
                                ((msub.get('packs_remaining', 0) or 0) * tablets_per_package) or
                                0)
                    machine_total += sub_total
                
                # Packaged submissions
                packaged_count = conn.execute('''
                    SELECT COALESCE(SUM(
                        (COALESCE(ws.displays_made, 0) * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
                        (COALESCE(ws.packs_remaining, 0) * COALESCE(pd.tablets_per_package, 0)) +
                        COALESCE(ws.loose_tablets, 0)
                    ), 0) as total_packaged
                    FROM warehouse_submissions ws
                    LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                    LEFT JOIN bags b_verify ON ws.bag_id = b_verify.id
                    LEFT JOIN small_boxes sb_verify ON b_verify.small_box_id = sb_verify.id
                    WHERE ws.submission_type = 'packaged'
                    AND (
                        (ws.bag_id = ? AND ws.assigned_po_id = ? AND sb_verify.receiving_id = ?)
                        OR (
                            ws.bag_id IS NULL AND ws.inventory_item_id = ? AND ws.bag_number = ?
                            AND ws.assigned_po_id = ? AND (ws.box_number = ? OR ws.box_number IS NULL)
                        )
                    )
                ''', (bag_id, po_id, receive_id, inventory_item_id, bag_number, po_id, box_number)).fetchone()
                
                # Bag count submissions
                bag_count = conn.execute('''
                    SELECT COALESCE(SUM(COALESCE(ws.loose_tablets, 0)), 0) as total_bag
                    FROM warehouse_submissions ws
                    LEFT JOIN bags b_verify ON ws.bag_id = b_verify.id
                    LEFT JOIN small_boxes sb_verify ON b_verify.small_box_id = sb_verify.id
                    WHERE ws.submission_type = 'bag'
                    AND (
                        (ws.bag_id = ? AND ws.assigned_po_id = ? AND sb_verify.receiving_id = ?)
                        OR (
                            ws.bag_id IS NULL AND ws.inventory_item_id = ? AND ws.bag_number = ?
                            AND ws.assigned_po_id = ? AND (ws.box_number = ? OR ws.box_number IS NULL)
                        )
                    )
                ''', (bag_id, po_id, receive_id, inventory_item_id, bag_number, po_id, box_number)).fetchone()
                
                products[inventory_item_id]['boxes'][box_number][bag_number] = {
                    'bag_id': bag_id,
                    'bag_number': bag_number,
                    'box_number': box_number,
                    'status': bag.get('status', 'Available'),
                    'received_count': bag_label_count,
                    'machine_count': machine_total,
                    'packaged_count': dict(packaged_count)['total_packaged'] if packaged_count else 0,
                    'bag_count': dict(bag_count)['total_bag'] if bag_count else 0,
                    'zoho_receive_pushed': bool(bag.get('zoho_receive_pushed', False)),
                    'zoho_receive_id': bag.get('zoho_receive_id')
                }
            
            # Convert nested dict to list format
            products_list = []
            for inventory_item_id, product_data in products.items():
                product_entry = {
                    'tablet_type_name': product_data['tablet_type_name'],
                    'inventory_item_id': inventory_item_id,
                    'boxes': []
                }
                for box_number, bags_in_box in sorted(product_data['boxes'].items()):
                    box_entry = {
                        'box_number': box_number,
                        'bags': []
                    }
                    for bag_number, bag_data in sorted(bags_in_box.items()):
                        box_entry['bags'].append({
                            'bag_number': bag_number,
                            **bag_data
                        })
                    product_entry['boxes'].append(box_entry)
                products_list.append(product_entry)
            
            return jsonify({
                'success': True,
                'receive': receive_dict,
                'products': products_list
            })
    except Exception as e:
        current_app.logger.error(f"Error getting receiving details: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/shipping')
@role_required('shipping')
def receiving_list():
    """Shipments Received page - record shipments that arrive"""
    try:
        with db_read_only() as conn:
            # Get all tablet types for the form dropdown
            tablet_types = conn.execute('''
                SELECT id, tablet_type_name 
                FROM tablet_types 
                ORDER BY tablet_type_name
            ''').fetchall()
            
            # Get all POs for managers/admin to assign
            purchase_orders = []
            if session.get('employee_role') in ['manager', 'admin']:
                purchase_orders = conn.execute('''
                    SELECT id, po_number, closed, internal_status, zoho_status
                    FROM purchase_orders
                    ORDER BY po_number DESC
                ''').fetchall()
            
            # Get all receiving records with their boxes and bags
            receiving_records = conn.execute('''
                SELECT r.*, 
                       COUNT(DISTINCT sb.id) as box_count,
                       COUNT(DISTINCT b.id) as total_bags,
                       po.po_number
                FROM receiving r
                LEFT JOIN small_boxes sb ON r.id = sb.receiving_id
                LEFT JOIN bags b ON sb.id = b.small_box_id
                LEFT JOIN purchase_orders po ON r.po_id = po.id
                GROUP BY r.id
                ORDER BY r.received_date DESC
            ''').fetchall()
            
            # Calculate shipment numbers for each PO
            po_shipment_counts = {}
            for rec in receiving_records:
                po_id = rec['po_id']
                if po_id and po_id not in po_shipment_counts:
                    po_shipments = conn.execute('''
                        SELECT id, received_date
                        FROM receiving
                        WHERE po_id = ?
                        ORDER BY received_date ASC, id ASC
                    ''', (po_id,)).fetchall()
                    po_shipment_counts[po_id] = {
                        shipment['id']: idx + 1 
                        for idx, shipment in enumerate(po_shipments)
                    }
            
            # For each receiving record, get its boxes and bags
            shipments = []
            for rec in receiving_records:
                rec_dict = dict(rec)
                if rec['po_id'] and rec['po_id'] in po_shipment_counts:
                    rec_dict['shipment_number'] = po_shipment_counts[rec['po_id']].get(rec['id'], 1)
                else:
                    rec_dict['shipment_number'] = None
                boxes = conn.execute('''
                    SELECT sb.*, COUNT(b.id) as bag_count
                    FROM small_boxes sb
                    LEFT JOIN bags b ON sb.id = b.small_box_id
                    WHERE sb.receiving_id = ?
                    GROUP BY sb.id
                    ORDER BY sb.box_number
                ''', (rec['id'],)).fetchall()
                
                boxes_with_bags = []
                for box in boxes:
                    bags = conn.execute('''
                        SELECT b.*, tt.tablet_type_name
                        FROM bags b
                        LEFT JOIN tablet_types tt ON b.tablet_type_id = tt.id
                        WHERE b.small_box_id = ?
                        ORDER BY b.bag_number
                    ''', (box['id'],)).fetchall()
                    boxes_with_bags.append({
                        'box': dict(box),
                        'bags': [dict(bag) for bag in bags]
                    })
                
                shipments.append({
                    'receiving': rec_dict,
                    'boxes': boxes_with_bags
                })
            
            return render_template('shipping_unified.html', 
                                 tablet_types=tablet_types,
                                 purchase_orders=purchase_orders,
                                 shipments=shipments,
                                 user_role=session.get('employee_role'))
    except Exception as e:
        error_details = traceback.format_exc()
        current_app.logger.error(f"Error in receiving_list: {str(e)}\n{error_details}")
        return render_template('error.html', 
                             error_message=f"Error loading shipping page: {str(e)}\n\nFull traceback:\n{error_details}"), 500


@bp.route('/api/shipments/<int:shipment_id>/refresh', methods=['POST'])
@role_required('dashboard')
def refresh_shipment_tracking(shipment_id: int):
    """Manually refresh a single shipment's tracking status."""
    try:
        with db_transaction() as conn:
            result = refresh_shipment_row(conn, shipment_id)
            if result.get('success'):
                return jsonify(result)
            return jsonify(result), 400
    except Exception as e:
        current_app.logger.error(f"Error refreshing shipment: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/shipment/<int:shipment_id>', methods=['GET'])
@role_required('dashboard')
def get_shipment_details(shipment_id: int):
    """Get shipment details by ID"""
    try:
        with db_read_only() as conn:
            row = conn.execute('''
                SELECT id, po_id, tracking_number, carrier, shipped_date, estimated_delivery, actual_delivery, notes
                FROM shipments WHERE id = ?
            ''', (shipment_id,)).fetchone()
            if not row:
                return jsonify({'success': False, 'error': 'Not found'}), 404
            return jsonify({'success': True, 'shipment': dict(row)})
    except Exception as e:
        current_app.logger.error(f"Error getting shipment: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/shipment/<int:shipment_id>', methods=['DELETE'])
@role_required('dashboard')
def delete_shipment(shipment_id: int):
    """Delete a shipment"""
    try:
        with db_transaction() as conn:
            conn.execute('DELETE FROM shipments WHERE id = ?', (shipment_id,))
            return jsonify({'success': True})
    except Exception as e:
        current_app.logger.error(f"Error deleting shipment: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/save_shipment', methods=['POST'])
@role_required('dashboard')
def save_shipment():
    """Save shipment information (supports multiple shipments per PO)"""
    try:
        data = request.get_json()
        
        if not data.get('po_id'):
            return jsonify({'success': False, 'error': 'po_id is required'}), 400
        
        try:
            po_id = int(data['po_id'])
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid po_id'}), 400
        
        with db_transaction() as conn:
            shipment_id = data.get('shipment_id')
            
            if shipment_id:
                try:
                    shipment_id = int(shipment_id)
                except (ValueError, TypeError):
                    return jsonify({'success': False, 'error': 'Invalid shipment_id'}), 400
                    
                conn.execute('''
                UPDATE shipments 
                SET tracking_number = ?, carrier = ?, shipped_date = ?,
                    estimated_delivery = ?, actual_delivery = ?, notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (data.get('tracking_number'), data.get('carrier'), data.get('shipped_date'),
                  data.get('estimated_delivery'), data.get('actual_delivery'), 
                      data.get('notes'), shipment_id))
            else:
                conn.execute('''
                INSERT INTO shipments (po_id, tracking_number, carrier, shipped_date,
                                     estimated_delivery, actual_delivery, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (po_id, data.get('tracking_number'), data.get('carrier'), 
                      data.get('shipped_date'), data.get('estimated_delivery'), 
                      data.get('actual_delivery'), data.get('notes')))
                conn.execute('UPDATE shipments SET carrier_code = LOWER(?) WHERE rowid = last_insert_rowid()', (data.get('carrier'),))
            
            # Auto-progress PO to "Shipped" status when tracking info is added
            if data.get('tracking_number'):
                current_status = conn.execute(
                    'SELECT internal_status FROM purchase_orders WHERE id = ?',
                    (po_id,)
                ).fetchone()
                
                if current_status and current_status['internal_status'] in ['Draft', 'Issued']:
                    conn.execute('''
                        UPDATE purchase_orders 
                        SET internal_status = 'Shipped', updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    ''', (po_id,))
                    current_app.logger.info(f"Auto-progressed PO {po_id} to Shipped (tracking added)")

            # Trigger immediate UPS refresh when applicable
            if data.get('tracking_number') and (data.get('carrier', '').lower() in ('ups','fedex','fed ex')):
                sh = conn.execute('''
                    SELECT id FROM shipments WHERE po_id = ? AND tracking_number = ?
                    ORDER BY updated_at DESC LIMIT 1
                ''', (po_id, data.get('tracking_number'))).fetchone()
                if sh:
                    try:
                        result = refresh_shipment_row(conn, sh['id'])
                        current_app.logger.info(f"UPS refresh result: {result}")
                    except Exception as exc:
                        current_app.logger.error(f"UPS refresh error: {exc}")

            return jsonify({'success': True, 'message': 'Shipment saved; tracking refreshed if supported'})
    except Exception as e:
        current_app.logger.error(f"Error saving shipment: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/receiving')
@admin_required  
def receiving_management():
    """Receiving management page"""
    try:
        with db_read_only() as conn:
            try:
                test_query = conn.execute('SELECT COUNT(*) as count FROM receiving').fetchone()
                receiving_count = test_query['count'] if test_query else 0
            except Exception as e:
                return f"""
                <h2>Database Error</h2>
                <p>Cannot access receiving table: {str(e)}</p>
                <p><a href="/debug/server-info">Check Database</a></p>
                """
            
            # Get pending shipments (delivered but not yet received)
            pending_shipments = conn.execute('''
                SELECT s.*, po.po_number
                FROM shipments s
                JOIN purchase_orders po ON s.po_id = po.id
                LEFT JOIN receiving r ON s.id = r.shipment_id
                WHERE s.tracking_status = 'Delivered' AND r.id IS NULL
                ORDER BY s.delivered_at DESC, s.created_at DESC
            ''').fetchall()
            
            # Get recent receiving history
            recent_receiving = conn.execute('''
                SELECT r.*, po.po_number,
                       COUNT(sb.id) as total_boxes,
                       SUM(sb.total_bags) as total_bags
                FROM receiving r
                JOIN purchase_orders po ON r.po_id = po.id
                LEFT JOIN small_boxes sb ON r.id = sb.receiving_id
                GROUP BY r.id
                ORDER BY r.received_date DESC
                LIMIT 20
            ''').fetchall()
            
            return render_template('receiving_management.html', 
                                 pending_shipments=pending_shipments,
                                 recent_receiving=recent_receiving)
    except Exception as e:
        current_app.logger.error(f"Error in receiving_management: {str(e)}")
        return f"""
        <h2>Receiving Page Error</h2>
        <p>Template error: {str(e)}</p>
        <p><a href="/receiving/debug">View debug info</a></p>
        <p><a href="/debug/server-info">Check Server Info</a></p>
        <p><a href="/admin">Back to admin</a></p>
        """


@bp.route('/receiving/<int:receiving_id>')
@admin_required
def receiving_details_view(receiving_id):
    """View detailed information about a specific receiving record"""
    try:
        receiving = get_receiving_with_details(receiving_id)
        if not receiving:
            flash('Receiving record not found', 'error')
            return redirect(url_for('api_receiving.receiving_management'))
        
        boxes = receiving.get('small_boxes', [])
        return render_template('receiving_details.html', 
                             receiving=receiving,
                             boxes=boxes)
    except Exception as e:
        current_app.logger.error(f"Error loading receiving details: {str(e)}")
        flash(f'Error loading receiving details: {str(e)}', 'error')
        return redirect(url_for('api_receiving.receiving_management'))


@bp.route('/api/receiving/<int:receiving_id>', methods=['DELETE'])
@role_required('shipping')
def delete_receiving(receiving_id):
    """Delete a receiving record with verification"""
    try:
        user_role = session.get('employee_role')
        if user_role not in ['manager', 'admin']:
            return jsonify({'success': False, 'error': 'Only managers and admins can delete shipments'}), 403
        
        with db_transaction() as conn:
            receiving = conn.execute('''
                SELECT r.id, r.po_id, po.po_number, r.received_date, r.received_by
                FROM receiving r
                LEFT JOIN purchase_orders po ON r.po_id = po.id
                WHERE r.id = ?
            ''', (receiving_id,)).fetchone()
            
            if not receiving:
                return jsonify({'success': False, 'error': 'Receiving record not found'}), 404
            
            # Delete in correct order due to foreign key constraints
            conn.execute('DELETE FROM bags WHERE small_box_id IN (SELECT id FROM small_boxes WHERE receiving_id = ?)', (receiving_id,))
            conn.execute('DELETE FROM small_boxes WHERE receiving_id = ?', (receiving_id,))
            conn.execute('DELETE FROM receiving WHERE id = ?', (receiving_id,))
            
            po_info = receiving['po_number'] if receiving['po_number'] else 'No PO'
            return jsonify({
                'success': True,
                'message': f'Successfully deleted shipment (PO: {po_info})'
            })
    except Exception as e:
        current_app.logger.error(f"Error deleting receiving: {str(e)}")
        return jsonify({'success': False, 'error': f'Failed to delete receiving record: {str(e)}'}), 500


@bp.route('/api/receiving/<int:receiving_id>/close', methods=['POST'])
@role_required('dashboard')
def close_receiving_endpoint(receiving_id):
    """Close a receiving record when all bags are physically emptied"""
    try:
        user_role = session.get('employee_role')
        is_admin = session.get('admin_authenticated')
        if user_role not in ['manager', 'admin'] and not is_admin:
            return jsonify({'success': False, 'error': 'Only managers and admins can close receives'}), 403
        
        with db_transaction() as conn:
            receiving = ReceivingRepository.get_by_id(conn, receiving_id)
            if not receiving:
                return jsonify({'success': False, 'error': 'Receiving record not found'}), 404
            
            # Toggle closed status
            current_closed = receiving.get('closed', False)
            new_closed = not current_closed
            
            conn.execute('''
                UPDATE receiving 
                SET closed = ?
                WHERE id = ?
            ''', (new_closed, receiving_id))
            
            # Also close all bags in this receive when closing
            if new_closed:
                conn.execute('''
                    UPDATE bags
                    SET status = 'Closed'
                    WHERE small_box_id IN (
                        SELECT id FROM small_boxes WHERE receiving_id = ?
                    )
                ''', (receiving_id,))
            else:
                # Reopen bags when reopening receive
                conn.execute('''
                    UPDATE bags
                    SET status = 'Available'
                    WHERE small_box_id IN (
                        SELECT id FROM small_boxes WHERE receiving_id = ?
                    )
                ''', (receiving_id,))
            
            po_info = receiving.get('po_number', 'Unassigned') if receiving else 'Unassigned'
            closed_status = new_closed
        
        action = 'closed' if closed_status else 'reopened'
        return jsonify({
            'success': True,
            'closed': closed_status,
            'message': f'Successfully {action} receive (PO: {po_info})'
        })
    except Exception as e:
        current_app.logger.error(f"Error closing receiving: {str(e)}")
        return jsonify({'success': False, 'error': f'Failed to close receiving: {str(e)}'}), 500


@bp.route('/api/bag/<int:bag_id>/close', methods=['POST'])
@role_required('dashboard')
def close_bag(bag_id):
    """Close a specific bag when it's physically emptied"""
    try:
        user_role = session.get('employee_role')
        is_admin = session.get('admin_authenticated')
        if user_role not in ['manager', 'admin'] and not is_admin:
            return jsonify({'success': False, 'error': 'Only managers and admins can close bags'}), 403
        
        with db_transaction() as conn:
            bag_row = conn.execute('''
                SELECT b.id, COALESCE(b.status, 'Available') as status, b.bag_number, sb.box_number, tt.tablet_type_name
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN tablet_types tt ON b.tablet_type_id = tt.id
                WHERE b.id = ?
            ''', (bag_id,)).fetchone()
            
            if not bag_row:
                return jsonify({'success': False, 'error': 'Bag not found'}), 404
            
            bag = dict(bag_row)
            current_status = bag.get('status', 'Available')
            new_status = 'Closed' if current_status != 'Closed' else 'Available'
            
            conn.execute('''
                UPDATE bags 
                SET status = ?
                WHERE id = ?
            ''', (new_status, bag_id))
            
            action = 'closed' if new_status == 'Closed' else 'reopened'
            bag_info = f"{bag.get('tablet_type_name', 'Unknown')} - Box {bag.get('box_number', 'N/A')}, Bag {bag.get('bag_number', 'N/A')}"
            return jsonify({
                'success': True,
                'status': new_status,
                'message': f'Successfully {action} bag: {bag_info}'
            })
    except Exception as e:
        current_app.logger.error(f"Error closing bag {bag_id}: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Failed to close bag: {str(e)}'}), 500


@bp.route('/api/bag/<int:bag_id>/push_to_zoho', methods=['POST'])
@role_required('dashboard')
def push_bag_to_zoho(bag_id):
    """
    Push a closed bag to Zoho as a purchase receive.
    
    Creates a purchase receive in Zoho Inventory with:
    - Line item quantity = packaged_count
    - Notes with shipment/box/bag info and counts
    - Chart image attachment showing received vs packaged
    
    Request JSON (optional):
        custom_notes: Additional notes to append
    """
    try:
        user_role = session.get('employee_role')
        is_admin = session.get('admin_authenticated')
        if user_role not in ['manager', 'admin'] and not is_admin:
            return jsonify({'success': False, 'error': 'Only managers and admins can push to Zoho'}), 403
        
        # Get optional custom notes from request
        data = request.get_json() or {}
        custom_notes = data.get('custom_notes', '').strip() if data.get('custom_notes') else None
        
        # Get bag with all required details
        bag = get_bag_with_packaged_count(bag_id)
        if not bag:
            return jsonify({'success': False, 'error': 'Bag not found'}), 404
        
        # Verify bag is closed
        if bag.get('status') != 'Closed':
            return jsonify({
                'success': False, 
                'error': 'Bag must be closed before pushing to Zoho. Please close the bag first.'
            }), 400
        
        # Check if already pushed
        if bag.get('zoho_receive_pushed'):
            return jsonify({
                'success': False, 
                'error': 'This bag has already been pushed to Zoho.',
                'zoho_receive_id': bag.get('zoho_receive_id')
            }), 400
        
        # Validate required fields
        zoho_po_id = bag.get('zoho_po_id')
        if not zoho_po_id:
            return jsonify({
                'success': False, 
                'error': 'Cannot push to Zoho: PO does not have a Zoho PO ID. Please sync POs from Zoho first.'
            }), 400
        
        # Get zoho_line_item_id for this bag's tablet type in this PO
        # This is the unique ID for the line item in the purchase order
        zoho_line_item_id = bag.get('zoho_line_item_id')
        if not zoho_line_item_id:
            return jsonify({
                'success': False, 
                'error': 'Cannot push to Zoho: PO line item does not have a Zoho line item ID. Please sync POs from Zoho first (click Sync POs button on Dashboard).'
            }), 400
        
        # Get values for notes
        receive_name = bag.get('receive_name', '')
        current_app.logger.info(f"📝 Building notes - receive_name from DB: '{receive_name}'")
        shipment_number = extract_shipment_number(receive_name)
        current_app.logger.info(f"📝 Extracted shipment_number: '{shipment_number}'")
        box_number = bag.get('box_number', 1)
        bag_number = bag.get('bag_number', 1)
        bag_label_count = bag.get('bag_label_count', 0) or 0
        packaged_count = bag.get('packaged_count', 0) or 0
        
        # Build notes
        notes = build_zoho_receive_notes(
            shipment_number=shipment_number,
            box_number=box_number,
            bag_number=bag_number,
            bag_label_count=bag_label_count,
            packaged_count=packaged_count,
            custom_notes=custom_notes
        )
        
        # Generate chart image with context information
        chart_image = generate_bag_chart_image(
            bag_label_count=bag_label_count,
            packaged_count=packaged_count,
            tablet_type_name=bag.get('tablet_type_name'),
            box_number=bag.get('box_number'),
            bag_number=bag.get('bag_number'),
            receive_name=receive_name
        )
        chart_filename = f"bag_{bag_id}_stats.png" if chart_image else None
        
        # Build line items for Zoho receive
        # Use line_item_id from the PO (this is required by Zoho API for purchase receives)
        line_items = [{
            'line_item_id': zoho_line_item_id,
            'quantity': packaged_count
        }]
        
        # Create purchase receive in Zoho
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Log the request details for debugging
        current_app.logger.info(f"Pushing bag {bag_id} to Zoho:")
        current_app.logger.info(f"  - Zoho PO ID: {zoho_po_id}")
        current_app.logger.info(f"  - Zoho Line Item ID: {zoho_line_item_id}")
        current_app.logger.info(f"  - Line items: {line_items}")
        current_app.logger.info(f"  - Date: {today}")
        current_app.logger.info(f"  - Has chart image: {bool(chart_image)}")
        
        result = zoho_api.create_purchase_receive(
            purchaseorder_id=zoho_po_id,
            line_items=line_items,
            date=today,
            notes=notes,
            image_bytes=chart_image if chart_image else None,
            image_filename=chart_filename
        )
        
        if not result:
            current_app.logger.error("Zoho API returned None - likely authentication or network error")
            return jsonify({
                'success': False,
                'error': 'Failed to create purchase receive in Zoho. Please check API credentials and try again. Check Flask logs for details.'
            }), 500
        
        # Check for errors in Zoho response
        if result.get('code') and result.get('code') != 0:
            error_msg = result.get('message', 'Unknown Zoho API error')
            current_app.logger.error(f"Zoho API error: {error_msg}")
            return jsonify({
                'success': False,
                'error': f'Zoho API error: {error_msg}'
            }), 500
        
        # Get the created receive ID - try multiple possible field names
        zoho_receive_id = None
        if result.get('purchasereceive'):
            zoho_receive_id = (
                result['purchasereceive'].get('purchasereceive_id') or
                result['purchasereceive'].get('purchase_receive_id') or
                result['purchasereceive'].get('id') or
                result['purchasereceive'].get('receive_id')
            )
            current_app.logger.info(f"Extracted zoho_receive_id from purchasereceive: {zoho_receive_id}")
        else:
            # Try direct fields in case response structure is different
            zoho_receive_id = (
                result.get('purchasereceive_id') or
                result.get('purchase_receive_id') or
                result.get('id') or
                result.get('receive_id')
            )
            current_app.logger.info(f"Extracted zoho_receive_id from root: {zoho_receive_id}")
        
        # Log the full response if receive ID is still None (for debugging)
        if not zoho_receive_id:
            current_app.logger.warning(f"⚠️ Could not extract zoho_receive_id. Full response: {json.dumps(result, indent=2, default=str)[:1000]}")
        
        # Update bag to mark as pushed
        with db_transaction() as conn:
            conn.execute('''
                UPDATE bags 
                SET zoho_receive_pushed = 1, zoho_receive_id = ?
                WHERE id = ?
            ''', (zoho_receive_id, bag_id))
        
        bag_info = f"{bag.get('tablet_type_name', 'Unknown')} - Box {box_number}, Bag {bag_number}"
        current_app.logger.info(f"Successfully pushed bag {bag_id} to Zoho receive {zoho_receive_id}")
        
        return jsonify({
            'success': True,
            'message': f'Successfully pushed {bag_info} to Zoho',
            'zoho_receive_id': zoho_receive_id
        })
        
    except Exception as e:
        current_app.logger.error(f"Error pushing bag {bag_id} to Zoho: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Failed to push to Zoho: {str(e)}'}), 500


@bp.route('/api/process_receiving', methods=['POST'])
@admin_required
def process_receiving():
    """Process a new shipment receiving with photos and box/bag tracking"""
    try:
        with db_transaction() as conn:
            shipment_id = request.form.get('shipment_id')
            if not shipment_id:
                return jsonify({'error': 'Shipment ID required'}), 400
            
            try:
                total_small_boxes = int(request.form.get('total_small_boxes', 0))
            except (ValueError, TypeError):
                return jsonify({'error': 'Invalid total_small_boxes value'}), 400
            
            received_by = request.form.get('received_by')
            notes = request.form.get('notes', '')
            
            # Get shipment and PO info
            shipment = conn.execute('''
                SELECT s.*, po.po_number, po.id as po_id
                FROM shipments s
                JOIN purchase_orders po ON s.po_id = po.id
                WHERE s.id = ?
            ''', (shipment_id,)).fetchone()
            
            if not shipment:
                return jsonify({'error': 'Shipment not found'}), 404
            
            # Handle photo upload with validation
            delivery_photo = request.files.get('delivery_photo')
            photo_path = None
            zoho_photo_id = None
            
            ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif'}
            MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
            
            def allowed_file(filename):
                return '.' in filename and \
                       filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
            
            if delivery_photo and delivery_photo.filename:
                if not allowed_file(delivery_photo.filename):
                    return jsonify({'error': 'Invalid file type. Only JPG, JPEG, PNG, and GIF are allowed.'}), 400
                
                delivery_photo.seek(0, os.SEEK_END)
                file_size = delivery_photo.tell()
                delivery_photo.seek(0)
                if file_size > MAX_FILE_SIZE:
                    return jsonify({'error': f'File too large. Maximum size is {MAX_FILE_SIZE / (1024*1024):.0f}MB'}), 400
                
                try:
                    shipment_id_int = int(shipment_id)
                except (ValueError, TypeError):
                    return jsonify({'error': 'Invalid shipment_id'}), 400
                
                safe_filename = secure_filename(delivery_photo.filename)
                original_ext = safe_filename.rsplit('.', 1)[1].lower() if '.' in safe_filename else 'jpg'
                
                upload_dir = os.path.join(current_app.root_path, '..', 'static', 'uploads', 'receiving')
                upload_dir = os.path.abspath(upload_dir)
                
                allowed_base = os.path.abspath(os.path.join(current_app.root_path, '..', 'static', 'uploads'))
                if not upload_dir.startswith(allowed_base):
                    return jsonify({'error': 'Invalid upload path'}), 400
                
                os.makedirs(upload_dir, exist_ok=True)
                
                filename = f"shipment_{shipment_id_int}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{original_ext}"
                photo_path = os.path.join(upload_dir, filename)
                delivery_photo.save(photo_path)
            
            # Calculate receive number for this PO
            receive_number_result = conn.execute('''
                SELECT COUNT(*) + 1 as receive_number
                FROM receiving
                WHERE po_id = ?
            ''', (shipment['po_id'],)).fetchone()
            
            receive_number = receive_number_result['receive_number'] if receive_number_result else 1
            receive_name = f"{shipment['po_number']}-{receive_number}"
            
            # Create receiving record
            receiving_cursor = conn.execute('''
                INSERT INTO receiving (po_id, shipment_id, total_small_boxes, received_by, notes, delivery_photo_path, delivery_photo_zoho_id, receive_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (shipment['po_id'], shipment_id, total_small_boxes, received_by, notes, photo_path, zoho_photo_id, receive_name))
            
            receiving_id = receiving_cursor.lastrowid
            
            # Process box details with sequential bag numbering
            total_bags = 0
            all_bag_data = {}
            
            for key in request.form.keys():
                if key.startswith('bag_') and key.endswith('_pill_count'):
                    try:
                        key_parts = key.split('_')
                        if len(key_parts) < 2:
                            continue
                        bag_num = int(key_parts[1])
                        if bag_num not in all_bag_data:
                            all_bag_data[bag_num] = {}
                        
                        try:
                            all_bag_data[bag_num]['pill_count'] = int(request.form[key])
                        except (ValueError, TypeError):
                            all_bag_data[bag_num]['pill_count'] = 0
                        
                        try:
                            all_bag_data[bag_num]['box'] = int(request.form.get(f'bag_{bag_num}_box', 0))
                        except (ValueError, TypeError):
                            all_bag_data[bag_num]['box'] = 0
                        
                        all_bag_data[bag_num]['notes'] = request.form.get(f'bag_{bag_num}_notes', '')
                    except (ValueError, TypeError, IndexError):
                        continue
            
            # Process boxes and their bags
            for box_num in range(1, total_small_boxes + 1):
                try:
                    bags_in_box = int(request.form.get(f'box_{box_num}_bags', 0))
                except (ValueError, TypeError):
                    bags_in_box = 0
                
                box_notes = request.form.get(f'box_{box_num}_notes', '')
                
                box_cursor = conn.execute('''
                    INSERT INTO small_boxes (receiving_id, box_number, total_bags, notes)
                    VALUES (?, ?, ?, ?)
                ''', (receiving_id, box_num, bags_in_box, box_notes))
                
                small_box_id = box_cursor.lastrowid
                
                for bag_data_key, bag_data in all_bag_data.items():
                    if bag_data['box'] == box_num:
                        conn.execute('''
                            INSERT INTO bags (small_box_id, bag_number, pill_count, status)
                            VALUES (?, ?, ?, 'Available')
                        ''', (small_box_id, bag_data_key, bag_data['pill_count']))
                        total_bags += 1
            
            # Update shipment status
            conn.execute('''
                UPDATE shipments SET actual_delivery = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (shipment_id,))
            
            return jsonify({
                'success': True,
                'message': f'Successfully received shipment for PO {shipment["po_number"]}. Processed {total_small_boxes} boxes with {total_bags} total bags.',
                'receiving_id': receiving_id
            })
    except Exception as e:
        current_app.logger.error(f"Error processing receiving: {str(e)}")
        return jsonify({'error': f'Failed to process receiving: {str(e)}'}), 500


@bp.route('/api/save_receives', methods=['POST'])
@role_required('shipping')
def save_receives():
    """Save received shipment data (boxes and bags)"""
    try:
        data = request.get_json()
        boxes_data = data.get('boxes', [])
        po_id = data.get('po_id')
        
        if not boxes_data:
            return jsonify({'success': False, 'error': 'No boxes data provided'}), 400
        
        user_role = session.get('employee_role')
        if po_id and user_role not in ['manager', 'admin']:
            return jsonify({'success': False, 'error': 'Only managers and admins can assign POs'}), 403
        
        with db_transaction() as conn:
            # Ensure tablet_type_id column exists
            c = conn.cursor()
            c.execute('PRAGMA table_info(bags)')
            existing_bags_cols = [row[1] for row in c.fetchall()]
            if 'tablet_type_id' not in existing_bags_cols:
                try:
                    conn.execute('ALTER TABLE bags ADD COLUMN tablet_type_id INTEGER')
                    conn.commit()
                except Exception as e:
                    if conn:
                        try:
                            conn.rollback()
                        except:
                            pass
                    current_app.logger.warning(f"Could not add tablet_type_id column: {e}")
            
            # Get current user name
            received_by = 'Unknown'
            if session.get('employee_id'):
                employee = conn.execute('SELECT full_name FROM employees WHERE id = ?', (session.get('employee_id'),)).fetchone()
                if employee:
                    received_by = employee['full_name']
            elif session.get('admin_authenticated'):
                received_by = 'Admin'
            
            # Create receiving record
            receiving_cursor = conn.execute('''
                INSERT INTO receiving (po_id, received_by, received_date, total_small_boxes, notes)
                VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?)
            ''', (po_id if po_id else None, received_by, len(boxes_data), f'Recorded {len(boxes_data)} box(es)'))
            
            receiving_id = receiving_cursor.lastrowid
            total_bags = 0
            
            # Process each box
            for box_data in boxes_data:
                box_number = box_data.get('box_number')
                bags = box_data.get('bags', [])
                
                if not bags:
                    continue
                
                box_cursor = conn.execute('''
                    INSERT INTO small_boxes (receiving_id, box_number, total_bags)
                    VALUES (?, ?, ?)
                ''', (receiving_id, box_number, len(bags)))
                
                small_box_id = box_cursor.lastrowid
                
                for bag in bags:
                    tablet_type_id = bag.get('tablet_type_id')
                    bag_count = bag.get('bag_count', 0)
                    bag_number = bag.get('bag_number')
                    
                    if not tablet_type_id or not bag_number:
                        continue
                    
                    conn.execute('''
                        INSERT INTO bags (small_box_id, bag_number, bag_label_count, tablet_type_id, status)
                        VALUES (?, ?, ?, ?, 'Available')
                    ''', (small_box_id, bag_number, bag_count, tablet_type_id))
                    total_bags += 1
            
            conn.execute('''
                UPDATE receiving SET total_small_boxes = ?
                WHERE id = ?
            ''', (len(boxes_data), receiving_id))
            
            return jsonify({
                'success': True,
                'message': f'Successfully recorded {len(boxes_data)} box(es) with {total_bags} bag(s)',
                'receiving_id': receiving_id
            })
    except Exception as e:
        current_app.logger.error(f"Error saving receives: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/receiving/<int:receiving_id>/assign_po', methods=['POST'])
@role_required('shipping')
def assign_po_to_receiving(receiving_id):
    """Update PO assignment for a receiving record (managers and admins only)"""
    try:
        user_role = session.get('employee_role')
        if user_role not in ['manager', 'admin']:
            return jsonify({'success': False, 'error': 'Only managers and admins can assign POs'}), 403
        
        data = request.get_json()
        po_id = data.get('po_id')
        
        with db_transaction() as conn:
            receiving = conn.execute('SELECT id FROM receiving WHERE id = ?', (receiving_id,)).fetchone()
            if not receiving:
                return jsonify({'success': False, 'error': 'Receiving record not found'}), 404
            
            conn.execute('''
                UPDATE receiving SET po_id = ?
                WHERE id = ?
            ''', (po_id if po_id else None, receiving_id))
            
            po_number = None
            if po_id:
                po = conn.execute('SELECT po_number FROM purchase_orders WHERE id = ?', (po_id,)).fetchone()
                if po:
                    po_number = po['po_number']
            
            return jsonify({
                'success': True,
                'message': f'PO assignment updated successfully',
                'po_number': po_number
            })
    except Exception as e:
        current_app.logger.error(f"Error assigning PO to receiving: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/available_boxes_bags/<int:po_id>')
@employee_required
def get_available_boxes_bags_for_po(po_id):
    """Get available boxes and bags for a PO (for warehouse form dropdowns)"""
    try:
        with db_read_only() as conn:
            # Get all receiving records for this PO with available bags
            receiving_data = conn.execute('''
                SELECT r.id as receiving_id, sb.box_number, b.bag_number, b.id as bag_id, b.bag_label_count
                FROM receiving r
                JOIN small_boxes sb ON r.id = sb.receiving_id
                JOIN bags b ON sb.id = b.small_box_id
                WHERE r.po_id = ? AND b.status = 'Available'
                ORDER BY sb.box_number, b.bag_number
            ''', (po_id,)).fetchall()
            
            # Structure data for frontend
            boxes = {}
            for row in receiving_data:
                box_num = row['box_number']
                if box_num not in boxes:
                    boxes[box_num] = []
                boxes[box_num].append({
                    'bag_number': row['bag_number'],
                    'bag_id': row['bag_id'],
                    'bag_label_count': row['bag_label_count']
                })
            
            return jsonify({'boxes': boxes})
    except Exception as e:
        current_app.logger.error(f"Error getting available boxes/bags: {str(e)}")
        return jsonify({'error': str(e)}), 500


@bp.route('/api/create_sample_receiving_data', methods=['POST'])
@admin_required  
def create_sample_receiving_data():
    """Create sample PO and shipment data for testing receiving workflow"""
    try:
        import random
        
        with db_transaction() as conn:
            timestamp = datetime.now().strftime('%m%d-%H%M')
            po_number = f'TEST-{timestamp}'
            tracking_suffix = random.randint(100000, 999999)
            tracking_number = f'1Z999AA{tracking_suffix}'
            
            po_cursor = conn.execute('''
                INSERT INTO purchase_orders (po_number, tablet_type, zoho_status, ordered_quantity, internal_status)
                VALUES (?, ?, ?, ?, ?)
            ''', (po_number, 'Test Tablets', 'confirmed', 1000, 'Active'))
            
            po_id = po_cursor.lastrowid
            
            shipment_cursor = conn.execute('''
                INSERT INTO shipments (po_id, tracking_number, carrier, tracking_status, delivered_at, created_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ''', (po_id, tracking_number, 'UPS', 'Delivered'))
            
            shipment_id = shipment_cursor.lastrowid
            
            return jsonify({
                'success': True,
                'message': f'Created sample PO {po_number} with delivered UPS shipment. Ready for receiving!',
                'po_id': po_id,
                'shipment_id': shipment_id
            })
    except Exception as e:
        current_app.logger.error(f"Error creating sample receiving data: {str(e)}")
        return jsonify({'error': f'Failed to create sample data: {str(e)}'}), 500


@bp.route('/api/po/<int:po_id>/receives', methods=['GET'])
@role_required('dashboard')
def get_po_receives(po_id):
    """Get all receives (shipments received) for a specific PO"""
    try:
        with db_read_only() as conn:
            po = conn.execute('''
                SELECT po_number
                FROM purchase_orders
                WHERE id = ?
            ''', (po_id,)).fetchone()
            
            if not po:
                return jsonify({'error': 'PO not found'}), 404
            
            receiving_records = conn.execute('''
                SELECT r.*, 
                       COUNT(DISTINCT sb.id) as box_count,
                       COUNT(DISTINCT b.id) as total_bags
                FROM receiving r
                LEFT JOIN small_boxes sb ON r.id = sb.receiving_id
                LEFT JOIN bags b ON sb.id = b.small_box_id
                WHERE r.po_id = ?
                GROUP BY r.id
                ORDER BY r.received_date ASC, r.id ASC
            ''', (po_id,)).fetchall()
            
            po_shipment_counts = {}
            po_shipments = conn.execute('''
                SELECT id, received_date
                FROM receiving
                WHERE po_id = ?
                ORDER BY received_date ASC, id ASC
            ''', (po_id,)).fetchall()
            po_shipment_counts = {
                dict(shipment)['id']: idx + 1 
                for idx, shipment in enumerate(po_shipments)
            }
            
            receives = []
            for rec in receiving_records:
                rec_dict = dict(rec)
                rec_id = rec_dict['id']
                if rec_id in po_shipment_counts:
                    rec_dict['shipment_number'] = po_shipment_counts[rec_id]
                else:
                    rec_dict['shipment_number'] = None
                boxes = conn.execute('''
                    SELECT sb.*, COUNT(b.id) as bag_count
                    FROM small_boxes sb
                    LEFT JOIN bags b ON sb.id = b.small_box_id
                    WHERE sb.receiving_id = ?
                    GROUP BY sb.id
                    ORDER BY sb.box_number
                ''', (rec_id,)).fetchall()
                
                boxes_with_bags = []
                for box in boxes:
                    box_dict = dict(box)
                    bags = conn.execute('''
                        SELECT b.*, tt.tablet_type_name, tt.inventory_item_id
                        FROM bags b
                        LEFT JOIN tablet_types tt ON b.tablet_type_id = tt.id
                        WHERE b.small_box_id = ?
                        ORDER BY b.bag_number
                    ''', (box_dict['id'],)).fetchall()
                    boxes_with_bags.append({
                        'box': box_dict,
                        'bags': [dict(bag) for bag in bags]
                    })
                
                receives.append({
                    'receiving': rec_dict,
                    'boxes': boxes_with_bags
                })
            
            return jsonify({
                'success': True,
                'po': dict(po),
                'receives': receives
            })
    except Exception as e:
        current_app.logger.error(f"Error getting PO receives: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/receives/list', methods=['GET'])
@role_required('dashboard')
def get_receives_list():
    """Get list of all receives for reporting"""
    try:
        with db_read_only() as conn:
            receives = conn.execute('''
                SELECT r.id, 
                       r.received_date,
                       po.po_number,
                       r.po_id,
                       r.receive_name
                FROM receiving r
                LEFT JOIN purchase_orders po ON r.po_id = po.id
                ORDER BY COALESCE(r.received_date, r.created_at) DESC, r.id DESC
                LIMIT 100
            ''').fetchall()
            
            receives_list = []
            for r in receives:
                receive_dict = dict(r)
                if not receive_dict.get('receive_name') and receive_dict.get('po_number'):
                    receive_number_result = conn.execute('''
                        SELECT COUNT(*) + 1 as receive_number
                        FROM receiving r2
                        WHERE r2.po_id = r.po_id
                        AND (r2.received_date < r.received_date 
                             OR (r2.received_date = r.received_date AND r2.id < r.id))
                    ''', (receive_dict['po_id'],)).fetchone()
                    receive_number = receive_number_result['receive_number'] if receive_number_result else 1
                    receive_dict['receive_name'] = f"{receive_dict['po_number']}-{receive_number}"
                receives_list.append(receive_dict)
            
            return jsonify({
                'success': True,
                'receives': receives_list
            })
    except Exception as e:
        current_app.logger.error(f"Error getting receives list: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/submission/<int:submission_id>/possible-receives', methods=['GET'])
@role_required('dashboard')
def get_possible_receives_for_submission(submission_id):
    """Get all possible receives that match a submission's flavor, box, bag"""
    try:
        with db_read_only() as conn:
            submission = conn.execute('''
                SELECT ws.*, tt.id as tablet_type_id, tt.tablet_type_name
                FROM warehouse_submissions ws
                LEFT JOIN tablet_types tt ON ws.inventory_item_id = tt.inventory_item_id
                WHERE ws.id = ?
            ''', (submission_id,)).fetchone()
            
            if not submission:
                return jsonify({'success': False, 'error': 'Submission not found'}), 404
            
            submission_dict = dict(submission)
            submission_type = submission_dict.get('submission_type', 'packaged')
            exclude_closed_bags = (submission_type != 'packaged')
            
            # Ensure tablet_type_id is populated - try fallback lookup if missing
            # This handles cases where LEFT JOIN didn't match but inventory_item_id exists
            tablet_type_id = submission_dict.get('tablet_type_id')
            if not tablet_type_id and submission_dict.get('inventory_item_id'):
                tt_row = conn.execute('''
                    SELECT id FROM tablet_types WHERE inventory_item_id = ?
                ''', (submission_dict.get('inventory_item_id'),)).fetchone()
                if tt_row:
                    tablet_type_id = tt_row['id']
                    submission_dict['tablet_type_id'] = tablet_type_id
            
            # Additional fallback: try to get tablet_type_id from product_name via product_details
            # This handles cases where inventory_item_id lookup failed (data inconsistency)
            if not tablet_type_id and submission_dict.get('product_name'):
                product_row = conn.execute('''
                    SELECT tablet_type_id FROM product_details WHERE product_name = ?
                ''', (submission_dict.get('product_name'),)).fetchone()
                if product_row:
                    tablet_type_id = product_row['tablet_type_id']
                    submission_dict['tablet_type_id'] = tablet_type_id
            
            # Use bag matching service
            matching_bags = find_matching_bags_with_receive_names(
                conn,
                submission_dict,
                exclude_closed_bags
            )
            
            if not submission_dict.get('bag_number'):
                # Fallback: try to find receives by tablet type
                if tablet_type_id:
                    if exclude_closed_bags:
                        fallback_receives = conn.execute('''
                            SELECT DISTINCT b.id as bag_id, 
                                   sb.box_number, 
                                   b.bag_number, 
                                   b.bag_label_count,
                                   r.id as receive_id,
                                   r.received_date,
                                   r.receive_name as stored_receive_name,
                                   po.po_number,
                                   po.id as po_id,
                                   tt.tablet_type_name
                            FROM bags b
                            JOIN small_boxes sb ON b.small_box_id = sb.id
                            JOIN receiving r ON sb.receiving_id = r.id
                            JOIN purchase_orders po ON r.po_id = po.id
                            JOIN tablet_types tt ON b.tablet_type_id = tt.id
                            WHERE tt.id = ?
                            AND COALESCE(b.status, 'Available') != 'Closed'
                            AND (r.closed IS NULL OR r.closed = FALSE)
                            ORDER BY r.received_date DESC
                            LIMIT 20
                        ''', (tablet_type_id,)).fetchall()
                    else:
                        fallback_receives = conn.execute('''
                            SELECT DISTINCT b.id as bag_id, 
                                   sb.box_number, 
                                   b.bag_number, 
                                   b.bag_label_count,
                                   r.id as receive_id,
                                   r.received_date,
                                   r.receive_name as stored_receive_name,
                                   po.po_number,
                                   po.id as po_id,
                                   tt.tablet_type_name
                            FROM bags b
                            JOIN small_boxes sb ON b.small_box_id = sb.id
                            JOIN receiving r ON sb.receiving_id = r.id
                            JOIN purchase_orders po ON r.po_id = po.id
                            JOIN tablet_types tt ON b.tablet_type_id = tt.id
                            WHERE tt.id = ?
                            AND (r.closed IS NULL OR r.closed = FALSE)
                            ORDER BY r.received_date DESC
                            LIMIT 20
                        ''', (tablet_type_id,)).fetchall()
                    
                    if fallback_receives:
                        receives = []
                        for bag_row in fallback_receives:
                            bag = dict(bag_row)
                            stored_receive_name = bag.get('stored_receive_name')
                            if stored_receive_name:
                                receive_name = stored_receive_name
                            else:
                                receive_number = conn.execute('''
                                    SELECT COUNT(*) + 1
                                    FROM receiving r2
                                    WHERE r2.po_id = ?
                                    AND (r2.received_date < (SELECT received_date FROM receiving WHERE id = ?)
                                         OR (r2.received_date = (SELECT received_date FROM receiving WHERE id = ?) 
                                             AND r2.id < ?))
                                ''', (bag['po_id'], bag['receive_id'], bag['receive_id'], bag['receive_id'])).fetchone()[0]
                                receive_name = f"{bag['po_number']}-{receive_number}"
                            
                            receives.append({
                                'bag_id': bag['bag_id'],
                                'receive_id': bag['receive_id'],
                                'receive_name': receive_name,
                                'po_number': bag['po_number'],
                                'received_date': bag['received_date'],
                                'box_number': bag['box_number'],
                                'bag_number': bag['bag_number'],
                                'bag_label_count': bag['bag_label_count'],
                                'tablet_type_name': bag['tablet_type_name']
                            })
                        
                        return jsonify({
                            'success': True,
                            'submission': submission_dict,
                            'possible_receives': receives,
                            'warning': 'Submission missing bag_number. Showing all available receives for this product.'
                        })
                
                return jsonify({
                    'success': False, 
                    'error': 'Submission missing bag_number. Cannot find matching receives. Please check if the bag number was entered when submitting.'
                }), 400
            
            if not submission_dict.get('tablet_type_id'):
                return jsonify({
                    'success': False,
                    'error': f'Could not determine tablet_type_id for submission. Product: {submission_dict.get("product_name")}, inventory_item_id: {submission_dict.get("inventory_item_id")}'
                }), 400
            
            return jsonify({
                'success': True,
                'submission': submission_dict,
                'possible_receives': matching_bags
            })
    except Exception as e:
        current_app.logger.error(f"Error getting possible receives: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/submission/<int:submission_id>/assign-receive', methods=['POST'])
@role_required('dashboard')
def assign_submission_to_receive(submission_id):
    """Assign a submission to a specific receive bag"""
    try:
        data = request.get_json()
        with db_transaction() as conn:
            bag_id = data.get('bag_id')
            
            if not bag_id:
                return jsonify({'success': False, 'error': 'bag_id is required'}), 400
            
            bag = BagRepository.get_by_id(conn, bag_id)
            if not bag:
                return jsonify({'success': False, 'error': 'Bag not found'}), 404
            
            conn.execute('''
                UPDATE warehouse_submissions
                SET bag_id = ?, assigned_po_id = ?, needs_review = FALSE
                WHERE id = ?
            ''', (bag_id, bag['po_id'], submission_id))
            
            return jsonify({
                'success': True,
                'message': 'Submission assigned successfully'
            })
    except Exception as e:
        current_app.logger.error(f"Error assigning submission to receive: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

