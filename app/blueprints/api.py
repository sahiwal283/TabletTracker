"""
API routes - all /api/* endpoints
"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session, make_response, current_app
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from werkzeug.utils import secure_filename
import json
import traceback
import csv
import io
import os
import re
import requests
import sqlite3
from config import Config
from __version__ import __version__, __title__, __description__
from flask_babel import gettext, ngettext, get_locale
from app.services.zoho_service import zoho_api
from app.services.tracking_service import refresh_shipment_row
from app.services.report_service import ProductionReportGenerator
from app.utils.db_utils import get_db
from app.utils.auth_utils import admin_required, role_required, employee_required
from app.utils.route_helpers import get_setting, ensure_app_settings_table, ensure_submission_type_column
from app.utils.receive_tracking import find_bag_for_submission

bp = Blueprint('api', __name__)


@bp.route('/api/bag/<int:bag_id>/submissions', methods=['GET'])
@role_required('dashboard')
def get_bag_submissions(bag_id):
    """Get all submissions for a specific bag (for duplicate review)"""
    conn = None
    try:
        conn = get_db()
        
        # Get bag details first
        bag = conn.execute('''
            SELECT b.*, tt.inventory_item_id, sb.box_number, r.po_id
            FROM bags b
            JOIN small_boxes sb ON b.small_box_id = sb.id
            JOIN receiving r ON sb.receiving_id = r.id
            JOIN tablet_types tt ON b.tablet_type_id = tt.id
            WHERE b.id = ?
        ''', (bag_id,)).fetchone()
        
        if not bag:
            return jsonify({'error': 'Bag not found'}), 404
        
        current_app.logger.info(f"🔍 GET /api/bag/{bag_id}/submissions")
        current_app.logger.info(f"   Bag criteria: inventory_item_id={bag['inventory_item_id']}, box={bag['box_number']}, bag={bag['bag_number']}, po_id={bag['po_id']}")
        
        # Query for submissions that match either:
        # 1. Have bag_id directly assigned to this bag, OR
        # 2. Match on inventory_item_id + bag + po_id (box optional for flavor-based)
        # Note: If submissions are missing inventory_item_id, run database/backfill_inventory_item_id.py
        # UPDATED: Handle flavor-based submissions where box_number might be NULL
        submissions = conn.execute('''
            SELECT ws.*, 
                   pd.product_name as pd_product_name,
                   pd.packages_per_display,
                   pd.tablets_per_package,
                   (
                       CASE ws.submission_type
                           WHEN 'packaged' THEN (ws.displays_made * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0) + 
                                                ws.packs_remaining * COALESCE(pd.tablets_per_package, 0))
                           WHEN 'bag' THEN ws.loose_tablets
                           WHEN 'machine' THEN COALESCE(
                               ws.tablets_pressed_into_cards,
                               ws.loose_tablets,
                               (ws.packs_remaining * COALESCE(COALESCE(pd.tablets_per_package, pd_fallback.tablets_per_package), 0)),
                               0
                           )
                           ELSE ws.loose_tablets + ws.damaged_tablets
                       END
                   ) as total_tablets
            FROM warehouse_submissions ws
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            LEFT JOIN tablet_types tt_fallback ON ws.inventory_item_id = tt_fallback.inventory_item_id
            LEFT JOIN product_details pd_fallback ON tt_fallback.id = pd_fallback.tablet_type_id
            WHERE (
                ws.bag_id = ?
                OR (
                    ws.bag_id IS NULL
                    AND ws.inventory_item_id = ?
                    AND ws.bag_number = ?
                    AND ws.assigned_po_id = ?
                    AND (ws.box_number = ? OR ws.box_number IS NULL)
                )
            )
            ORDER BY ws.created_at DESC
        ''', (bag_id, bag['inventory_item_id'], bag['bag_number'], bag['po_id'], bag['box_number'])).fetchall()
        
        current_app.logger.info(f"   Matched {len(submissions)} submissions")
        
        return jsonify({
            'success': True,
            'submissions': [dict(row) for row in submissions]
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


@bp.route('/api/receive/<int:receive_id>/details', methods=['GET'])
@role_required('shipping')
def get_receive_details(receive_id):
    """Get receive details with submission counts (similar to PO details modal)"""
    conn = None
    try:
        conn = get_db()
        
        # Get receive details with PO info
        receive = conn.execute('''
            SELECT r.*, po.po_number, po.id as po_id
            FROM receiving r
            LEFT JOIN purchase_orders po ON r.po_id = po.id
            WHERE r.id = ?
        ''', (receive_id,)).fetchone()
        
        if not receive:
            return jsonify({'error': 'Receive not found'}), 404
        
        receive_dict = dict(receive)
        
        # Get all bags in this receive with their counts and tablet types
        bags = conn.execute('''
            SELECT b.*, tt.tablet_type_name, tt.inventory_item_id, sb.box_number
            FROM bags b
            JOIN small_boxes sb ON b.small_box_id = sb.id
            JOIN tablet_types tt ON b.tablet_type_id = tt.id
            WHERE sb.receiving_id = ?
            ORDER BY sb.box_number, b.bag_number
        ''', (receive_id,)).fetchall()
        
        # Group by product -> box -> bag
        products = {}
        for bag_row in bags:
            bag = dict(bag_row)  # Convert Row to dict
            inventory_item_id = bag['inventory_item_id']
            tablet_type_name = bag['tablet_type_name']
            box_number = bag['box_number']
            bag_number = bag['bag_number']
            bag_label_count = bag['bag_label_count'] or 0
            
            if inventory_item_id not in products:
                products[inventory_item_id] = {
                    'tablet_type_name': tablet_type_name,
                    'inventory_item_id': inventory_item_id,
                    'boxes': {}
                }
            
            if box_number not in products[inventory_item_id]['boxes']:
                products[inventory_item_id]['boxes'][box_number] = {}
            
            # Get submission counts for this specific bag
            # For machine submissions: calculate each submission individually to ensure proper fallback
            # UPDATED: Handle flavor-based submissions where box_number might be NULL
            # Bag and PO are tied together: bag belongs to receive, receive belongs to PO
            # Must verify: bag_id matches this bag AND assigned_po_id matches receive's PO AND bag belongs to this receive
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
                    (ws.bag_id = ? 
                     AND ws.assigned_po_id = ?
                     AND sb_verify.receiving_id = ?)
                    OR (
                        ws.bag_id IS NULL
                        AND ws.inventory_item_id = ?
                        AND ws.bag_number = ?
                        AND ws.assigned_po_id = ?
                        AND (ws.box_number = ? OR ws.box_number IS NULL)
                    )
                )
            ''', (bag['id'], receive_dict['po_id'], receive_id, inventory_item_id, bag_number, receive_dict['po_id'], box_number)).fetchall()
            
            machine_total = 0
            for machine_sub in machine_submissions:
                msub = dict(machine_sub)
                tablets_per_package = msub.get('tablets_per_package_final') or 0
                
                # If still 0, do direct query
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
                
                # Calculate total for this submission
                sub_total = (msub.get('tablets_pressed_into_cards') or
                            msub.get('loose_tablets') or
                            ((msub.get('packs_remaining', 0) or 0) * tablets_per_package) or
                            0)
                machine_total += sub_total
            
            # UPDATED: Handle flavor-based submissions where box_number might be NULL
            # Bag and PO are tied together: bag belongs to receive, receive belongs to PO
            # Must verify: bag_id matches this bag AND assigned_po_id matches receive's PO AND bag belongs to this receive
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
                    (ws.bag_id = ? 
                     AND ws.assigned_po_id = ?
                     AND sb_verify.receiving_id = ?)
                    OR (
                        ws.bag_id IS NULL
                        AND ws.inventory_item_id = ?
                        AND ws.bag_number = ?
                        AND ws.assigned_po_id = ?
                        AND (ws.box_number = ? OR ws.box_number IS NULL)
                    )
                )
            ''', (bag['id'], receive_dict['po_id'], receive_id, inventory_item_id, bag_number, receive_dict['po_id'], box_number)).fetchone()
            
            # UPDATED: Handle flavor-based submissions where box_number might be NULL
            # Bag and PO are tied together: bag belongs to receive, receive belongs to PO
            # Must verify: bag_id matches this bag AND assigned_po_id matches receive's PO AND bag belongs to this receive
            bag_count = conn.execute('''
                SELECT COALESCE(SUM(COALESCE(ws.loose_tablets, 0)), 0) as total_bag
                FROM warehouse_submissions ws
                LEFT JOIN bags b_verify ON ws.bag_id = b_verify.id
                LEFT JOIN small_boxes sb_verify ON b_verify.small_box_id = sb_verify.id
                WHERE ws.submission_type = 'bag'
                AND (
                    (ws.bag_id = ? 
                     AND ws.assigned_po_id = ?
                     AND sb_verify.receiving_id = ?)
                    OR (
                        ws.bag_id IS NULL
                        AND ws.inventory_item_id = ?
                        AND ws.bag_number = ?
                        AND ws.assigned_po_id = ?
                        AND (ws.box_number = ? OR ws.box_number IS NULL)
                    )
                )
            ''', (bag['id'], receive_dict['po_id'], receive_id, inventory_item_id, bag_number, receive_dict['po_id'], box_number)).fetchone()
            
            products[inventory_item_id]['boxes'][box_number][bag_number] = {
                'bag_id': bag['id'],
                'bag_number': bag_number,
                'box_number': box_number,
                'status': bag.get('status', 'Available'),
                'received_count': bag_label_count,
                'machine_count': machine_total,
                'packaged_count': dict(packaged_count)['total_packaged'] if packaged_count else 0,
                'bag_count': dict(bag_count)['total_bag'] if bag_count else 0
            }
        
        # Convert nested dict to list format for easier frontend handling
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
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@bp.route('/api/sync_zoho_pos', methods=['GET', 'POST'])
@role_required('dashboard')
def sync_zoho_pos():
    """Sync Purchase Orders from Zoho Inventory"""
    conn = None
    try:
        print("🔄 Starting Zoho PO sync...")
        conn = get_db()
        print("✅ Database connection established")
        
        print("📡 Calling Zoho API sync function...")
        success, message = zoho_api.sync_tablet_pos_to_db(conn)
        print(f"✅ Sync completed. Success: {success}, Message: {message}")
        
        if success:
            return jsonify({'message': message, 'success': True})
        else:
            return jsonify({'error': message, 'success': False}), 400
            
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ Sync Zoho POs error: {str(e)}")
        print(f"Traceback: {error_trace}")
        return jsonify({'error': f'Sync failed: {str(e)}', 'success': False}), 500
    finally:
        if conn:
            try:
                conn.close()
                print("✅ Database connection closed")
            except:
                pass



@bp.route('/api/create_overs_po/<int:po_id>', methods=['POST'])
@role_required('dashboard')
def create_overs_po(po_id):
    """Create an overs PO in Zoho for a parent PO"""
    conn = None
    try:
        conn = get_db()
        
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
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/create_overs_po_info/<int:po_id>')
@role_required('dashboard')
def get_overs_po_info(po_id):
    """Get information needed to create an overs PO for a parent PO (for preview)"""
    conn = None
    try:
        conn = get_db()
        
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
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/po_lines/<int:po_id>')
def get_po_lines(po_id):
    """Get line items for a specific PO"""
    conn = None
    try:
        conn = get_db()
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
            # Calculate total tablets for machine counts
            # For machine submissions: use tablets_pressed_into_cards column (fallback to loose_tablets for old data)
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
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'error': f'Failed to get PO lines: {str(e)}'}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@bp.route('/admin/products')
@admin_required
def product_mapping():
    """Show product → tablet mapping and calculation examples"""
    conn = None
    try:
        conn = get_db()
        
        # Get all products with their tablet type and calculation details
        # Use LEFT JOIN to include products even if tablet_type_id is NULL or invalid
        products = conn.execute('''
            SELECT pd.*, tt.tablet_type_name, tt.inventory_item_id, tt.category
            FROM product_details pd
            LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            ORDER BY COALESCE(tt.tablet_type_name, ''), pd.product_name
        ''').fetchall()
        
        # Check if category column exists and add it if missing
        table_info = conn.execute("PRAGMA table_info(tablet_types)").fetchall()
        has_category_column = any(col[1] == 'category' for col in table_info)
        
        if not has_category_column:
            try:
                conn.execute('ALTER TABLE tablet_types ADD COLUMN category TEXT')
                conn.commit()
                has_category_column = True
            except Exception as e:
                if conn:
                    try:
                        conn.rollback()
                    except:
                        pass
                print(f"Warning: Could not add category column: {e}")
        
        # Get tablet types for dropdown
        if has_category_column:
            tablet_types = conn.execute('SELECT * FROM tablet_types ORDER BY tablet_type_name').fetchall()
            # Get unique categories (including those with tablet types assigned)
            categories = conn.execute('SELECT DISTINCT category FROM tablet_types WHERE category IS NOT NULL AND category != "" ORDER BY category').fetchall()
            category_list = [cat['category'] for cat in categories] if categories else []
        else:
            # Fallback: get tablet types without category column
            tablet_types_raw = conn.execute('SELECT id, tablet_type_name, inventory_item_id FROM tablet_types ORDER BY tablet_type_name').fetchall()
            # Convert to dict format with None category
            tablet_types = [dict(row) for row in tablet_types_raw]
            for tt in tablet_types:
                tt['category'] = None
            category_list = []
        
        # Get deleted categories from app_settings
        deleted_categories_set = set()
        try:
            deleted_categories_json = conn.execute('''
                SELECT setting_value FROM app_settings WHERE setting_key = 'deleted_categories'
            ''').fetchone()
            if deleted_categories_json and deleted_categories_json['setting_value']:
                try:
                    deleted_categories_set = set(json.loads(deleted_categories_json['setting_value']))
                except (json.JSONDecodeError, ValueError, TypeError):
                    deleted_categories_set = set()
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except:
                    pass
            print(f"Warning: Could not load deleted categories: {e}")
            # Continue without filtering if there's an error
        
        # Get category order from app_settings (or use alphabetical as fallback)
        try:
            category_order_json = conn.execute('''
                SELECT setting_value FROM app_settings WHERE setting_key = 'category_order'
            ''').fetchone()
            if category_order_json and category_order_json['setting_value']:
                try:
                    preferred_order = json.loads(category_order_json['setting_value'])
                except (json.JSONDecodeError, ValueError, TypeError):
                    preferred_order = sorted(category_list)
            else:
                # No saved order - use alphabetical
                preferred_order = sorted(category_list)
        except Exception as e:
            print(f"Warning: Could not load category order: {e}")
            preferred_order = sorted(category_list)
        
        # Filter out deleted categories
        all_categories = [cat for cat in category_list if cat not in deleted_categories_set]
        
        # Sort by preferred order (categories not in preferred_order go at the end alphabetically)
        all_categories.sort(key=lambda x: (preferred_order.index(x) if x in preferred_order else len(preferred_order) + 1, x))
        
        # Find tablet types that don't have product configurations yet
        product_tablet_type_ids = set(p['tablet_type_id'] for p in products if p['tablet_type_id'])
        tablet_types_without_products = [tt for tt in tablet_types if tt['id'] not in product_tablet_type_ids]
        
        return render_template('product_mapping.html', products=products, tablet_types=tablet_types, 
                             categories=all_categories, tablet_types_without_products=tablet_types_without_products)
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        flash(f'Error loading product mapping: {str(e)}', 'error')
        return render_template('product_mapping.html', products=[], tablet_types=[])
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@bp.route('/admin/tablet_types')
@admin_required
def tablet_types_config():
    """Configuration page for tablet types and their inventory item IDs"""
    conn = None
    try:
        conn = get_db()
        
        # Get all tablet types with their current inventory item IDs
        tablet_types = conn.execute('''
            SELECT * FROM tablet_types 
            ORDER BY tablet_type_name
        ''').fetchall()
        
        return render_template('tablet_types_config.html', tablet_types=tablet_types)
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        flash(f'Error loading tablet types: {str(e)}', 'error')
        return render_template('tablet_types_config.html', tablet_types=[])
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@bp.route('/shipping')
@role_required('shipping')
def shipping_unified():
    """Shipments Received page - record shipments that arrive"""
    conn = None
    try:
        conn = get_db()
        
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
        
        # Calculate shipment numbers for each PO (numbered sequentially by received_date)
        # Group shipments by PO and assign numbers
        po_shipment_counts = {}
        for rec in receiving_records:
            po_id = rec['po_id']
            if po_id:
                if po_id not in po_shipment_counts:
                    # Get all shipments for this PO ordered by received_date
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
            # Add shipment number if PO is assigned
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
            
            # Get bags for each box with tablet type info
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
        if conn:
            try:
                conn.rollback()
            except:
                pass
        import traceback
        error_details = traceback.format_exc()
        current_app.logger.error(f"Error in shipping_unified: {str(e)}\n{error_details}")
        return render_template('error.html', 
                             error_message=f"Error loading shipping page: {str(e)}\n\nFull traceback:\n{error_details}"), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/shipments/<int:shipment_id>/refresh', methods=['POST'])
def refresh_shipment(shipment_id: int):
    """Manually refresh a single shipment's tracking status."""
    conn = None
    try:
        conn = get_db()
        result = refresh_shipment_row(conn, shipment_id)
        if result.get('success'):
            return jsonify(result)
        return jsonify(result), 400
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/shipment/<int:shipment_id>', methods=['GET'])
def get_shipment(shipment_id: int):
    conn = None
    try:
        conn = get_db()
        row = conn.execute('''
            SELECT id, po_id, tracking_number, carrier, shipped_date, estimated_delivery, actual_delivery, notes
            FROM shipments WHERE id = ?
        ''', (shipment_id,)).fetchone()
        if not row:
            return jsonify({'success': False, 'error': 'Not found'}), 404
        return jsonify({'success': True, 'shipment': dict(row)})
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/shipment/<int:shipment_id>', methods=['DELETE'])
def delete_shipment(shipment_id: int):
    conn = None
    try:
        conn = get_db()
        conn.execute('DELETE FROM shipments WHERE id = ?', (shipment_id,))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/save_shipment', methods=['POST'])
def save_shipment():
    """Save shipment information (supports multiple shipments per PO)"""
    conn = None
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data.get('po_id'):
            return jsonify({'success': False, 'error': 'po_id is required'}), 400
        
        # Validate po_id is numeric
        try:
            po_id = int(data['po_id'])
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid po_id'}), 400
        
        conn = get_db()
        
        # For multiple shipments per PO, always create new unless we're editing a specific shipment
        shipment_id = data.get('shipment_id')
        
        if shipment_id:
            # Validate shipment_id is numeric
            try:
                shipment_id = int(shipment_id)
            except (ValueError, TypeError):
                return jsonify({'success': False, 'error': 'Invalid shipment_id'}), 400
                
            # Update existing specific shipment
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
            # Create new shipment (allows multiple shipments per PO)
            conn.execute('''
                INSERT INTO shipments (po_id, tracking_number, carrier, shipped_date,
                                     estimated_delivery, actual_delivery, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (po_id, data.get('tracking_number'), data.get('carrier'), 
                  data.get('shipped_date'), data.get('estimated_delivery'), 
                  data.get('actual_delivery'), data.get('notes')))
            # set carrier_code based on carrier
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
                print(f"Auto-progressed PO {po_id} to Shipped (tracking added)")
        
        conn.commit()

        # Trigger immediate UPS refresh when applicable
        if data.get('tracking_number') and (data.get('carrier', '').lower() in ('ups','fedex','fed ex')):
            sh = conn.execute('''
                SELECT id FROM shipments WHERE po_id = ? AND tracking_number = ?
                ORDER BY updated_at DESC LIMIT 1
            ''', (po_id, data.get('tracking_number'))).fetchone()
            if sh:
                try:
                    result = refresh_shipment_row(conn, sh['id'])
                    print('UPS refresh result:', result)
                except Exception as exc:
                    print('UPS refresh error:', exc)

        return jsonify({'success': True, 'message': 'Shipment saved; tracking refreshed if supported'})
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/update_tablet_type_inventory', methods=['POST'])
@admin_required
def update_tablet_type_inventory():
    """Update a tablet type's inventory item ID"""
    conn = None
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Invalid JSON data'}), 400
            
        tablet_type_id = data.get('tablet_type_id')
        if not tablet_type_id:
            return jsonify({'success': False, 'error': 'Tablet type ID required'}), 400
            
        inventory_item_id = (data.get('inventory_item_id') or '').strip()
        
        conn = get_db()
        
        # Clear the inventory_item_id if empty
        if not inventory_item_id:
            conn.execute('''
                UPDATE tablet_types 
                SET inventory_item_id = NULL
                WHERE id = ?
            ''', (tablet_type_id,))
        else:
            # Check if this inventory_item_id is already used
            existing = conn.execute('''
                SELECT tablet_type_name FROM tablet_types 
                WHERE inventory_item_id = ? AND id != ?
            ''', (inventory_item_id, tablet_type_id)).fetchone()
            
            if existing:
                return jsonify({
                    'success': False, 
                    'error': f'Inventory ID already used by {existing["tablet_type_name"]}'
                })
            
            conn.execute('''
                UPDATE tablet_types 
                SET inventory_item_id = ?
                WHERE id = ?
            ''', (inventory_item_id, tablet_type_id))
        
        conn.commit()
        
        return jsonify({'success': True, 'message': 'Tablet type updated successfully'})
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/settings/cards_per_turn', methods=['GET', 'POST'])
@admin_required
def manage_cards_per_turn():
    """Get or update cards per turn setting"""
    conn = None
    try:
        ensure_app_settings_table()  # Ensure table exists
        conn = get_db()
        
        if request.method == 'GET':
            setting = conn.execute(
                'SELECT setting_value, description FROM app_settings WHERE setting_key = ?',
                ('cards_per_turn',)
            ).fetchone()
            if setting:
                return jsonify({
                    'success': True,
                    'value': int(setting['setting_value']),
                    'description': setting['description']
                })
            else:
                return jsonify({'success': False, 'error': 'Setting not found'}), 404
        
        elif request.method == 'POST':
            data = request.get_json()
            if not data:
                return jsonify({'success': False, 'error': 'No data provided'}), 400
            
            cards_per_turn = data.get('cards_per_turn')
            
            if cards_per_turn is None:
                return jsonify({'success': False, 'error': 'cards_per_turn is required'}), 400
            
            try:
                cards_per_turn = int(cards_per_turn)
                if cards_per_turn < 1:
                    return jsonify({'success': False, 'error': 'cards_per_turn must be at least 1'}), 400
            except (ValueError, TypeError):
                return jsonify({'success': False, 'error': 'Invalid cards_per_turn value'}), 400
            
            # Update or insert setting
            existing = conn.execute(
                'SELECT id FROM app_settings WHERE setting_key = ?',
                ('cards_per_turn',)
            ).fetchone()
            
            if existing:
                conn.execute('''
                    UPDATE app_settings 
                    SET setting_value = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE setting_key = ?
                ''', (str(cards_per_turn), 'cards_per_turn'))
            else:
                conn.execute('''
                    INSERT INTO app_settings (setting_key, setting_value, description)
                    VALUES (?, ?, ?)
                ''', ('cards_per_turn', str(cards_per_turn), 'Number of cards produced in one turn of the machine'))
            
            conn.commit()
            return jsonify({
                'success': True,
                'message': f'Cards per turn updated to {cards_per_turn}'
            })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@bp.route('/admin')
def admin_panel():
    """Admin panel with quick actions and product management"""
    # Check for admin session
    if not session.get('admin_authenticated'):
        return render_template('admin_login.html')
    
    conn = None
    try:
        ensure_app_settings_table()  # Ensure table exists
        conn = get_db()
        # Get current settings
        cards_per_turn = conn.execute(
            'SELECT setting_value FROM app_settings WHERE setting_key = ?',
            ('cards_per_turn',)
        ).fetchone()
        cards_per_turn_value = int(cards_per_turn['setting_value']) if cards_per_turn else 1
        return render_template('admin_panel.html', cards_per_turn=cards_per_turn_value)
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        import traceback
        traceback.print_exc()
        return render_template('admin_panel.html', cards_per_turn=1)
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@bp.route('/admin/login', methods=['POST'])
def admin_login():
    """Handle admin login with enhanced security"""
    password = request.form.get('password') or request.json.get('password')
    
    # Get admin password from environment variable with secure default
    admin_password = Config.ADMIN_PASSWORD
    
    if password == admin_password:
        session['admin_authenticated'] = True
        session['employee_role'] = 'admin'  # Set admin role for navigation
        session['login_time'] = datetime.now().isoformat()
        session.permanent = True  # Make session permanent
        current_app.permanent_session_lifetime = timedelta(hours=8)  # 8 hour timeout
        
        return redirect('/admin') if request.form else jsonify({'success': True})
    else:
        # Log failed login attempt
        print(f"Failed admin login attempt from {request.remote_addr} at {datetime.now()}")
        
        if request.form:
            flash('Invalid password', 'error')
            return render_template('admin_login.html')
        else:
            return jsonify({'success': False, 'error': 'Invalid password'})

@bp.route('/admin/logout')
def admin_logout():
    """Logout admin - redirect to unified logout"""
    return redirect(url_for('auth.logout'))

@bp.route('/login')
def employee_login():
    """Employee login page"""
    return render_template('employee_login.html')

@bp.route('/login', methods=['POST'])
def employee_login_post():
    """Handle employee login"""
    conn = None
    try:
        username = request.form.get('username') or request.json.get('username')
        password = request.form.get('password') or request.json.get('password')
        
        if not username or not password:
            if request.form:
                flash('Username and password required', 'error')
                return render_template('employee_login.html')
            else:
                return jsonify({'success': False, 'error': 'Username and password required'})
        
        conn = get_db()
        employee = conn.execute('''
            SELECT id, username, full_name, password_hash, role, is_active 
            FROM employees 
            WHERE username = ? AND is_active = TRUE
        ''', (username,)).fetchone()
        
        if employee and verify_password(password, employee['password_hash']):
            session['employee_authenticated'] = True
            session['employee_id'] = employee['id']
            session['employee_name'] = employee['full_name']
            session['employee_username'] = employee['username']
            session['employee_role'] = employee['role'] if employee['role'] else 'warehouse_staff'
            session.permanent = True
            current_app.permanent_session_lifetime = timedelta(hours=8)
            
            return redirect(url_for('production.warehouse_form')) if request.form else jsonify({'success': True})
        else:
            # Log failed login attempt
            print(f"Failed employee login attempt for {username} from {request.remote_addr} at {datetime.now()}")
            
            if request.form:
                flash('Invalid username or password', 'error')
                return render_template('employee_login.html')
            else:
                return jsonify({'success': False, 'error': 'Invalid username or password'})
    except Exception as e:
        # Log error but don't expose details to user
        print(f"Login error: {str(e)}")
        if conn:
            try:
                conn.rollback()
            except:
                pass
        if request.form:
            flash('An error occurred during login', 'error')
            return render_template('employee_login.html')
        else:
            return jsonify({'success': False, 'error': 'An error occurred during login'}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@bp.route('/logout')
def logout():
    """Unified logout for both employees and admin"""
    # Clear all session data
    session.pop('admin_authenticated', None)
    session.pop('employee_authenticated', None)
    session.pop('employee_id', None)
    session.pop('employee_name', None)
    session.pop('employee_username', None)
    session.pop('employee_role', None)
    session.pop('login_time', None)
    
    flash('You have been logged out successfully', 'success')
    return redirect(url_for('auth.index'))

@bp.route('/count')
@employee_required
def count_form():
    """Legacy route - redirects to production page"""
    return redirect(url_for('production.production_form'))

@bp.route('/submit_count', methods=['POST'])
def submit_count():
    """Process manual count submission for PO close-outs - RECEIVE-BASED TRACKING"""
    conn = None
    try:
        data = request.get_json() if request.is_json else request.form
        
        # Ensure submission_type column exists
        ensure_submission_type_column()
        
        # Validate required fields
        if not data.get('tablet_type'):
            return jsonify({'error': 'tablet_type is required'}), 400
        
        conn = get_db()
        
        # Get employee name from session (logged-in user)
        if session.get('admin_authenticated'):
            employee_name = 'Admin'
        else:
            employee = conn.execute('''
                SELECT full_name FROM employees WHERE id = ?
            ''', (session.get('employee_id'),)).fetchone()
            
            if not employee:
                return jsonify({'error': 'Employee not found'}), 400
            
            employee_name = employee['full_name']
        
        # Get tablet type details
        tablet_type = conn.execute('''
            SELECT * FROM tablet_types
            WHERE tablet_type_name = ?
        ''', (data.get('tablet_type'),)).fetchone()
        
        if not tablet_type:
            return jsonify({'error': 'Tablet type not found'}), 400
        
        # Convert Row to dict for safe access
        tablet_type = dict(tablet_type)
        
        # Safe type conversion
        try:
            actual_count = int(data.get('actual_count', 0) or 0)
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid numeric values for counts'}), 400
        
        # Get submission_date (defaults to today if not provided)
        submission_date = data.get('submission_date', datetime.now().date().isoformat())
        
        # Get admin_notes if user is admin or manager
        admin_notes = None
        if session.get('admin_authenticated') or session.get('employee_role') in ['admin', 'manager']:
            admin_notes_raw = data.get('admin_notes', '')
            if admin_notes_raw and isinstance(admin_notes_raw, str):
                admin_notes = admin_notes_raw.strip() or None
            elif admin_notes_raw:
                admin_notes = str(admin_notes_raw).strip() or None
        
        # Get inventory_item_id and tablet_type_id
        inventory_item_id = tablet_type.get('inventory_item_id')
        tablet_type_id = tablet_type.get('id')
        if not inventory_item_id:
            return jsonify({'error': 'Tablet type inventory_item_id not found'}), 400
        if not tablet_type_id:
            return jsonify({'error': 'Tablet type_id not found'}), 400
        
        # RECEIVE-BASED TRACKING: Find matching bag in receives
        # NEW: Pass bag_number first, box_number as optional parameter
        bag, needs_review, error_message = find_bag_for_submission(
            conn, tablet_type_id, data.get('bag_number'), data.get('box_number')
        )
        
        if error_message:
            return jsonify({'error': error_message}), 404
        
        # If needs_review, bag will be None (ambiguous submission)
        bag_id = bag['id'] if bag else None
        assigned_po_id = bag['po_id'] if bag else None
        
        # Insert count record with bag_id (or NULL if needs review)
        conn.execute('''
            INSERT INTO warehouse_submissions 
            (employee_name, product_name, inventory_item_id, box_number, bag_number, 
             bag_id, assigned_po_id, needs_review, loose_tablets, 
             submission_date, admin_notes, submission_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'bag')
        ''', (employee_name, data.get('tablet_type'), inventory_item_id, data.get('box_number'),
              data.get('bag_number'), bag_id, assigned_po_id, needs_review,
              actual_count, submission_date, admin_notes))
        
        conn.commit()
        
        message = 'Count flagged for manager review - multiple matching receives found.' if needs_review else 'Bag count submitted successfully!'
        
        return jsonify({
            'success': True,
            'message': message,
            'bag_id': bag_id,
            'po_id': assigned_po_id,
            'needs_review': needs_review
        })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@bp.route('/submit_machine_count', methods=['POST'])
@employee_required
def submit_machine_count():
    """Submit machine count reading and create warehouse submission"""
    conn = None
    try:
        data = request.get_json()
        
        # Ensure required tables/columns exist
        ensure_submission_type_column()
        ensure_machine_counts_table()
        ensure_machine_count_columns()
        
        tablet_type_id = data.get('tablet_type_id')
        machine_count = data.get('machine_count')
        count_date = data.get('count_date')
        
        # Validation
        if not tablet_type_id:
            return jsonify({'error': 'Tablet type is required'}), 400
        if machine_count is None or machine_count < 0:
            return jsonify({'error': 'Valid machine count is required'}), 400
        if not count_date:
            return jsonify({'error': 'Date is required'}), 400
        
        conn = get_db()
        
        # Get employee name from session (logged-in user)
        if session.get('admin_authenticated'):
            employee_name = 'Admin'
        else:
            employee = conn.execute('''
                SELECT full_name FROM employees WHERE id = ?
            ''', (session.get('employee_id'),)).fetchone()
            
            if not employee:
                return jsonify({'error': 'Employee not found'}), 400
            
            employee_name = employee['full_name']
        
        # Verify tablet type exists and get its info
        tablet_type = conn.execute('''
            SELECT id, tablet_type_name, inventory_item_id 
            FROM tablet_types 
            WHERE id = ?
        ''', (tablet_type_id,)).fetchone()
        if not tablet_type:
            return jsonify({'error': 'Invalid tablet type'}), 400
        
        tablet_type = dict(tablet_type)
        
        # Get a product for this tablet type to get tablets_per_package
        product = conn.execute('''
            SELECT product_name, tablets_per_package 
            FROM product_details 
            WHERE tablet_type_id = ? 
            LIMIT 1
        ''', (tablet_type_id,)).fetchone()
        
        if not product:
            return jsonify({'error': 'No product found for this tablet type. Please configure a product first.'}), 400
        
        product = dict(product)
        tablets_per_package = product.get('tablets_per_package', 0)
        
        if tablets_per_package == 0:
            return jsonify({'error': 'Product configuration incomplete: tablets_per_package must be greater than 0'}), 400
        
        # Get machine_id from form data FIRST (before calculating cards_per_turn)
        machine_id = data.get('machine_id')
        if machine_id:
            try:
                machine_id = int(machine_id)
            except (ValueError, TypeError):
                machine_id = None
        
        # Get machine-specific cards_per_turn from machines table
        cards_per_turn = None
        if machine_id:
            machine_row = conn.execute('''
                SELECT cards_per_turn FROM machines WHERE id = ?
            ''', (machine_id,)).fetchone()
            if machine_row:
                machine = dict(machine_row)
                cards_per_turn = machine.get('cards_per_turn')
        
        # Fallback to global setting if machine not found or doesn't have cards_per_turn
        if not cards_per_turn:
            cards_per_turn_setting = get_setting('cards_per_turn', '1')
            try:
                cards_per_turn = int(cards_per_turn_setting)
            except (ValueError, TypeError):
                cards_per_turn = 1
        
        # Calculate total tablets for machine submissions
        # Formula: turns × cards_per_turn × tablets_per_package = total tablets pressed into cards
        try:
            machine_count_int = int(machine_count)
            total_tablets = machine_count_int * cards_per_turn * tablets_per_package
            # For machine submissions: these tablets are pressed into blister cards (not loose)
            # Store in a clearly named variable to distinguish from actual loose tablets
            tablets_pressed_into_cards = total_tablets
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid machine count value'}), 400
        
        # Insert machine count record (for historical tracking)
        if machine_id:
            conn.execute('''
                INSERT INTO machine_counts (tablet_type_id, machine_id, machine_count, employee_name, count_date)
                VALUES (?, ?, ?, ?, ?)
            ''', (tablet_type_id, machine_id, machine_count_int, employee_name, count_date))
        else:
            conn.execute('''
                INSERT INTO machine_counts (tablet_type_id, machine_count, employee_name, count_date)
                VALUES (?, ?, ?, ?)
            ''', (tablet_type_id, machine_count_int, employee_name, count_date))
        
        # Get inventory_item_id and tablet_type_id
        inventory_item_id = tablet_type.get('inventory_item_id')
        tablet_type_id = tablet_type.get('id')
        
        if not inventory_item_id or not tablet_type_id:
            conn.commit()
            return jsonify({'warning': 'Tablet type inventory_item_id or id not found. Submission saved but not assigned to PO.', 'submission_saved': True})
        
        # Get box/bag numbers from form data
        box_number = data.get('box_number')
        bag_number = data.get('bag_number')
        
        # Get admin_notes if user is admin or manager
        admin_notes = None
        is_admin_or_manager = session.get('admin_authenticated') or session.get('employee_role') in ['admin', 'manager']
        if is_admin_or_manager:
            admin_notes_raw = data.get('admin_notes', '')
            if admin_notes_raw and isinstance(admin_notes_raw, str):
                admin_notes = admin_notes_raw.strip() or None
            elif admin_notes_raw:
                # Handle non-string values (shouldn't happen, but be safe)
                admin_notes = str(admin_notes_raw).strip() or None
            # Debug logging
            print(f"Machine submission admin_notes: raw='{admin_notes_raw}', processed='{admin_notes}', is_admin={is_admin_or_manager}")
        
        # RECEIVE-BASED TRACKING: Try to match to existing receive/bag
        bag = None
        needs_review = False
        error_message = None
        assigned_po_id = None
        bag_id = None
        
        if bag_number:
            # NEW: Pass bag_number first, box_number as optional parameter
            bag, needs_review, error_message = find_bag_for_submission(conn, tablet_type_id, bag_number, box_number)
            
            if bag:
                # Exact match found - auto-assign
                bag_id = bag['id']
                assigned_po_id = bag['po_id']
                box_ref = f", box={box_number}" if box_number else ""
                print(f"✅ Matched to receive: bag_id={bag_id}, po_id={assigned_po_id}, bag={bag_number}{box_ref}")
            elif needs_review:
                # Multiple matches - needs manual review
                box_ref = f" Box {box_number}," if box_number else ""
                print(f"⚠️ Multiple receives found for{box_ref} Bag {bag_number} - needs review")
            elif error_message:
                # No match found
                print(f"❌ {error_message}")
        
        # Get receipt_number from form data
        receipt_number = (data.get('receipt_number') or '').strip() or None
        
        # Create warehouse submission with submission_type='machine'
        # For machine submissions:
        # - displays_made = machine_count_int (turns)
        # - packs_remaining = machine_count_int * cards_per_turn (cards made)
        # - tablets_pressed_into_cards = total tablets pressed into blister cards (properly named column)
        cards_made = machine_count_int * cards_per_turn
        conn.execute('''
            INSERT INTO warehouse_submissions 
            (employee_name, product_name, inventory_item_id, box_number, bag_number, 
             displays_made, packs_remaining, tablets_pressed_into_cards,
             submission_date, submission_type, bag_id, assigned_po_id, needs_review, machine_id, admin_notes, receipt_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'machine', ?, ?, ?, ?, ?, ?)
        ''', (employee_name, product['product_name'], inventory_item_id, box_number, bag_number,
              machine_count_int, cards_made, tablets_pressed_into_cards,
              count_date, bag_id, assigned_po_id, needs_review, machine_id, admin_notes, receipt_number))
        
        # If no receive match, submission is saved but not assigned
        if not assigned_po_id:
            conn.commit()
            if error_message:
                return jsonify({
                    'success': True,
                    'warning': error_message,
                    'submission_saved': True,
                    'needs_review': needs_review,
                    'message': 'Machine count submitted successfully.'
                })
            else:
                return jsonify({
                    'success': True,
                    'warning': 'No receive found for this box/bag combination. Submission saved but not assigned to PO.',
                    'submission_saved': True,
                    'message': 'Machine count submitted successfully.'
                })
        
        # Get PO lines for the matched PO to update counts
        po_lines = conn.execute('''
            SELECT pl.*, po.closed
            FROM po_lines pl
            JOIN purchase_orders po ON pl.po_id = po.id
            WHERE pl.inventory_item_id = ? AND po.id = ?
        ''', (inventory_item_id, assigned_po_id)).fetchall()
        
        # Only allocate to lines from the ASSIGNED PO
        assigned_po_lines = [line for line in po_lines if line['po_id'] == assigned_po_id]
        
        # Update machine_good_count (separate from regular good_count)
        if assigned_po_lines:
            line = assigned_po_lines[0]
            conn.execute('''
                UPDATE po_lines 
                SET machine_good_count = machine_good_count + ?
                WHERE id = ?
            ''', (tablets_pressed_into_cards, line['id']))
            print(f"Machine count - Updated PO line {line['id']}: +{tablets_pressed_into_cards} tablets pressed into cards")
        
        # Update PO header totals (separate machine counts)
        updated_pos = set()
        for line in assigned_po_lines:
            if line['po_id'] not in updated_pos:
                totals = conn.execute('''
                    SELECT 
                        COALESCE(SUM(quantity_ordered), 0) as total_ordered,
                        COALESCE(SUM(good_count), 0) as total_good,
                        COALESCE(SUM(damaged_count), 0) as total_damaged,
                        COALESCE(SUM(machine_good_count), 0) as total_machine_good,
                        COALESCE(SUM(machine_damaged_count), 0) as total_machine_damaged
                    FROM po_lines 
                    WHERE po_id = ?
                ''', (line['po_id'],)).fetchone()
                
                remaining = totals['total_ordered'] - totals['total_good'] - totals['total_damaged']
                
                conn.execute('''
                    UPDATE purchase_orders 
                    SET ordered_quantity = ?, current_good_count = ?, 
                        current_damaged_count = ?, remaining_quantity = ?,
                        machine_good_count = ?, machine_damaged_count = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (totals['total_ordered'], totals['total_good'], 
                      totals['total_damaged'], remaining,
                      totals['total_machine_good'], totals['total_machine_damaged'],
                      line['po_id']))
                
                updated_pos.add(line['po_id'])
        
        conn.commit()
        
        return jsonify({
            'success': True, 
            'message': 'Machine count submitted successfully.'
        })
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/save_product', methods=['POST'])
@admin_required
def save_product():
    """Save or update a product configuration"""
    conn = None
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['product_name', 'tablet_type_id', 'packages_per_display', 'tablets_per_package']
        for field in required_fields:
            if field not in data or data[field] is None:
                return jsonify({'success': False, 'error': f'{field} is required'}), 400
        
        # Validate numeric fields
        try:
            tablet_type_id = int(data['tablet_type_id'])
            packages_per_display = int(data['packages_per_display'])
            tablets_per_package = int(data['tablets_per_package'])
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid numeric values for tablet_type_id, packages_per_display, or tablets_per_package'}), 400
        
        conn = get_db()
        
        product_name = data.get('product_name')
        
        if data.get('id'):
            # Update existing product
            try:
                product_id = int(data['id'])
            except (ValueError, TypeError):
                return jsonify({'success': False, 'error': 'Invalid product ID'}), 400
                
            conn.execute('''
                UPDATE product_details 
                SET product_name = ?, tablet_type_id = ?, packages_per_display = ?, tablets_per_package = ?
                WHERE id = ?
            ''', (product_name, tablet_type_id, packages_per_display, tablets_per_package, product_id))
            message = f"Updated {product_name}"
        else:
            # Create new product
            conn.execute('''
                INSERT INTO product_details (product_name, tablet_type_id, packages_per_display, tablets_per_package)
                VALUES (?, ?, ?, ?)
            ''', (product_name, tablet_type_id, packages_per_display, tablets_per_package))
            message = f"Created {product_name}"
        
        conn.commit()
        
        return jsonify({'success': True, 'message': message})
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/delete_product/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    """Delete a product configuration"""
    conn = None
    try:
        conn = get_db()
        
        # Get product name first
        product = conn.execute('SELECT product_name FROM product_details WHERE id = ?', (product_id,)).fetchone()
        if not product:
            return jsonify({'success': False, 'error': 'Product not found'}), 404
        
        conn.execute('DELETE FROM product_details WHERE id = ?', (product_id,))
        conn.commit()
        
        return jsonify({'success': True, 'message': f"Deleted {product['product_name']}"})
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/get_or_create_tablet_type', methods=['POST'])
def get_or_create_tablet_type():
    """Get existing tablet type by name or create new one"""
    conn = None
    try:
        data = request.get_json()
        tablet_type_name = data.get('tablet_type_name', '').strip()
        
        if not tablet_type_name:
            return jsonify({'success': False, 'error': 'Tablet type name required'}), 400
        
        conn = get_db()
        
        # Check if exists
        existing = conn.execute(
            'SELECT id FROM tablet_types WHERE tablet_type_name = ?', 
            (tablet_type_name,)
        ).fetchone()
        
        if existing:
            tablet_type_id = existing['id']
        else:
            # Create new
            cursor = conn.execute(
                'INSERT INTO tablet_types (tablet_type_name) VALUES (?)',
                (tablet_type_name,)
            )
            tablet_type_id = cursor.lastrowid
            conn.commit()
        
        return jsonify({'success': True, 'tablet_type_id': tablet_type_id})
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/update_tablet_inventory_ids', methods=['POST'])
def update_tablet_inventory_ids():
    """Update tablet types with inventory item IDs from PO line items"""
    conn = None
    try:
        conn = get_db()
        
        # Get all tablet types without inventory_item_id
        tablet_types = conn.execute('''
            SELECT id, tablet_type_name 
            FROM tablet_types 
            WHERE inventory_item_id IS NULL OR inventory_item_id = ''
        ''').fetchall()
        
        updated_count = 0
        
        for tablet_type in tablet_types:
            print(f"Processing tablet type: {tablet_type['tablet_type_name']}")
            
            # Look for PO lines that contain this tablet type name
            matching_lines = conn.execute('''
                SELECT DISTINCT inventory_item_id, line_item_name
                FROM po_lines 
                WHERE line_item_name LIKE ? OR line_item_name LIKE ?
                LIMIT 1
            ''', (f'%{tablet_type["tablet_type_name"]}%', 
                  f'%{tablet_type["tablet_type_name"].replace(" ", "%")}%')).fetchone()
            
            if matching_lines:
                print(f"Found matching line: {matching_lines['line_item_name']} -> {matching_lines['inventory_item_id']}")
                
                # Check if this inventory_item_id is already used by another tablet type
                existing = conn.execute('''
                    SELECT tablet_type_name FROM tablet_types 
                    WHERE inventory_item_id = ? AND id != ?
                ''', (matching_lines['inventory_item_id'], tablet_type['id'])).fetchone()
                
                if existing:
                    print(f"Inventory ID {matching_lines['inventory_item_id']} already used by {existing['tablet_type_name']}, skipping {tablet_type['tablet_type_name']}")
                else:
                    conn.execute('''
                        UPDATE tablet_types 
                        SET inventory_item_id = ?
                        WHERE id = ?
                    ''', (matching_lines['inventory_item_id'], tablet_type['id']))
                    updated_count += 1
            else:
                print(f"No matching line found for: {tablet_type['tablet_type_name']}")
        
        conn.commit()
        
        return jsonify({
            'success': True, 
            'message': f'Updated {updated_count} tablet types with inventory item IDs'
        })
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/tablet_types/categories', methods=['GET'])
def get_tablet_type_categories():
    """Get all tablet types grouped by their configured categories"""
    conn = None
    try:
        conn = get_db()
        conn.row_factory = sqlite3.Row
        
        # Get all tablet types with their categories (already sorted alphabetically)
        tablet_types = conn.execute('''
            SELECT id, tablet_type_name, category 
            FROM tablet_types 
            ORDER BY tablet_type_name
        ''').fetchall()
        
        # Group by category (products will maintain alphabetical order)
        categories = {}
        unassigned = []
        
        for tt in tablet_types:
            category = tt['category'] if tt['category'] else None
            if not category:
                unassigned.append({
                    'id': tt['id'],
                    'name': tt['tablet_type_name']
                })
            else:
                if category not in categories:
                    categories[category] = []
                categories[category].append({
                    'id': tt['id'],
                    'name': tt['tablet_type_name']
                })
        
        # Add unassigned to Other if it exists (already alphabetically sorted)
        if unassigned:
            if 'Other' not in categories:
                categories['Other'] = []
            categories['Other'].extend(unassigned)
        
        # Sort categories alphabetically
        category_order = sorted(categories.keys())
        
        return jsonify({
            'success': True,
            'categories': categories,
            'category_order': category_order
        })
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/tablet_type/category', methods=['POST'])
@admin_required
def update_tablet_type_category():
    """Update category for a tablet type"""
    conn = None
    try:
        data = request.get_json()
        tablet_type_id = data.get('tablet_type_id')
        category = data.get('category')  # Can be None to remove category
        
        if not tablet_type_id:
            return jsonify({'success': False, 'error': 'Tablet type ID required'}), 400
        
        conn = get_db()
        
        # Update category
        conn.execute('''
            UPDATE tablet_types 
            SET category = ?
            WHERE id = ?
        ''', (category, tablet_type_id))
        
        conn.commit()
        
        return jsonify({'success': True, 'message': 'Category updated successfully'})
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/tablet_types', methods=['GET'])
@role_required('dashboard')
def get_tablet_types():
    """Get all tablet types/products for dropdowns"""
    conn = None
    try:
        conn = get_db()
        
        # Get all tablet types
        tablet_types = conn.execute('''
            SELECT id, tablet_type_name, inventory_item_id, category
            FROM tablet_types 
            ORDER BY tablet_type_name
        ''').fetchall()
        
        return jsonify({
            'success': True,
            'tablet_types': [dict(row) for row in tablet_types]
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


@bp.route('/api/categories', methods=['GET'])
@admin_required
def get_categories():
    """Get all unique categories"""
    conn = None
    try:
        conn = get_db()
        
        # Get unique categories from tablet_types
        categories = conn.execute('''
            SELECT DISTINCT category 
            FROM tablet_types 
            WHERE category IS NOT NULL AND category != ''
            ORDER BY category
        ''').fetchall()
        
        category_list = [cat['category'] for cat in categories] if categories else []
        
        # Get deleted categories from app_settings
        deleted_categories_set = set()
        try:
            deleted_categories_json = conn.execute('''
                SELECT setting_value FROM app_settings WHERE setting_key = 'deleted_categories'
            ''').fetchone()
            if deleted_categories_json and deleted_categories_json['setting_value']:
                try:
                    deleted_categories_set = set(json.loads(deleted_categories_json['setting_value']))
                except (json.JSONDecodeError, ValueError, TypeError):
                    deleted_categories_set = set()
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except:
                    pass
            print(f"Warning: Could not load deleted categories: {e}")
            # Continue without filtering if there's an error
        
        # Get category order from app_settings (or use alphabetical as fallback)
        try:
            category_order_json = conn.execute('''
                SELECT setting_value FROM app_settings WHERE setting_key = 'category_order'
            ''').fetchone()
            if category_order_json and category_order_json['setting_value']:
                try:
                    preferred_order = json.loads(category_order_json['setting_value'])
                except (json.JSONDecodeError, ValueError, TypeError):
                    preferred_order = sorted(category_list)
            else:
                # No saved order - use alphabetical
                preferred_order = sorted(category_list)
        except Exception as e:
            print(f"Warning: Could not load category order: {e}")
            preferred_order = sorted(category_list)
        
        # Filter out deleted categories
        all_categories = [cat for cat in category_list if cat not in deleted_categories_set]
        
        # Sort by preferred order (categories not in preferred_order go at the end alphabetically)
        all_categories.sort(key=lambda x: (preferred_order.index(x) if x in preferred_order else len(preferred_order) + 1, x))
        
        return jsonify({'success': True, 'categories': all_categories})
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/categories', methods=['POST'])
@admin_required
def add_category():
    """Add a new category"""
    conn = None
    try:
        data = request.get_json()
        category_name = data.get('category_name', '').strip()
        
        if not category_name:
            return jsonify({'success': False, 'error': 'Category name required'}), 400
        
        conn = get_db()
        conn.row_factory = sqlite3.Row
        
        # Check if category already exists
        existing = conn.execute('''
            SELECT DISTINCT category 
            FROM tablet_types 
            WHERE category = ?
        ''', (category_name,)).fetchone()
        
        if existing:
            if conn:
                try:
                    conn.close()
                except:
                    pass
            return jsonify({'success': False, 'error': 'Category already exists'}), 400
        
        # Categories are created when tablet types are assigned to them
        # This endpoint just validates the name - actual creation happens when assigning
        if conn:
            try:
                conn.close()
            except:
                pass
        
        return jsonify({
            'success': True, 
            'message': f'Category "{category_name}" is ready. Assign tablet types to make it active.'
        })
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        import traceback
        traceback.print_exc()
        if conn:
            try:
                conn.close()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500



@bp.route('/api/categories/rename', methods=['POST'])
@admin_required
def rename_category():
    """Rename a category (updates all tablet types with that category)"""
    conn = None
    try:
        data = request.get_json()
        old_name = data.get('old_name', '').strip()
        new_name = data.get('new_name', '').strip()
        
        if not old_name or not new_name:
            return jsonify({'success': False, 'error': 'Both old and new category names required'}), 400
        
        if old_name == new_name:
            return jsonify({'success': False, 'error': 'New name must be different from old name'}), 400
        
        conn = get_db()
        conn.row_factory = sqlite3.Row
        
        # Check if new name already exists
        existing = conn.execute('''
            SELECT DISTINCT category 
            FROM tablet_types 
            WHERE category = ?
        ''', (new_name,)).fetchone()
        
        if existing:
            if conn:
                try:
                    conn.close()
                except:
                    pass
            return jsonify({'success': False, 'error': 'Category name already exists'}), 400
        
        # Check if old category exists and get count
        old_exists = conn.execute('''
            SELECT COUNT(*) as count
            FROM tablet_types 
            WHERE category = ?
        ''', (old_name,)).fetchone()
        
        if old_exists['count'] == 0:
            if conn:
                try:
                    conn.close()
                except:
                    pass
            return jsonify({'success': False, 'error': f'Category "{old_name}" not found or has no tablet types assigned'}), 404
        
        # Update all tablet types with the old category name
        cursor = conn.execute('''
            UPDATE tablet_types 
            SET category = ?
            WHERE category = ?
        ''', (new_name, old_name))
        
        rows_updated = cursor.rowcount
        
        # Verify the update worked
        verify_update = conn.execute('''
            SELECT COUNT(*) as count
            FROM tablet_types 
            WHERE category = ?
        ''', (new_name,)).fetchone()
        
        if verify_update['count'] != old_exists['count']:
            conn.rollback()
            if conn:
                try:
                    conn.close()
                except:
                    pass
            return jsonify({'success': False, 'error': 'Failed to update all tablet types. Transaction rolled back.'}), 500
        
        conn.commit()
        
        if conn:
            try:
                conn.close()
            except:
                pass
        
        return jsonify({
            'success': True, 
            'message': f'Category renamed from "{old_name}" to "{new_name}" ({rows_updated} tablet types updated)'
        })
    except Exception as e:
        if conn:
            try:
                conn.close()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500



@bp.route('/api/categories/delete', methods=['POST'])
@admin_required
def delete_category():
    """Delete a category (removes category from all tablet types)"""
    conn = None
    try:
        data = request.get_json()
        category_name = data.get('category_name', '').strip()
        
        if not category_name:
            return jsonify({'success': False, 'error': 'Category name required'}), 400
        
        conn = get_db()
        conn.row_factory = sqlite3.Row
        
        # Check if category exists and get count
        category_exists = conn.execute('''
            SELECT COUNT(*) as count
            FROM tablet_types 
            WHERE category = ?
        ''', (category_name,)).fetchone()
        
        rows_updated = 0
        
        # Only try to update if there are tablet types with this category
        if category_exists['count'] > 0:
            # Remove category from all tablet types (set to NULL)
            cursor = conn.execute('''
                UPDATE tablet_types 
                SET category = NULL
                WHERE category = ?
            ''', (category_name,))
            
            rows_updated = cursor.rowcount
            
            # Verify the update worked
            verify_delete = conn.execute('''
                SELECT COUNT(*) as count
                FROM tablet_types 
                WHERE category = ?
            ''', (category_name,)).fetchone()
            
            if verify_delete['count'] != 0:
                conn.rollback()
                if conn:
                    try:
                        conn.close()
                    except:
                        pass
                return jsonify({'success': False, 'error': 'Failed to delete category. Transaction rolled back.'}), 500
        
        # Commit even if no rows were updated (category was empty)
        conn.commit()
        
        # Track deleted category in app_settings so it doesn't reappear
        try:
            # Get current deleted categories using correct column names
            deleted_categories_json = conn.execute('''
                SELECT setting_value FROM app_settings WHERE setting_key = 'deleted_categories'
            ''').fetchone()
            
            deleted_categories = set()
            if deleted_categories_json and deleted_categories_json['setting_value']:
                try:
                    deleted_categories = set(json.loads(deleted_categories_json['setting_value']))
                except (json.JSONDecodeError, ValueError, TypeError):
                    deleted_categories = set()
            
            # Add this category to deleted set
            deleted_categories.add(category_name)
            
            # Save back to app_settings using correct column names
            conn.execute('''
                INSERT OR REPLACE INTO app_settings (setting_key, setting_value, description) 
                VALUES (?, ?, ?)
            ''', ('deleted_categories', json.dumps(list(deleted_categories)), 'List of deleted categories that should not appear'))
            
            conn.commit()
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except:
                    pass
            import traceback
            traceback.print_exc()
            print(f"Warning: Could not track deleted category: {e}")
            # Don't fail the request if tracking fails, but log the error
        
        if conn:
            try:
                conn.close()
            except:
                pass
        
        return jsonify({
            'success': True, 
            'message': f'Category "{category_name}" deleted. {rows_updated} tablet type(s) have been unassigned.'
        })
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        import traceback
        traceback.print_exc()
        if conn:
            try:
                conn.close()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500



@bp.route('/api/add_tablet_type', methods=['POST'])
@admin_required
def add_tablet_type():
    """Add a new tablet type"""
    conn = None
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Invalid JSON data'}), 400
            
        tablet_type_name = (data.get('tablet_type_name') or '').strip()
        inventory_item_id = (data.get('inventory_item_id') or '').strip()
        
        if not tablet_type_name:
            return jsonify({'success': False, 'error': 'Tablet type name required'}), 400
            
        conn = get_db()
        
        # Check if tablet type already exists
        existing = conn.execute(
            'SELECT id FROM tablet_types WHERE tablet_type_name = ?', 
            (tablet_type_name,)
        ).fetchone()
        
        if existing:
            return jsonify({'success': False, 'error': 'Tablet type already exists'}), 400
        
        # Check if inventory_item_id is already used (if provided)
        if inventory_item_id:
            existing_id = conn.execute(
                'SELECT tablet_type_name FROM tablet_types WHERE inventory_item_id = ?',
                (inventory_item_id,)
            ).fetchone()
            
            if existing_id:
                return jsonify({
                    'success': False, 
                    'error': f'Inventory ID already used by {existing_id["tablet_type_name"]}'
                }), 400
        
        # Insert new tablet type
        conn.execute('''
            INSERT INTO tablet_types (tablet_type_name, inventory_item_id)
            VALUES (?, ?)
        ''', (tablet_type_name, inventory_item_id if inventory_item_id else None))
        
        conn.commit()
        
        return jsonify({'success': True, 'message': f'Added tablet type: {tablet_type_name}'})
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/delete_tablet_type/<int:tablet_type_id>', methods=['DELETE'])
@admin_required
def delete_tablet_type(tablet_type_id):
    """Delete a tablet type and its associated products"""
    conn = None
    try:
        conn = get_db()
        
        # Get tablet type name first
        tablet_type = conn.execute(
            'SELECT tablet_type_name FROM tablet_types WHERE id = ?', 
            (tablet_type_id,)
        ).fetchone()
        
        if not tablet_type:
            return jsonify({'success': False, 'error': 'Tablet type not found'}), 404
        
        # Delete associated products first
        conn.execute('DELETE FROM product_details WHERE tablet_type_id = ?', (tablet_type_id,))
        
        # Delete tablet type
        conn.execute('DELETE FROM tablet_types WHERE id = ?', (tablet_type_id,))
        
        conn.commit()
        
        return jsonify({'success': True, 'message': f'Deleted {tablet_type["tablet_type_name"]} and its products'})
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

# Employee Management Routes for Admin
# Note: /admin/employees route is in admin.py blueprint, not here

@bp.route('/api/add_employee', methods=['POST'])
def add_employee():
    """Add a new employee"""
    conn = None
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        full_name = data.get('full_name', '').strip()
        password = data.get('password', '').strip()
        role = data.get('role', 'warehouse_staff').strip()
        
        if not username or not full_name or not password:
            return jsonify({'success': False, 'error': 'Username, full name, and password required'}), 400
            
        # Validate role
        valid_roles = ['warehouse_staff', 'manager', 'admin']
        if role not in valid_roles:
            return jsonify({'success': False, 'error': 'Invalid role specified'}), 400
            
        conn = get_db()
        
        # Check if username already exists
        existing = conn.execute(
            'SELECT id FROM employees WHERE username = ?', 
            (username,)
        ).fetchone()
        
        if existing:
            return jsonify({'success': False, 'error': 'Username already exists'}), 400
        
        # Hash password and insert employee
        password_hash = hash_password(password)
        conn.execute('''
            INSERT INTO employees (username, full_name, password_hash, role)
            VALUES (?, ?, ?, ?)
        ''', (username, full_name, password_hash, role))
        
        conn.commit()
        return jsonify({'success': True, 'message': f'Added employee: {full_name}'})
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/update_employee_role/<int:employee_id>', methods=['POST'])
@admin_required
def update_employee_role(employee_id):
    """Update an employee's role"""
    conn = None
    try:
        data = request.get_json()
        new_role = data.get('role', '').strip()
        
        # Validate role
        valid_roles = ['warehouse_staff', 'manager', 'admin']
        if new_role not in valid_roles:
            return jsonify({'success': False, 'error': 'Invalid role specified'}), 400
            
        conn = get_db()
        
        # Check if employee exists
        employee = conn.execute(
            'SELECT id, username, full_name FROM employees WHERE id = ?', 
            (employee_id,)
        ).fetchone()
        
        if not employee:
            return jsonify({'success': False, 'error': 'Employee not found'}), 404
            
        # Update employee role
        conn.execute('''
            UPDATE employees 
            SET role = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (new_role, employee_id))
        
        conn.commit()
        
        return jsonify({
            'success': True, 
            'message': f'Updated {employee["full_name"]} role to {new_role.replace("_", " ").title()}'
        })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/toggle_employee/<int:employee_id>', methods=['POST'])
def toggle_employee(employee_id):
    """Toggle employee active status"""
    conn = None
    try:
        conn = get_db()
        
        # Get current status
        employee = conn.execute(
            'SELECT full_name, is_active FROM employees WHERE id = ?', 
            (employee_id,)
        ).fetchone()
        
        if not employee:
            return jsonify({'success': False, 'error': 'Employee not found'}), 404
        
        # Toggle status
        new_status = not employee['is_active']
        conn.execute('''
            UPDATE employees 
            SET is_active = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (new_status, employee_id))
        
        conn.commit()
        
        status_text = 'activated' if new_status else 'deactivated'
        return jsonify({'success': True, 'message': f'{employee["full_name"]} {status_text}'})
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/delete_employee/<int:employee_id>', methods=['DELETE'])
def delete_employee(employee_id):
    """Delete an employee"""
    conn = None
    try:
        conn = get_db()
        
        # Get employee name first
        employee = conn.execute(
            'SELECT full_name FROM employees WHERE id = ?', 
            (employee_id,)
        ).fetchone()
        
        if not employee:
            return jsonify({'success': False, 'error': 'Employee not found'}), 404
        
        # Delete employee
        conn.execute('DELETE FROM employees WHERE id = ?', (employee_id,))
        
        conn.commit()
        
        return jsonify({'success': True, 'message': f'Deleted employee: {employee["full_name"]}'})
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/set-language', methods=['POST'])
def set_language():
    """Set language preference for current session and save to employee profile"""
    try:
        data = request.get_json()
        language = data.get('language', '').strip()
        
        # Validate language
        if language not in current_app.config['LANGUAGES']:
            return jsonify({'success': False, 'error': 'Invalid language'}), 400
        
        # Set session language with manual override flag
        session['language'] = language
        session['manual_language_override'] = True
        session.permanent = True
        
        # Save to employee profile if authenticated
        if session.get('employee_authenticated') and session.get('employee_id'):
            try:
                conn = get_db()
                conn.execute('''
                    UPDATE employees 
                    SET preferred_language = ? 
                    WHERE id = ?
                ''', (language, session.get('employee_id')))
                conn.commit()
                conn.close()
                current_app.logger.info(f"Language preference saved to database: {language} for employee {session.get('employee_id')}")
            except Exception as e:
                current_app.logger.error(f"Failed to save language preference to database: {str(e)}")
                # Continue without database save - session is still set
        
        current_app.logger.info(f"Language manually set to {language} for session")
        
        return jsonify({'success': True, 'message': f'Language set to {language}'})
        
    except Exception as e:
        current_app.logger.error(f"Language setting error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500



@bp.route('/api/refresh_products', methods=['POST'])
def refresh_products():
    """Clear and rebuild products with updated configuration"""
    try:
        from setup_db import setup_sample_data
        
        conn = get_db()
        
        # Clear existing data
        conn.execute('DELETE FROM warehouse_submissions')
        conn.execute('DELETE FROM product_details')
        conn.execute('DELETE FROM tablet_types')
        conn.commit()
        conn.close()
        
        # Rebuild with new data
        setup_sample_data()
        
        return jsonify({
            'success': True, 
            'message': 'Products refreshed with updated configuration'
        })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500



@bp.route('/api/po_tracking/<int:po_id>')
def get_po_tracking(po_id):
    """Get all tracking information for a PO (supports multiple shipments)"""
    try:
        conn = get_db()
        
        # Get all shipments for this PO
        shipments = conn.execute('''
            SELECT id, tracking_number, carrier, shipped_date, estimated_delivery, actual_delivery, notes, created_at
            FROM shipments 
            WHERE po_id = ?
            ORDER BY created_at DESC
        ''', (po_id,)).fetchall()
        
        conn.close()
        
        if shipments:
            # Return all shipments
            shipments_list = []
            for shipment in shipments:
                shipments_list.append({
                    'id': shipment['id'],
                    'tracking_number': shipment['tracking_number'],
                    'carrier': shipment['carrier'],
                    'shipped_date': shipment['shipped_date'],
                    'estimated_delivery': shipment['estimated_delivery'],
                    'actual_delivery': shipment['actual_delivery'],
                    'notes': shipment['notes']
                })
            
            return jsonify({
                'shipments': shipments_list,
                'has_tracking': True
            })
        else:
            return jsonify({
                'shipments': [],
                'has_tracking': False
            })
            
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'error': str(e)}), 500



@bp.route('/api/find_org_id')
def find_organization_id():
    """Help find the correct Zoho Organization ID"""
    try:
        # Get token first
        token = zoho_api.get_access_token()
        if not token:
            return jsonify({
                'success': False,
                'error': 'Failed to get access token. Check your credentials.'
            })
        
        # Try to get organizations
        url = 'https://www.zohoapis.com/inventory/v1/organizations'
        headers = {'Authorization': f'Zoho-oauthtoken {token}'}
        
        response = requests.get(url, headers=headers)
        print(f"Organizations API - Status: {response.status_code}")
        print(f"Organizations API - Response: {response.text}")
        
        if response.status_code == 200:
            data = response.json()
            orgs = data.get('organizations', [])
            return jsonify({
                'success': True,
                'organizations': orgs,
                'message': f'Found {len(orgs)} organizations. Use the organization_id from the one you want.'
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Failed to get organizations: {response.status_code} - {response.text}'
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error finding organizations: {str(e)}'
        })



@bp.route('/api/test_zoho_connection')
def test_zoho_connection():
    """Test if Zoho API credentials are working"""
    try:
        # Try to get an access token
        token = zoho_api.get_access_token()
        if not token:
            return jsonify({
                'success': False,
                'error': 'Failed to get access token. Check your CLIENT_ID, CLIENT_SECRET, and REFRESH_TOKEN in .env file'
            })
        
        # Try to make a simple API call
        result = zoho_api.make_request('items', method='GET', extra_params={'per_page': 10})
        if result:
            item_count = len(result.get('items', []))
            return jsonify({
                'success': True,
                'message': f'✅ Connected to Zoho! Found {item_count} inventory items.',
                'organization_id': zoho_api.organization_id
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Got access token but API call failed. Check your ORGANIZATION_ID or check the terminal for detailed error info.'
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Connection test failed: {str(e)}'
        })



@bp.route('/api/clear_po_data', methods=['POST'])
@admin_required
def clear_po_data():
    """Clear all PO data for fresh sync testing"""
    conn = None
    try:
        conn = get_db()
        
        # Clear all PO-related data
        conn.execute('DELETE FROM po_lines')
        conn.execute('DELETE FROM purchase_orders WHERE zoho_po_id IS NOT NULL')  # Keep sample test POs
        conn.execute('DELETE FROM warehouse_submissions')
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': '✅ Cleared all synced PO data. Ready for fresh sync!'
        })
        
    except Exception as e:
        if conn:
            try:
                conn.close()
            except:
                pass
        return jsonify({
            'success': False,
            'error': f'Clear failed: {str(e)}'
        }), 500

# ===== PRODUCTION REPORT ENDPOINTS =====



@bp.route('/api/reports/production', methods=['POST'])
@role_required('dashboard')
def generate_production_report():
    """Generate comprehensive production report PDF"""
    # Note: This function does NOT use database connections directly.
    # ProductionReportGenerator handles its own connections internally.
    try:
        data = request.get_json() or {}
        
        start_date = data.get('start_date')
        end_date = data.get('end_date') 
        po_numbers = data.get('po_numbers', [])
        tablet_type_id = data.get('tablet_type_id')
        report_type = data.get('report_type', 'production')  # 'production', 'vendor', or 'receive'
        receive_id = data.get('receive_id')
        
        # Validate date formats if provided
        if start_date:
            try:
                datetime.strptime(start_date, '%Y-%m-%d')
            except ValueError:
                return jsonify({'error': 'Invalid start_date format. Use YYYY-MM-DD'}), 400
        
        if end_date:
            try:
                datetime.strptime(end_date, '%Y-%m-%d')
            except ValueError:
                return jsonify({'error': 'Invalid end_date format. Use YYYY-MM-DD'}), 400
        
        # Generate report
        generator = ProductionReportGenerator(db_path=Config.DATABASE_PATH)
        
        if report_type == 'vendor':
            pdf_content = generator.generate_vendor_report(
                start_date=start_date,
                end_date=end_date,
                po_numbers=po_numbers if po_numbers else None,
                tablet_type_id=tablet_type_id
            )
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'vendor_report_{timestamp}.pdf'
        elif report_type == 'receive':
            if not receive_id:
                return jsonify({'error': 'Receive ID is required for receive reports'}), 400
            pdf_content = generator.generate_receive_report(receive_id=receive_id)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'receive_report_{timestamp}.pdf'
        else:
            pdf_content = generator.generate_production_report(
                start_date=start_date,
                end_date=end_date,
                po_numbers=po_numbers if po_numbers else None,
                tablet_type_id=tablet_type_id
            )
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'production_report_{timestamp}.pdf'
        
        # Return PDF as download
        from flask import make_response
        response = make_response(pdf_content)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Report generation error: {str(e)}")
        print(error_trace)
        return jsonify({
            'success': False,
            'error': f'Report generation failed: {str(e)}'
        }), 500



@bp.route('/api/reports/po-summary')
@role_required('dashboard')
def get_po_summary_for_reports():
    """Get summary of POs available for reporting"""
    conn = None
    try:
        conn = get_db()
        
        # First, verify the table exists and has data
        po_count_row = conn.execute('SELECT COUNT(*) as count FROM purchase_orders').fetchone()
        po_count = dict(po_count_row) if po_count_row else {'count': 0}
        if not po_count or po_count.get('count', 0) == 0:
            conn.close()
            return jsonify({
                'success': True,
                'pos': [],
                'total_count': 0,
                'message': 'No purchase orders found'
            })
        
        # Simplified query for dropdown - use subqueries instead of GROUP BY with JOINs
        # This avoids expensive JOIN operations and is much faster
        query = '''
            SELECT 
                po.id,
                po.po_number,
                po.tablet_type,
                COALESCE(po.internal_status, 'Active') as internal_status,
                COALESCE(po.ordered_quantity, 0) as ordered_quantity,
                COALESCE(po.current_good_count, 0) as current_good_count,
                COALESCE(po.current_damaged_count, 0) as current_damaged_count,
                po.created_at,
                po.updated_at,
                (SELECT COUNT(*) FROM warehouse_submissions WHERE assigned_po_id = po.id) as submission_count,
                (SELECT MAX(created_at) FROM warehouse_submissions WHERE assigned_po_id = po.id) as last_submission,
                (SELECT MAX(actual_delivery) FROM shipments WHERE po_id = po.id) as actual_delivery,
                (SELECT MAX(delivered_at) FROM shipments WHERE po_id = po.id) as delivered_at,
                (SELECT MAX(tracking_status) FROM shipments WHERE po_id = po.id) as tracking_status
            FROM purchase_orders po
            WHERE po.po_number IS NOT NULL
            ORDER BY po.created_at DESC
            LIMIT 100
        '''
        pos = conn.execute(query).fetchall()
        
        # Convert to list of dicts efficiently - calculate pack_time only if dates exist
        po_list = []
        for po_row in pos:
            po = dict(po_row)
            
            # Calculate pack time if both dates exist (simplified)
            pack_time = None
            delivery_date = po.get('actual_delivery') or po.get('delivered_at')
            completion_date = po.get('last_submission') or (po.get('updated_at')[:10] if po.get('internal_status') == 'Complete' and po.get('updated_at') else None)
            
            if delivery_date and completion_date:
                try:
                    del_dt = datetime.strptime(str(delivery_date)[:10], '%Y-%m-%d')
                    comp_dt = datetime.strptime(str(completion_date)[:10], '%Y-%m-%d')
                    pack_time = (comp_dt - del_dt).days
                except (ValueError, TypeError):
                    pack_time = None
            
            po_list.append({
                'po_number': po.get('po_number') or 'N/A',
                'tablet_type': po.get('tablet_type') or 'N/A',
                'status': po.get('internal_status') or 'Active',
                'ordered': int(po.get('ordered_quantity') or 0),
                'produced': int(po.get('current_good_count') or 0),
                'damaged': int(po.get('current_damaged_count') or 0),
                'created_date': str(po['created_at'])[:10] if po.get('created_at') else None,
                'submissions': int(po.get('submission_count') or 0),
                'pack_time_days': pack_time,
                'tracking_status': po.get('tracking_status')
            })
        
        return jsonify({
            'success': True,
            'pos': po_list,
            'total_count': len(po_list)
        })
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error in get_po_summary_for_reports: {e}")
        print(error_trace)
        return jsonify({
            'success': False,
            'error': f'Failed to get PO summary: {str(e)}',
            'trace': error_trace
        }), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

# ===== RECEIVING MANAGEMENT ROUTES =====

# Temporarily removed force-reload route due to import issues

@bp.route('/debug/server-info')
def server_debug_info():
    """Debug route to check server state - no auth required"""
    import os
    import time
    import sqlite3
    
    try:
        # Check file timestamps
        app_py_time = os.path.getmtime('app.py')
        version_time = os.path.getmtime('__version__.py')
        
        # Check if we can read version
        try:
            from __version__ import __version__, __title__
            version_info = f"{__title__} v{__version__}"
        except:
            version_info = "Version import failed"
        
        # Check current working directory
        cwd = os.getcwd()
        
        # Check if template exists (using absolute path)
        template_path = os.path.join(current_app.root_path, '..', 'templates', 'receiving_management.html')
        template_path = os.path.abspath(template_path)
        template_exists = os.path.exists(template_path)
        
        # Find database path and check what tables exist (use Config.DATABASE_PATH)
        db_path = Config.DATABASE_PATH
        db_full_path = os.path.abspath(db_path)
        db_exists = os.path.exists(db_path)
        
        # Check what tables actually exist in this database
        tables_info = "Database not accessible"
        if db_exists:
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cursor.fetchall()]
                tables_info = f"Tables: {tables}"
                conn.close()
            except Exception as e:
                tables_info = f"Database error: {e}"
        
        return f"""
        <h2>Server Debug Info</h2>
        <p><strong>Version:</strong> {version_info}</p>
        <p><strong>Working Directory:</strong> {cwd}</p>
        <p><strong>App.py Modified:</strong> {time.ctime(app_py_time)}</p>
        <p><strong>Version.py Modified:</strong> {time.ctime(version_time)}</p>
        <p><strong>Receiving Template Exists:</strong> {template_exists}</p>
        <p><strong>Python Path:</strong> {os.sys.path[0]}</p>
        <hr>
        <p><strong>Database Path:</strong> {db_full_path}</p>
        <p><strong>Database Exists:</strong> {db_exists}</p>
        <p><strong>{tables_info}</strong></p>
        <hr>
        <p><a href="/receiving">Test Receiving Route</a></p>
        <p><a href="/receiving/debug">Test Debug Route</a></p>
        """
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return f"<h2>Server Debug Error</h2><p>{str(e)}</p>"

@bp.route('/receiving/debug')
@admin_required
def receiving_debug():
    """Debug route to test receiving functionality"""
    conn = None
    try:
        conn = get_db()
        
        # Test database connections
        po_count = conn.execute('SELECT COUNT(*) as count FROM purchase_orders').fetchone()
        shipment_count = conn.execute('SELECT COUNT(*) as count FROM shipments').fetchone()
        receiving_count = conn.execute('SELECT COUNT(*) as count FROM receiving').fetchone()
        
        # Test the actual query
        pending_shipments = conn.execute('''
            SELECT s.*, po.po_number
            FROM shipments s
            JOIN purchase_orders po ON s.po_id = po.id
            LEFT JOIN receiving r ON s.id = r.shipment_id
            WHERE s.tracking_status = 'Delivered' AND r.id IS NULL
            ORDER BY s.delivered_at DESC, s.created_at DESC
        ''').fetchall()
        
        debug_info = {
            'status': 'success',
            'database_counts': {
                'purchase_orders': po_count['count'] if po_count else 0,
                'shipments': shipment_count['count'] if shipment_count else 0,
                'receiving': receiving_count['count'] if receiving_count else 0
            },
            'pending_shipments': len(pending_shipments),
            'template_exists': 'receiving_management.html exists',
            'version': '1.7.1'
        }
        
        return f"""
        <h2>Receiving Debug Info (v1.7.1)</h2>
        <pre>{debug_info}</pre>
        <p><a href="/receiving">Go to actual receiving page</a></p>
        """
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return f"""
        <h2>Receiving Debug Error</h2>
        <p>Error: {str(e)}</p>
        <p><a href="/receiving">Try receiving page anyway</a></p>
        """
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@bp.route('/receiving')
@admin_required  
def receiving_management_v2():
    """Receiving management page - REBUILT VERSION"""
    conn = None
    try:
        conn = get_db()
        
        # Simple query first - just check if we can access receiving table
        try:
            test_query = conn.execute('SELECT COUNT(*) as count FROM receiving').fetchone()
            receiving_count = test_query['count'] if test_query else 0
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except:
                    pass
            return f"""
            <h2>Database Error (v1.7.6 REBUILT)</h2>
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
        if conn:
            try:
                conn.rollback()
            except:
                pass
        # If template fails, return simple HTML with version
        return f"""
        <h2>Receiving Page Error (v1.7.6 REBUILT)</h2>
        <p>Template error: {str(e)}</p>
        <p><a href="/receiving/debug">View debug info</a></p>
        <p><a href="/debug/server-info">Check Server Info</a></p>
        <p><a href="/admin">Back to admin</a></p>
        """
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

@bp.route('/receiving/<int:receiving_id>')
@admin_required
def receiving_details(receiving_id):
    """View detailed information about a specific receiving record"""
    conn = None
    try:
        conn = get_db()
        
        # Get receiving record with PO and shipment info
        receiving = conn.execute('''
            SELECT r.*, po.po_number, s.tracking_number, s.carrier
            FROM receiving r
            JOIN purchase_orders po ON r.po_id = po.id
            LEFT JOIN shipments s ON r.shipment_id = s.id
            WHERE r.id = ?
        ''', (receiving_id,)).fetchone()
        
        if not receiving:
            flash('Receiving record not found', 'error')
            return redirect(url_for('receiving_management_v2'))
        
        # Get box and bag details
        boxes = conn.execute('''
            SELECT sb.*, 
                   GROUP_CONCAT(b.bag_number) as bag_numbers, 
                   COUNT(b.id) as bag_count,
                   GROUP_CONCAT('Bag ' || b.bag_number || ': ' || COALESCE(b.pill_count, 'N/A') || ' pills') as pill_counts
            FROM small_boxes sb
            LEFT JOIN bags b ON sb.id = b.small_box_id
            WHERE sb.receiving_id = ?
            GROUP BY sb.id
            ORDER BY sb.box_number
        ''', (receiving_id,)).fetchall()
        
        return render_template('receiving_details.html', 
                             receiving=dict(receiving),
                             boxes=[dict(box) for box in boxes])
                             
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        flash(f'Error loading receiving details: {str(e)}', 'error')
        return redirect(url_for('receiving_management_v2'))
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/receiving/<int:receiving_id>', methods=['DELETE'])
@role_required('shipping')
def delete_receiving(receiving_id):
    """Delete a receiving record with verification"""
    conn = None
    try:
        # Check if user is manager or admin
        user_role = session.get('employee_role')
        if user_role not in ['manager', 'admin']:
            return jsonify({'success': False, 'error': 'Only managers and admins can delete shipments'}), 403
        
        conn = get_db()
        
        # Check if receiving record exists and get info
        receiving = conn.execute('''
            SELECT r.id, r.po_id, po.po_number, r.received_date, r.received_by
            FROM receiving r
            LEFT JOIN purchase_orders po ON r.po_id = po.id
            WHERE r.id = ?
        ''', (receiving_id,)).fetchone()
        
        if not receiving:
            return jsonify({'success': False, 'error': 'Receiving record not found'}), 404
        
        # Delete in correct order due to foreign key constraints
        # 1. Delete bags first
        conn.execute('DELETE FROM bags WHERE small_box_id IN (SELECT id FROM small_boxes WHERE receiving_id = ?)', (receiving_id,))
        
        # 2. Delete small_boxes
        conn.execute('DELETE FROM small_boxes WHERE receiving_id = ?', (receiving_id,))
        
        # 3. Delete receiving record
        conn.execute('DELETE FROM receiving WHERE id = ?', (receiving_id,))
        
        conn.commit()
        
        po_info = receiving['po_number'] if receiving['po_number'] else 'No PO'
        return jsonify({
            'success': True,
            'message': f'Successfully deleted shipment (PO: {po_info})'
        })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': f'Failed to delete receiving record: {str(e)}'}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


@bp.route('/api/receiving/<int:receiving_id>/close', methods=['POST'])
@role_required('dashboard')  # Changed from 'shipping' to 'dashboard' to allow manager/admin access
def close_receiving(receiving_id):
    """Close a receiving record when all bags are physically emptied"""
    conn = None
    try:
        # Check if user is manager or admin
        user_role = session.get('employee_role')
        is_admin = session.get('admin_authenticated')
        if user_role not in ['manager', 'admin'] and not is_admin:
            return jsonify({'success': False, 'error': 'Only managers and admins can close receives'}), 403
        
        conn = get_db()
        
        # Check if receiving record exists
        receiving = conn.execute('''
            SELECT r.id, r.closed, po.po_number
            FROM receiving r
            LEFT JOIN purchase_orders po ON r.po_id = po.id
            WHERE r.id = ?
        ''', (receiving_id,)).fetchone()
        
        if not receiving:
            return jsonify({'success': False, 'error': 'Receiving record not found'}), 404
        
        # Toggle closed status
        new_status = not receiving['closed']
        
        conn.execute('''
            UPDATE receiving 
            SET closed = ?
            WHERE id = ?
        ''', (new_status, receiving_id))
        
        # Also close all bags in this receive when closing
        if new_status:
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
        
        conn.commit()
        
        action = 'closed' if new_status else 'reopened'
        po_info = receiving['po_number'] if receiving['po_number'] else 'Unassigned'
        return jsonify({
            'success': True,
            'closed': new_status,
            'message': f'Successfully {action} receive (PO: {po_info})'
        })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': f'Failed to close receiving: {str(e)}'}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


@bp.route('/api/bag/<int:bag_id>/close', methods=['POST'])
@role_required('dashboard')  # Changed from 'shipping' to 'dashboard' to allow manager/admin access
def close_bag(bag_id):
    """Close a specific bag when it's physically emptied"""
    conn = None
    try:
        # Check if user is manager or admin
        user_role = session.get('employee_role')
        is_admin = session.get('admin_authenticated')
        if user_role not in ['manager', 'admin'] and not is_admin:
            return jsonify({'success': False, 'error': 'Only managers and admins can close bags'}), 403
        
        conn = get_db()
        
        # Check if bag exists
        bag = conn.execute('''
            SELECT b.id, b.status, b.bag_number, sb.box_number, tt.tablet_type_name
            FROM bags b
            JOIN small_boxes sb ON b.small_box_id = sb.id
            JOIN tablet_types tt ON b.tablet_type_id = tt.id
            WHERE b.id = ?
        ''', (bag_id,)).fetchone()
        
        if not bag:
            return jsonify({'success': False, 'error': 'Bag not found'}), 404
        
        # Toggle status between 'Closed' and 'Available'
        current_status = bag['status'] or 'Available'
        new_status = 'Closed' if current_status != 'Closed' else 'Available'
        
        conn.execute('''
            UPDATE bags 
            SET status = ?
            WHERE id = ?
        ''', (new_status, bag_id))
        
        conn.commit()
        
        action = 'closed' if new_status == 'Closed' else 'reopened'
        bag_info = f"{bag['tablet_type_name']} - Box {bag['box_number']}, Bag {bag['bag_number']}"
        return jsonify({
            'success': True,
            'status': new_status,
            'message': f'Successfully {action} bag: {bag_info}'
        })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': f'Failed to close bag: {str(e)}'}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


@bp.route('/api/process_receiving', methods=['POST'])
@admin_required
def process_receiving():
    """Process a new shipment receiving with photos and box/bag tracking"""
    conn = None
    try:
        conn = get_db()
        
        # Get form data with safe type conversion
        shipment_id = request.form.get('shipment_id')
        if not shipment_id:
            return jsonify({'error': 'Shipment ID required'}), 400
        
        # Safe type conversion for total_small_boxes
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
        
        # File upload validation constants
        ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif'}
        MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
        
        def allowed_file(filename):
            return '.' in filename and \
                   filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
        
        if delivery_photo and delivery_photo.filename:
            # Validate file extension
            if not allowed_file(delivery_photo.filename):
                return jsonify({'error': 'Invalid file type. Only JPG, JPEG, PNG, and GIF are allowed.'}), 400
            
            # Check file size
            delivery_photo.seek(0, os.SEEK_END)
            file_size = delivery_photo.tell()
            delivery_photo.seek(0)
            if file_size > MAX_FILE_SIZE:
                return jsonify({'error': f'File too large. Maximum size is {MAX_FILE_SIZE / (1024*1024):.0f}MB'}), 400
            
            # Validate shipment_id is a valid integer
            try:
                shipment_id_int = int(shipment_id)
            except (ValueError, TypeError):
                return jsonify({'error': 'Invalid shipment_id'}), 400
            
            # Sanitize filename
            safe_filename = secure_filename(delivery_photo.filename)
            original_ext = safe_filename.rsplit('.', 1)[1].lower() if '.' in safe_filename else 'jpg'
            
            # Save photo locally
            # Create uploads directory if it doesn't exist (using absolute path)
            upload_dir = os.path.join(current_app.root_path, '..', 'static', 'uploads', 'receiving')
            upload_dir = os.path.abspath(upload_dir)
            
            # Ensure upload directory is within allowed path (prevent path traversal)
            allowed_base = os.path.abspath(os.path.join(current_app.root_path, '..', 'static', 'uploads'))
            if not upload_dir.startswith(allowed_base):
                return jsonify({'error': 'Invalid upload path'}), 400
            
            os.makedirs(upload_dir, exist_ok=True)
            
            # Generate unique filename with validated shipment_id
            filename = f"shipment_{shipment_id_int}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{original_ext}"
            photo_path = os.path.join(upload_dir, filename)
            delivery_photo.save(photo_path)
            
            # TODO: Upload to Zoho (implement after basic workflow is working)
        
        # Calculate receive number for this PO (sequential number per PO)
        receive_number_result = conn.execute('''
            SELECT COUNT(*) + 1 as receive_number
            FROM receiving
            WHERE po_id = ?
        ''', (shipment['po_id'],)).fetchone()
        
        receive_number = receive_number_result['receive_number'] if receive_number_result else 1
        
        # Build receive name: PO-{po_number}-{receive_number}
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
        
        # First, collect all bag data from the form with safe type conversion
        for key in request.form.keys():
            if key.startswith('bag_') and key.endswith('_pill_count'):
                try:
                    # Extract bag number from key like 'bag_3_pill_count'
                    key_parts = key.split('_')
                    if len(key_parts) < 2:
                        continue
                    bag_num = int(key_parts[1])
                    if bag_num not in all_bag_data:
                        all_bag_data[bag_num] = {}
                    
                    # Safe type conversion for pill_count
                    try:
                        all_bag_data[bag_num]['pill_count'] = int(request.form[key])
                    except (ValueError, TypeError):
                        all_bag_data[bag_num]['pill_count'] = 0
                    
                    # Safe type conversion for box number
                    try:
                        all_bag_data[bag_num]['box'] = int(request.form.get(f'bag_{bag_num}_box', 0))
                    except (ValueError, TypeError):
                        all_bag_data[bag_num]['box'] = 0
                    
                    all_bag_data[bag_num]['notes'] = request.form.get(f'bag_{bag_num}_notes', '')
                except (ValueError, TypeError, IndexError):
                    # Skip invalid bag entries
                    continue
        
        # Process boxes and their bags with sequential numbering
        for box_num in range(1, total_small_boxes + 1):
            # Safe type conversion for bags_in_box
            try:
                bags_in_box = int(request.form.get(f'box_{box_num}_bags', 0))
            except (ValueError, TypeError):
                bags_in_box = 0
            
            box_notes = request.form.get(f'box_{box_num}_notes', '')
            
            # Create small box record
            box_cursor = conn.execute('''
                INSERT INTO small_boxes (receiving_id, box_number, total_bags, notes)
                VALUES (?, ?, ?, ?)
            ''', (receiving_id, box_num, bags_in_box, box_notes))
            
            small_box_id = box_cursor.lastrowid
            
            # Create bag records for this box using sequential numbering
            for bag_data_key, bag_data in all_bag_data.items():
                if bag_data['box'] == box_num:
                    conn.execute('''
                        INSERT INTO bags (small_box_id, bag_number, pill_count, status)
                        VALUES (?, ?, ?, 'Available')
                    ''', (small_box_id, bag_data_key, bag_data['pill_count']))
                    total_bags += 1
        
        # Update shipment status to indicate it's been received
        conn.execute('''
            UPDATE shipments SET actual_delivery = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (shipment_id,))
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': f'Successfully received shipment for PO {shipment["po_number"]}. Processed {total_small_boxes} boxes with {total_bags} total bags.',
            'receiving_id': receiving_id
        })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'error': f'Failed to process receiving: {str(e)}'}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/save_receives', methods=['POST'])
@role_required('shipping')
def save_receives():
    """Save received shipment data (boxes and bags)"""
    conn = None
    try:
        data = request.get_json()
        boxes_data = data.get('boxes', [])
        po_id = data.get('po_id')  # Optional PO assignment
        
        if not boxes_data:
            return jsonify({'success': False, 'error': 'No boxes data provided'}), 400
        
        # Only managers and admins can assign POs
        user_role = session.get('employee_role')
        if po_id and user_role not in ['manager', 'admin']:
            return jsonify({'success': False, 'error': 'Only managers and admins can assign POs'}), 403
        
        conn = get_db()
        
        # Ensure tablet_type_id column exists in bags table
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
                print(f"Warning: Could not add tablet_type_id column: {e}")
        
        # Get current user name
        received_by = 'Unknown'
        if session.get('employee_id'):
            employee = conn.execute('SELECT full_name FROM employees WHERE id = ?', (session.get('employee_id'),)).fetchone()
            if employee:
                received_by = employee['full_name']
        elif session.get('admin_authenticated'):
            received_by = 'Admin'
        
        # Create receiving record (with optional PO assignment)
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
            
            # Create small box record
            box_cursor = conn.execute('''
                INSERT INTO small_boxes (receiving_id, box_number, total_bags)
                VALUES (?, ?, ?)
            ''', (receiving_id, box_number, len(bags)))
            
            small_box_id = box_cursor.lastrowid
            
            # Create bag records
            for bag in bags:
                tablet_type_id = bag.get('tablet_type_id')
                bag_count = bag.get('bag_count', 0)
                bag_number = bag.get('bag_number')  # NEW: Use flavor-based bag number from frontend
                
                if not tablet_type_id or not bag_number:
                    continue
                
                conn.execute('''
                    INSERT INTO bags (small_box_id, bag_number, bag_label_count, tablet_type_id, status)
                    VALUES (?, ?, ?, ?, 'Available')
                ''', (small_box_id, bag_number, bag_count, tablet_type_id))
                total_bags += 1
        
        # Update receiving record with total bags
        conn.execute('''
            UPDATE receiving SET total_small_boxes = ?
            WHERE id = ?
        ''', (len(boxes_data), receiving_id))
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': f'Successfully recorded {len(boxes_data)} box(es) with {total_bags} bag(s)',
            'receiving_id': receiving_id
        })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/receiving/<int:receiving_id>/assign_po', methods=['POST'])
@role_required('shipping')
def assign_po_to_receiving(receiving_id):
    """Update PO assignment for a receiving record (managers and admins only)"""
    conn = None
    try:
        user_role = session.get('employee_role')
        if user_role not in ['manager', 'admin']:
            return jsonify({'success': False, 'error': 'Only managers and admins can assign POs'}), 403
        
        data = request.get_json()
        po_id = data.get('po_id')  # Can be None to unassign
        
        conn = get_db()
        
        # Verify receiving record exists
        receiving = conn.execute('SELECT id FROM receiving WHERE id = ?', (receiving_id,)).fetchone()
        if not receiving:
            return jsonify({'success': False, 'error': 'Receiving record not found'}), 404
        
        # Update PO assignment
        conn.execute('''
            UPDATE receiving SET po_id = ?
            WHERE id = ?
        ''', (po_id if po_id else None, receiving_id))
        
        conn.commit()
        
        # Get PO number for response
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
        if conn:
            try:
                conn.rollback()
            except:
                pass
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/available_boxes_bags/<int:po_id>')
@employee_required
def get_available_boxes_bags(po_id):
    """Get available boxes and bags for a PO (for warehouse form dropdowns)"""
    conn = None
    try:
        conn = get_db()
        
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
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass




@bp.route('/api/create_sample_receiving_data', methods=['POST'])
@admin_required  
def create_sample_receiving_data():
    """Create sample PO and shipment data for testing receiving workflow"""
    conn = None
    try:
        from datetime import datetime
        import random
        
        conn = get_db()
        
        # Generate unique PO number
        timestamp = datetime.now().strftime('%m%d-%H%M')
        po_number = f'TEST-{timestamp}'
        
        # Generate unique tracking number
        tracking_suffix = random.randint(100000, 999999)
        tracking_number = f'1Z999AA{tracking_suffix}'
        
        # Create sample PO
        po_cursor = conn.execute('''
            INSERT INTO purchase_orders (po_number, tablet_type, zoho_status, ordered_quantity, internal_status)
            VALUES (?, ?, ?, ?, ?)
        ''', (po_number, 'Test Tablets', 'confirmed', 1000, 'Active'))
        
        po_id = po_cursor.lastrowid
        
        # Create sample shipment with delivered status
        shipment_cursor = conn.execute('''
            INSERT INTO shipments (po_id, tracking_number, carrier, tracking_status, delivered_at, created_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ''', (po_id, tracking_number, 'UPS', 'Delivered'))
        
        shipment_id = shipment_cursor.lastrowid
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': f'Created sample PO {po_number} with delivered UPS shipment. Ready for receiving!',
            'po_id': po_id,
            'shipment_id': shipment_id
        })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'error': f'Failed to create sample data: {str(e)}'}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/update_submission_date', methods=['POST'])
@role_required('dashboard')
def update_submission_date():
    """Update the submission date for an existing submission"""
    conn = None
    try:
        data = request.get_json()
        submission_id = data.get('submission_id')
        submission_date = data.get('submission_date')
        
        if not submission_id or not submission_date:
            return jsonify({'error': 'Missing submission_id or submission_date'}), 400
        
        conn = get_db()
        
        # Update the submission date
        conn.execute('''
            UPDATE warehouse_submissions 
            SET submission_date = ?
            WHERE id = ?
        ''', (submission_date, submission_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Submission date updated to {submission_date}'
        })
        
    except Exception as e:
        # Ensure connection is closed even on error
        if conn:
            try:
                conn.close()
            except:
                pass
        return jsonify({'error': str(e)}), 500



@bp.route('/api/submission/<int:submission_id>/available_pos', methods=['GET'])
@role_required('dashboard')
def get_available_pos_for_submission(submission_id):
    """Get list of POs that can accept this submission (filtered by product/inventory_item_id)"""
    conn = None
    try:
        conn = get_db()
        
        # Get submission details
        submission = conn.execute('''
            SELECT ws.*, pd.packages_per_display, pd.tablets_per_package, tt.inventory_item_id
            FROM warehouse_submissions ws
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            WHERE ws.id = ?
        ''', (submission_id,)).fetchone()
        
        if not submission:
            return jsonify({'error': 'Submission not found'}), 404
        
        inventory_item_id = submission['inventory_item_id']
        if not inventory_item_id:
            return jsonify({'error': 'Could not determine product inventory_item_id'}), 400
        
        # Get all POs (open and closed) that have this inventory_item_id
        # Exclude Draft POs, order newest first (DESC) for less scrolling
        pos = conn.execute('''
            SELECT DISTINCT po.id, po.po_number, po.closed, po.internal_status,
                   po.ordered_quantity, po.current_good_count, po.current_damaged_count
            FROM purchase_orders po
            INNER JOIN po_lines pl ON po.id = pl.po_id
            WHERE pl.inventory_item_id = ?
            AND COALESCE(po.internal_status, '') != 'Draft'
            ORDER BY po.po_number DESC
        ''', (inventory_item_id,)).fetchall()
        
        pos_list = []
        for po in pos:
            pos_list.append({
                'id': po['id'],
                'po_number': po['po_number'],
                'closed': bool(po['closed']),
                'status': 'Cancelled' if po['internal_status'] == 'Cancelled' else ('Closed' if po['closed'] else (po['internal_status'] or 'Active')),
                'ordered': po['ordered_quantity'] or 0,
                'good': po['current_good_count'] or 0,
                'damaged': po['current_damaged_count'] or 0,
                'remaining': (po['ordered_quantity'] or 0) - (po['current_good_count'] or 0) - (po['current_damaged_count'] or 0)
            })
        
        return jsonify({
            'success': True,
            'available_pos': pos_list,
            'submission_product': submission['product_name'],
            'current_po_id': submission['assigned_po_id']
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/submission/<int:submission_id>/approve', methods=['POST'])
@role_required('dashboard')
def approve_submission_assignment(submission_id):
    """Approve and lock the current PO assignment for a submission"""
    conn = None
    try:
        conn = get_db()
        
        # Check if submission exists and isn't already verified
        submission = conn.execute('''
            SELECT id, assigned_po_id, po_assignment_verified
            FROM warehouse_submissions
            WHERE id = ?
        ''', (submission_id,)).fetchone()
        
        if not submission:
            conn.close()
            return jsonify({'error': 'Submission not found'}), 404
        
        if submission['po_assignment_verified']:
            conn.close()
            return jsonify({'error': 'Submission already verified and locked'}), 400
        
        if not submission['assigned_po_id']:
            conn.close()
            return jsonify({'error': 'Cannot approve unassigned submission'}), 400
        
        # Mark as verified/locked
        conn.execute('''
            UPDATE warehouse_submissions 
            SET po_assignment_verified = TRUE
            WHERE id = ?
        ''', (submission_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'PO assignment approved and locked'
        })
        
    except Exception as e:
        # Ensure connection is closed even on error
        if conn:
            try:
                conn.close()
            except:
                pass
        return jsonify({'error': str(e)}), 500



@bp.route('/api/submission/<int:submission_id>/reassign', methods=['POST'])
@role_required('dashboard')
def reassign_submission_to_po(submission_id):
    """Reassign a submission to a different PO (manager verification/correction)"""
    conn = None
    try:
        data = request.get_json()
        new_po_id = data.get('new_po_id')
        
        if not new_po_id:
            return jsonify({'error': 'Missing new_po_id'}), 400
        
        conn = get_db()
        
        # Get submission details
        submission = conn.execute('''
            SELECT ws.*, pd.packages_per_display, pd.tablets_per_package, tt.inventory_item_id,
                   COALESCE(ws.submission_type, 'packaged') as submission_type
            FROM warehouse_submissions ws
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            WHERE ws.id = ?
        ''', (submission_id,)).fetchone()
        
        if not submission:
            conn.close()
            return jsonify({'error': 'Submission not found'}), 404
        
        # Check if already verified/locked
        if submission['po_assignment_verified']:
            conn.close()
            return jsonify({'error': 'Cannot reassign: PO assignment is already verified and locked'}), 403
        
        old_po_id = submission['assigned_po_id']
        inventory_item_id = submission['inventory_item_id']
        
        # Verify new PO has this product
        new_po_check = conn.execute('''
            SELECT COUNT(*) as count
            FROM po_lines pl
            WHERE pl.po_id = ? AND pl.inventory_item_id = ?
        ''', (new_po_id, inventory_item_id)).fetchone()
        
        if new_po_check['count'] == 0:
            conn.close()
            return jsonify({'error': 'Selected PO does not have this product'}), 400
        
        # Calculate counts based on submission type
        submission_type = submission.get('submission_type', 'packaged')
        if submission_type == 'machine':
            good_tablets = submission.get('tablets_pressed_into_cards', 0) or 0
        else:
            packages_per_display = submission['packages_per_display'] or 0
            tablets_per_package = submission['tablets_per_package'] or 0
            good_tablets = (submission['displays_made'] * packages_per_display * tablets_per_package + 
                           submission['packs_remaining'] * tablets_per_package + 
                           submission['loose_tablets'])
        damaged_tablets = submission['damaged_tablets']
        
        # Remove counts from old PO if assigned
        if old_po_id:
            # Remove from old PO line
            old_line = conn.execute('''
                SELECT id FROM po_lines 
                WHERE po_id = ? AND inventory_item_id = ?
                LIMIT 1
            ''', (old_po_id, inventory_item_id)).fetchone()
            
            if old_line:
                # Get current counts first to calculate new values
                current_line = conn.execute('''
                    SELECT good_count, damaged_count FROM po_lines WHERE id = ?
                ''', (old_line['id'],)).fetchone()
                
                new_good = max(0, (current_line['good_count'] or 0) - good_tablets)
                new_damaged = max(0, (current_line['damaged_count'] or 0) - damaged_tablets)
                
                conn.execute('''
                    UPDATE po_lines 
                    SET good_count = ?, 
                        damaged_count = ?
                    WHERE id = ?
                ''', (new_good, new_damaged, old_line['id']))
                
                # Update old PO header
                old_totals = conn.execute('''
                    SELECT 
                        COALESCE(SUM(quantity_ordered), 0) as total_ordered,
                        COALESCE(SUM(good_count), 0) as total_good,
                        COALESCE(SUM(damaged_count), 0) as total_damaged
                    FROM po_lines 
                    WHERE po_id = ?
                ''', (old_po_id,)).fetchone()
                
                remaining = old_totals['total_ordered'] - old_totals['total_good'] - old_totals['total_damaged']
                conn.execute('''
                    UPDATE purchase_orders 
                    SET ordered_quantity = ?, current_good_count = ?, 
                        current_damaged_count = ?, remaining_quantity = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (old_totals['total_ordered'], old_totals['total_good'], 
                      old_totals['total_damaged'], remaining, old_po_id))
        
        # Add counts to new PO line
        new_line = conn.execute('''
            SELECT id FROM po_lines 
            WHERE po_id = ? AND inventory_item_id = ?
            LIMIT 1
        ''', (new_po_id, inventory_item_id)).fetchone()
        
        if new_line:
            conn.execute('''
                UPDATE po_lines 
                SET good_count = good_count + ?, damaged_count = damaged_count + ?
                WHERE id = ?
            ''', (good_tablets, damaged_tablets, new_line['id']))
            
            # Update new PO header
            new_totals = conn.execute('''
                SELECT 
                    COALESCE(SUM(quantity_ordered), 0) as total_ordered,
                    COALESCE(SUM(good_count), 0) as total_good,
                    COALESCE(SUM(damaged_count), 0) as total_damaged
                FROM po_lines 
                WHERE po_id = ?
            ''', (new_po_id,)).fetchone()
            
            remaining = new_totals['total_ordered'] - new_totals['total_good'] - new_totals['total_damaged']
            conn.execute('''
                UPDATE purchase_orders 
                SET ordered_quantity = ?, current_good_count = ?, 
                    current_damaged_count = ?, remaining_quantity = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (new_totals['total_ordered'], new_totals['total_good'], 
                  new_totals['total_damaged'], remaining, new_po_id))
        
        # Update submission assignment and mark as verified (locked)
        conn.execute('''
            UPDATE warehouse_submissions 
            SET assigned_po_id = ?, po_assignment_verified = TRUE
            WHERE id = ?
        ''', (new_po_id, submission_id))
        
        # Get new PO number for response
        new_po = conn.execute('SELECT po_number FROM purchase_orders WHERE id = ?', (new_po_id,)).fetchone()
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Submission reassigned to PO-{new_po["po_number"]} and locked',
            'new_po_number': new_po['po_number']
        })
        
    except Exception as e:
        # Ensure connection is closed even on error
        if conn:
            try:
                conn.close()
            except:
                pass
        return jsonify({'error': str(e)}), 500



@bp.route('/api/submission/<int:submission_id>/admin_reassign', methods=['POST'])
@admin_required
def admin_reassign_verified_submission(submission_id):
    """Admin-only: Reassign a verified submission to a different PO (bypasses verification lock)"""
    conn = None
    try:
        data = request.get_json()
        new_po_id = data.get('new_po_id')
        confirm_override = data.get('confirm_override', False)
        
        if not new_po_id:
            return jsonify({'error': 'Missing new_po_id'}), 400
        
        if not confirm_override:
            return jsonify({'error': 'Admin override confirmation required'}), 400
        
        conn = get_db()
        
        # Get submission details
        submission = conn.execute('''
            SELECT ws.*, pd.packages_per_display, pd.tablets_per_package, tt.inventory_item_id,
                   COALESCE(ws.submission_type, 'packaged') as submission_type
            FROM warehouse_submissions ws
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            WHERE ws.id = ?
        ''', (submission_id,)).fetchone()
        
        if not submission:
            return jsonify({'error': 'Submission not found'}), 404
        
        old_po_id = submission['assigned_po_id']
        inventory_item_id = submission['inventory_item_id']
        
        # Verify new PO has this product
        new_po_check = conn.execute('''
            SELECT COUNT(*) as count
            FROM po_lines pl
            WHERE pl.po_id = ? AND pl.inventory_item_id = ?
        ''', (new_po_id, inventory_item_id)).fetchone()
        
        if new_po_check['count'] == 0:
            return jsonify({'error': 'Selected PO does not have this product'}), 400
        
        # Calculate counts based on submission type
        submission_type = submission.get('submission_type', 'packaged')
        if submission_type == 'machine':
            good_tablets = submission.get('tablets_pressed_into_cards', 0) or 0
        else:
            packages_per_display = submission['packages_per_display'] or 0
            tablets_per_package = submission['tablets_per_package'] or 0
            good_tablets = (submission['displays_made'] * packages_per_display * tablets_per_package + 
                           submission['packs_remaining'] * tablets_per_package + 
                           submission['loose_tablets'])
        damaged_tablets = submission['damaged_tablets']
        
        # Remove counts from old PO if assigned
        if old_po_id:
            # Remove from old PO line
            old_line = conn.execute('''
                SELECT id FROM po_lines 
                WHERE po_id = ? AND inventory_item_id = ?
                LIMIT 1
            ''', (old_po_id, inventory_item_id)).fetchone()
            
            if old_line:
                # Get current counts first to calculate new values
                current_line = conn.execute('''
                    SELECT good_count, damaged_count FROM po_lines WHERE id = ?
                ''', (old_line['id'],)).fetchone()
                
                new_good = max(0, (current_line['good_count'] or 0) - good_tablets)
                new_damaged = max(0, (current_line['damaged_count'] or 0) - damaged_tablets)
                
                conn.execute('''
                    UPDATE po_lines 
                    SET good_count = ?, 
                        damaged_count = ?
                    WHERE id = ?
                ''', (new_good, new_damaged, old_line['id']))
                
                # Update old PO header
                old_totals = conn.execute('''
                    SELECT 
                        COALESCE(SUM(quantity_ordered), 0) as total_ordered,
                        COALESCE(SUM(good_count), 0) as total_good,
                        COALESCE(SUM(damaged_count), 0) as total_damaged
                    FROM po_lines 
                    WHERE po_id = ?
                ''', (old_po_id,)).fetchone()
                
                remaining = old_totals['total_ordered'] - old_totals['total_good'] - old_totals['total_damaged']
                conn.execute('''
                    UPDATE purchase_orders 
                    SET ordered_quantity = ?, current_good_count = ?, 
                        current_damaged_count = ?, remaining_quantity = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (old_totals['total_ordered'], old_totals['total_good'], 
                      old_totals['total_damaged'], remaining, old_po_id))
        
        # Add counts to new PO line
        new_line = conn.execute('''
            SELECT id FROM po_lines 
            WHERE po_id = ? AND inventory_item_id = ?
            LIMIT 1
        ''', (new_po_id, inventory_item_id)).fetchone()
        
        if new_line:
            conn.execute('''
                UPDATE po_lines 
                SET good_count = good_count + ?, damaged_count = damaged_count + ?
                WHERE id = ?
            ''', (good_tablets, damaged_tablets, new_line['id']))
            
            # Update new PO header
            new_totals = conn.execute('''
                SELECT 
                    COALESCE(SUM(quantity_ordered), 0) as total_ordered,
                    COALESCE(SUM(good_count), 0) as total_good,
                    COALESCE(SUM(damaged_count), 0) as total_damaged
                FROM po_lines 
                WHERE po_id = ?
            ''', (new_po_id,)).fetchone()
            
            remaining = new_totals['total_ordered'] - new_totals['total_good'] - new_totals['total_damaged']
            conn.execute('''
                UPDATE purchase_orders 
                SET ordered_quantity = ?, current_good_count = ?, 
                    current_damaged_count = ?, remaining_quantity = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (new_totals['total_ordered'], new_totals['total_good'], 
                  new_totals['total_damaged'], remaining, new_po_id))
        
        # Update submission assignment (keep verified status)
        conn.execute('''
            UPDATE warehouse_submissions 
            SET assigned_po_id = ?
            WHERE id = ?
        ''', (new_po_id, submission_id))
        
        # Get new PO number for response
        new_po = conn.execute('SELECT po_number FROM purchase_orders WHERE id = ?', (new_po_id,)).fetchone()
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': f'Submission reassigned to PO-{new_po["po_number"]} (Admin override)'
        })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/reassign_all_submissions', methods=['POST'])
@admin_required
def reassign_all_submissions():
    """Reassign ALL submissions to POs using correct PO order (by PO number, not created_at)"""
    conn = None
    try:
        conn = get_db()
        
        # Step 1: Clear all PO assignments and counts (soft reassign - reset verification)
        print("Clearing all PO assignments and counts...")
        conn.execute('UPDATE warehouse_submissions SET assigned_po_id = NULL, po_assignment_verified = FALSE')
        conn.execute('UPDATE po_lines SET good_count = 0, damaged_count = 0')
        conn.execute('UPDATE purchase_orders SET current_good_count = 0, current_damaged_count = 0, remaining_quantity = ordered_quantity')
        conn.commit()
        
        # Step 2: Get all submissions in order with their creation timestamp
        all_submissions_rows = conn.execute('''
            SELECT ws.id, ws.product_name, ws.displays_made, 
                   ws.packs_remaining, ws.loose_tablets, ws.damaged_tablets, ws.tablets_pressed_into_cards,
                   COALESCE(ws.submission_type, 'packaged') as submission_type, ws.created_at
            FROM warehouse_submissions ws
            ORDER BY ws.created_at ASC
        ''').fetchall()
        
        all_submissions = [dict(row) for row in all_submissions_rows]
        
        if not all_submissions:
            return jsonify({'success': True, 'message': 'No submissions found'})
        
        matched_count = 0
        updated_pos = set()
        
        # Track running totals for each PO line during reassignment
        # This helps us know when to move to the next PO (when current one has enough)
        po_line_running_totals = {}  # {line_id: {'good': count, 'damaged': count}}
        
        # Step 3: Reassign each submission using correct PO order
        for submission in all_submissions:
            try:
                # Get product details
                product_row = conn.execute('''
                    SELECT tt.inventory_item_id, pd.packages_per_display, pd.tablets_per_package
                    FROM product_details pd
                    JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                    WHERE pd.product_name = ?
                ''', (submission['product_name'],)).fetchone()
                
                if not product_row:
                    # Try direct tablet_type match
                    product_row = conn.execute('''
                        SELECT inventory_item_id, 0 as packages_per_display, 0 as tablets_per_package
                        FROM tablet_types
                        WHERE tablet_type_name = ?
                    ''', (submission['product_name'],)).fetchone()
                
                if not product_row:
                    continue
                
                product = dict(product_row)
                inventory_item_id = product.get('inventory_item_id')
                
                if not inventory_item_id:
                    continue
                
                # Find OPEN PO lines only - ORDER BY PO NUMBER
                # Automatic bulk reassignment assigns to open POs only
                # Managers can still manually reassign to closed POs via "Change" button
                # Exclude Draft POs - only assign to Active/Issued open POs
                # Note: We do NOT filter by available quantity - POs can receive more than ordered
                po_lines_rows = conn.execute('''
                    SELECT pl.*, po.closed, po.po_number
                    FROM po_lines pl
                    JOIN purchase_orders po ON pl.po_id = po.id
                    WHERE pl.inventory_item_id = ?
                    AND COALESCE(po.internal_status, '') != 'Draft'
                    AND po.closed = FALSE
                    AND COALESCE(po.internal_status, '') != 'Cancelled'
                    ORDER BY po.po_number ASC
                ''', (inventory_item_id,)).fetchall()
                
                po_lines = [dict(row) for row in po_lines_rows]
                
                if not po_lines:
                    continue
                
                # Calculate good and damaged counts based on submission type
                submission_type = submission.get('submission_type', 'packaged')
                if submission_type == 'machine':
                    good_tablets = submission.get('tablets_pressed_into_cards', 0) or 0
                else:
                    packages_per_display = product.get('packages_per_display') or 0
                    tablets_per_package = product.get('tablets_per_package') or 0
                    good_tablets = (submission.get('displays_made', 0) * packages_per_display * tablets_per_package + 
                                  submission.get('packs_remaining', 0) * tablets_per_package + 
                                  submission.get('loose_tablets', 0))
                damaged_tablets = submission.get('damaged_tablets', 0)
                
                # Find the first PO that hasn't reached its ordered quantity yet
                # This allows sequential filling: complete PO-127, then PO-131, then PO-135, etc.
                # But final counts can still exceed ordered quantities (no artificial cap)
                assigned_po_id = None
                for line in po_lines:
                    # Initialize running total if first time seeing this line
                    if line['id'] not in po_line_running_totals:
                        po_line_running_totals[line['id']] = {'good': 0, 'damaged': 0, 'quantity_ordered': line['quantity_ordered']}
                    
                    # Check if this PO line still needs more tablets
                    current_total = po_line_running_totals[line['id']]['good'] + po_line_running_totals[line['id']]['damaged']
                    if current_total < line['quantity_ordered']:
                        # This PO still has room, assign to it
                        assigned_po_id = line['po_id']
                        break
                
                # If all POs are at or above their ordered quantities, assign to the last (newest) PO
                if assigned_po_id is None and po_lines:
                    assigned_po_id = po_lines[-1]['po_id']
                conn.execute('''
                    UPDATE warehouse_submissions 
                    SET assigned_po_id = ?
                    WHERE id = ?
                ''', (assigned_po_id, submission['id']))
                
                # IMPORTANT: Only allocate counts to lines from the ASSIGNED PO
                # This ensures older POs are completely filled before newer ones receive submissions
                assigned_po_lines = [line for line in po_lines if line['po_id'] == assigned_po_id]
                
                # Allocate counts to PO lines from the assigned PO only
                # Note: We do NOT cap at ordered quantity - actual production may exceed the PO
                remaining_good = good_tablets
                remaining_damaged = damaged_tablets
                
                for line in assigned_po_lines:
                    if remaining_good <= 0 and remaining_damaged <= 0:
                        break
                    
                    # Apply all remaining good count to this line
                    if remaining_good > 0:
                        conn.execute('''
                            UPDATE po_lines 
                            SET good_count = good_count + ?
                            WHERE id = ?
                        ''', (remaining_good, line['id']))
                        # Update running total
                        if line['id'] in po_line_running_totals:
                            po_line_running_totals[line['id']]['good'] += remaining_good
                        remaining_good = 0
                    
                    # Apply all remaining damaged count to this line
                    if remaining_damaged > 0:
                        conn.execute('''
                            UPDATE po_lines 
                            SET damaged_count = damaged_count + ?
                            WHERE id = ?
                        ''', (remaining_damaged, line['id']))
                        # Update running total
                        if line['id'] in po_line_running_totals:
                            po_line_running_totals[line['id']]['damaged'] += remaining_damaged
                        remaining_damaged = 0
                    
                    updated_pos.add(line['po_id'])
                    break  # All counts applied to first line
                
                matched_count += 1
            except Exception as e:
                if conn:
                    try:
                        conn.rollback()
                    except:
                        pass
                print(f"Error processing submission {submission.get('id')}: {e}")
                continue
        
        # Step 4: Update PO header totals
        for po_id in updated_pos:
            totals_row = conn.execute('''
                SELECT 
                    COALESCE(SUM(quantity_ordered), 0) as total_ordered,
                    COALESCE(SUM(good_count), 0) as total_good,
                    COALESCE(SUM(damaged_count), 0) as total_damaged
                FROM po_lines 
                WHERE po_id = ?
            ''', (po_id,)).fetchone()
            
            totals = dict(totals_row)
            remaining = totals.get('total_ordered', 0) - totals.get('total_good', 0) - totals.get('total_damaged', 0)
            
            conn.execute('''
                UPDATE purchase_orders 
                SET ordered_quantity = ?, current_good_count = ?, 
                    current_damaged_count = ?, remaining_quantity = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (totals.get('total_ordered', 0), totals.get('total_good', 0), 
                  totals.get('total_damaged', 0), remaining, po_id))
        
        conn.commit()
        
        return jsonify({
            'success': True, 
            'message': f'✅ Reassigned all {matched_count} submissions to POs using correct order (by PO number)',
            'matched': matched_count,
            'total_submissions': len(all_submissions)
        })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌❌❌ REASSIGN ERROR: {str(e)}")
        print(error_trace)
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'error': str(e), 'trace': error_trace}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/recalculate_po_counts', methods=['POST'])
@admin_required
def recalculate_po_counts():
    """
    Recalculate PO line counts based on currently assigned submissions.
    Does NOT change any PO assignments - just fixes the counts to match actual submissions.
    """
    conn = None
    try:
        conn = get_db()
        
        print("🔄 Recalculating PO counts without changing assignments...")
        
        # Step 1: Reset all PO line counts to zero
        conn.execute('UPDATE po_lines SET good_count = 0, damaged_count = 0')
        conn.commit()
        
        # Step 2: Get all submissions with inventory_item_id (now stored directly!)
        # Use COALESCE to fallback to JOIN for old submissions without inventory_item_id
        submissions_query = '''
            SELECT 
                ws.id as submission_id,
                ws.assigned_po_id,
                ws.product_name,
                ws.displays_made,
                ws.packs_remaining,
                ws.loose_tablets,
                ws.damaged_tablets,
                ws.tablets_pressed_into_cards,
                COALESCE(ws.submission_type, 'packaged') as submission_type,
                ws.created_at,
                pd.packages_per_display,
                pd.tablets_per_package,
                COALESCE(ws.inventory_item_id, tt.inventory_item_id) as inventory_item_id
            FROM warehouse_submissions ws
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            WHERE ws.assigned_po_id IS NOT NULL
            ORDER BY ws.created_at ASC
        '''
        submissions = conn.execute(submissions_query).fetchall()
        
        # Group submissions by PO and inventory_item_id
        po_line_totals = {}  # {(po_id, inventory_item_id): {'good': X, 'damaged': Y}}
        skipped_submissions = []
        
        for sub in submissions:
            po_id = sub['assigned_po_id']
            inventory_item_id = sub['inventory_item_id']
            
            if not inventory_item_id:
                submission_type = sub.get('submission_type', 'packaged')
                if submission_type == 'machine':
                    good_tablets = sub.get('tablets_pressed_into_cards', 0) or 0
                else:
                    packages_per_display = sub['packages_per_display'] or 0
                    tablets_per_package = sub['tablets_per_package'] or 0
                    good_tablets = (
                        (sub['displays_made'] or 0) * packages_per_display * tablets_per_package +
                        (sub['packs_remaining'] or 0) * tablets_per_package +
                        (sub['loose_tablets'] or 0)
                    )
                skipped_submissions.append({
                    'submission_id': sub['submission_id'],
                    'product_name': sub['product_name'],
                    'good_tablets': good_tablets,
                    'damaged_tablets': sub['damaged_tablets'] or 0,
                    'created_at': sub['created_at'],
                    'po_id': sub['assigned_po_id']
                })
                print(f"⚠️ Skipped submission ID {sub['submission_id']}: {sub['product_name']} - {good_tablets} tablets (no inventory_item_id)")
                continue
            
            # Calculate good and damaged counts based on submission type
            submission_type = sub.get('submission_type', 'packaged')
            if submission_type == 'machine':
                good_tablets = sub.get('tablets_pressed_into_cards', 0) or 0
            else:
                packages_per_display = sub['packages_per_display'] or 0
                tablets_per_package = sub['tablets_per_package'] or 0
                good_tablets = (
                    (sub['displays_made'] or 0) * packages_per_display * tablets_per_package +
                    (sub['packs_remaining'] or 0) * tablets_per_package +
                    (sub['loose_tablets'] or 0)
                )
            damaged_tablets = sub['damaged_tablets'] or 0
            
            # Add to running total for this PO line
            key = (po_id, inventory_item_id)
            if key not in po_line_totals:
                po_line_totals[key] = {'good': 0, 'damaged': 0}
            
            po_line_totals[key]['good'] += good_tablets
            po_line_totals[key]['damaged'] += damaged_tablets
        
        # Step 3: Update each PO line with the calculated totals
        updated_count = 0
        for (po_id, inventory_item_id), totals in po_line_totals.items():
            # Find the PO line for this PO and inventory item
            line = conn.execute('''
                SELECT id FROM po_lines
                WHERE po_id = ? AND inventory_item_id = ?
                LIMIT 1
            ''', (po_id, inventory_item_id)).fetchone()
            
            if line:
                conn.execute('''
                    UPDATE po_lines
                    SET good_count = ?, damaged_count = ?
                    WHERE id = ?
                ''', (totals['good'], totals['damaged'], line['id']))
                updated_count += 1
                print(f"✅ Updated PO line {line['id']}: {totals['good']} good, {totals['damaged']} damaged")
        
        # Step 4: Update PO header totals from line totals
        conn.execute('''
            UPDATE purchase_orders
            SET 
                ordered_quantity = (
                    SELECT COALESCE(SUM(quantity_ordered), 0)
                    FROM po_lines
                    WHERE po_lines.po_id = purchase_orders.id
                ),
                current_good_count = (
                    SELECT COALESCE(SUM(good_count), 0)
                    FROM po_lines
                    WHERE po_lines.po_id = purchase_orders.id
                ),
                current_damaged_count = (
                    SELECT COALESCE(SUM(damaged_count), 0)
                    FROM po_lines
                    WHERE po_lines.po_id = purchase_orders.id
                ),
                remaining_quantity = (
                    SELECT COALESCE(SUM(quantity_ordered), 0) - COALESCE(SUM(good_count), 0) - COALESCE(SUM(damaged_count), 0)
                    FROM po_lines
                    WHERE po_lines.po_id = purchase_orders.id
                ),
                updated_at = CURRENT_TIMESTAMP
        ''')
        
        conn.commit()
        
        # Build response message
        message = f'Successfully recalculated counts for {updated_count} PO lines. No assignments were changed.'
        skipped_by_product = {}
        
        if skipped_submissions:
            # Group skipped by product
            for skip in skipped_submissions:
                product = skip['product_name']
                if product not in skipped_by_product:
                    skipped_by_product[product] = {'good': 0, 'damaged': 0}
                skipped_by_product[product]['good'] += skip['good_tablets']
                skipped_by_product[product]['damaged'] += skip['damaged_tablets']
            
            message += f'\n\n⚠️ WARNING: {len(skipped_submissions)} submissions were skipped (missing product configuration):\n'
            for product, totals in skipped_by_product.items():
                message += f'\n• {product}: {totals["good"]} tablets (damaged: {totals["damaged"]})'
            message += '\n\nTo fix: Go to "Manage Products" and ensure each product is linked to a tablet type with an inventory_item_id.'
        
        return jsonify({
            'success': True,
            'message': message,
            'skipped_count': len(skipped_submissions),
            'skipped_details': skipped_by_product
        })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        error_trace = traceback.format_exc()
        print(f"❌ RECALCULATE ERROR: {str(e)}")
        print(error_trace)
        return jsonify({'error': str(e), 'trace': error_trace}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/submission/<int:submission_id>/details', methods=['GET'])
@role_required('dashboard')
def get_submission_details(submission_id):
    """Get full details of a submission (viewable by all authenticated users)"""
    conn = None
    try:
        conn = get_db()
        
        submission = conn.execute('''
            SELECT ws.*, po.po_number, po.closed as po_closed, po.zoho_po_id,
                   COALESCE(ws.po_assignment_verified, 0) as po_verified,
                   pd.packages_per_display, pd.tablets_per_package,
                   COALESCE(pd.tablets_per_package, pd_fallback.tablets_per_package) as tablets_per_package_final,
                   COALESCE(b.bag_label_count, ws.bag_label_count, 0) as bag_label_count, 
                   r.id as receive_id, r.received_date,
                   m.machine_name, m.cards_per_turn as machine_cards_per_turn,
                   (
                       SELECT COUNT(*) + 1
                       FROM receiving r2
                       WHERE r2.po_id = r.po_id
                       AND (r2.received_date < r.received_date 
                            OR (r2.received_date = r.received_date AND r2.id < r.id))
                   ) as shipment_number
            FROM warehouse_submissions ws
            LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            LEFT JOIN tablet_types tt_fallback ON ws.inventory_item_id = tt_fallback.inventory_item_id
            LEFT JOIN product_details pd_fallback ON tt_fallback.id = pd_fallback.tablet_type_id
            LEFT JOIN bags b ON ws.bag_id = b.id
            LEFT JOIN small_boxes sb ON b.small_box_id = sb.id
            LEFT JOIN receiving r ON sb.receiving_id = r.id
            LEFT JOIN machines m ON ws.machine_id = m.id
            WHERE ws.id = ?
        ''', (submission_id,)).fetchone()
        
        if not submission:
            conn.close()
            return jsonify({'success': False, 'error': 'Submission not found'}), 404
        
        submission_dict = dict(submission)
        submission_type = submission_dict.get('submission_type', 'packaged')
        
        # If bag_label_count is 0 or missing but bag_id exists, try to get it directly from bags table
        if submission_dict.get('bag_id') and (not submission_dict.get('bag_label_count') or submission_dict.get('bag_label_count') == 0):
            bag_row = conn.execute('SELECT bag_label_count FROM bags WHERE id = ?', (submission_dict.get('bag_id'),)).fetchone()
            if bag_row:
                bag_dict = dict(bag_row)
                if bag_dict.get('bag_label_count'):
                    submission_dict['bag_label_count'] = bag_dict.get('bag_label_count')
        
        # Get machine information for machine submissions
        # First try to get from the JOIN we already did
        machine_name = submission_dict.get('machine_name')
        cards_per_turn = submission_dict.get('machine_cards_per_turn')
        
        if submission_type == 'machine':
            # If not found from JOIN, try to get from machine_id in submission
            if not cards_per_turn and submission_dict.get('machine_id'):
                machine_row = conn.execute('''
                    SELECT machine_name, cards_per_turn
                    FROM machines
                    WHERE id = ?
                ''', (submission_dict.get('machine_id'),)).fetchone()
                if machine_row:
                    machine = dict(machine_row)
                    if not machine_name:
                        machine_name = machine.get('machine_name')
                    if not cards_per_turn:
                        cards_per_turn = machine.get('cards_per_turn')
            
            # If still not found, try to find from machine_counts table by matching submission details
            if not cards_per_turn:
                tablet_type_row = conn.execute('''
                    SELECT id FROM tablet_types WHERE inventory_item_id = ?
                ''', (submission_dict.get('inventory_item_id'),)).fetchone()
                
                if tablet_type_row:
                    tablet_type = dict(tablet_type_row)
                    tablet_type_id = tablet_type.get('id')
                    
                    # Try to find machine_count record that matches this submission
                    submission_date = submission_dict.get('submission_date') or submission_dict.get('created_at')
                    machine_count_record_row = conn.execute('''
                        SELECT mc.machine_id, m.machine_name, m.cards_per_turn
                        FROM machine_counts mc
                        LEFT JOIN machines m ON mc.machine_id = m.id
                        WHERE mc.tablet_type_id = ?
                        AND mc.machine_count = ?
                        AND mc.employee_name = ?
                        AND DATE(mc.count_date) = DATE(?)
                        ORDER BY mc.created_at DESC
                        LIMIT 1
                    ''', (tablet_type_id, 
                          submission_dict.get('displays_made'),
                          submission_dict.get('employee_name'),
                          submission_date)).fetchone()
                    
                    if machine_count_record_row:
                        machine_count_record = dict(machine_count_record_row)
                        if not machine_name:
                            machine_name = machine_count_record.get('machine_name')
                        if not cards_per_turn:
                            cards_per_turn = machine_count_record.get('cards_per_turn')
            
            # Fallback to app_settings if machine not found
            if not cards_per_turn:
                cards_per_turn_setting_row = conn.execute(
                    'SELECT setting_value FROM app_settings WHERE setting_key = ?',
                    ('cards_per_turn',)
                ).fetchone()
                if cards_per_turn_setting_row:
                    cards_per_turn_setting = dict(cards_per_turn_setting_row)
                    cards_per_turn = int(cards_per_turn_setting.get('setting_value', 1))
                else:
                    cards_per_turn = 1
            
            # Recalculate cards_made using correct machine-specific cards_per_turn
            # This fixes submissions that were saved with wrong cards_per_turn
            machine_count = submission_dict.get('displays_made', 0) or 0  # displays_made stores machine_count (turns)
            cards_made = machine_count * cards_per_turn
            submission_dict['cards_made'] = cards_made  # Add recalculated cards_made
            
            # For machine submissions: total tablets pressed into cards is stored in tablets_pressed_into_cards
            # Fallback to loose_tablets, then calculate from cards_made × tablets_per_package
            packs_remaining = submission_dict.get('packs_remaining', 0) or 0
            # Use tablets_per_package_final (with fallback) if available, otherwise try tablets_per_package
            tablets_per_package = (submission_dict.get('tablets_per_package_final') or 
                                 submission_dict.get('tablets_per_package') or 0)
            
            # If tablets_per_package is still 0 or None, try to get it directly from database using inventory_item_id
            if not tablets_per_package or tablets_per_package == 0:
                inventory_item_id = submission_dict.get('inventory_item_id')
                if inventory_item_id:
                    # Try to get tablets_per_package via inventory_item_id -> tablet_types -> product_details
                    tpp_row = conn.execute('''
                        SELECT pd.tablets_per_package
                        FROM tablet_types tt
                        JOIN product_details pd ON tt.id = pd.tablet_type_id
                        WHERE tt.inventory_item_id = ?
                        LIMIT 1
                    ''', (inventory_item_id,)).fetchone()
                    if tpp_row:
                        tpp_dict = dict(tpp_row)
                        tablets_per_package = tpp_dict.get('tablets_per_package', 0) or 0
            
            submission_dict['individual_calc'] = (submission_dict.get('tablets_pressed_into_cards') or
                                                 submission_dict.get('loose_tablets') or
                                                 (packs_remaining * tablets_per_package) or
                                                 0)
            submission_dict['total_tablets'] = submission_dict['individual_calc']
            submission_dict['cards_per_turn'] = cards_per_turn
            submission_dict['machine_name'] = machine_name
            # Use recalculated cards_made instead of packs_remaining (which may have wrong value)
            submission_dict['packs_remaining'] = cards_made
        else:
            # For packaged/bag submissions: calculate from displays and packs
            packages_per_display = submission_dict.get('packages_per_display', 0) or 0
            tablets_per_package = submission_dict.get('tablets_per_package', 0) or 0
            displays_made = submission_dict.get('displays_made', 0) or 0
            packs_remaining = submission_dict.get('packs_remaining', 0) or 0
            loose_tablets = submission_dict.get('loose_tablets', 0) or 0
            damaged_tablets = submission_dict.get('damaged_tablets', 0) or 0
            
            calculated_total = (
                (displays_made * packages_per_display * tablets_per_package) +
                (packs_remaining * tablets_per_package) +
                loose_tablets + damaged_tablets
            )
            submission_dict['individual_calc'] = calculated_total
            submission_dict['total_tablets'] = calculated_total
        
        # Build receive name if we have the necessary information
        receive_name = None
        if submission_dict.get('receive_id') and submission_dict.get('po_number') and submission_dict.get('shipment_number'):
            receive_name = f"{submission_dict.get('po_number')}-{submission_dict.get('shipment_number')}-{submission_dict.get('box_number', '')}-{submission_dict.get('bag_number', '')}"
        submission_dict['receive_name'] = receive_name
        
        # Calculate bag running totals for this submission
        # Get all submissions to the same bag up to and including this submission (chronological order)
        if submission_dict.get('assigned_po_id') and submission_dict.get('product_name') and submission_dict.get('box_number') is not None and submission_dict.get('bag_number') is not None:
            bag_identifier = f"{submission_dict.get('box_number')}/{submission_dict.get('bag_number')}"
            bag_key = (submission_dict.get('assigned_po_id'), submission_dict.get('product_name'), bag_identifier)
            
            # Get all submissions to this bag up to and including this one, in chronological order
            bag_submissions = conn.execute('''
                SELECT ws.*, pd.packages_per_display, pd.tablets_per_package,
                       COALESCE(pd.tablets_per_package, pd_fallback.tablets_per_package) as tablets_per_package_final
                FROM warehouse_submissions ws
                LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                LEFT JOIN tablet_types tt_fallback ON ws.inventory_item_id = tt_fallback.inventory_item_id
                LEFT JOIN product_details pd_fallback ON tt_fallback.id = pd_fallback.tablet_type_id
                WHERE ws.assigned_po_id = ?
                AND ws.product_name = ?
                AND ws.box_number = ?
                AND ws.bag_number = ?
                AND ws.created_at <= ?
                ORDER BY ws.created_at ASC
            ''', (submission_dict.get('assigned_po_id'),
                  submission_dict.get('product_name'),
                  submission_dict.get('box_number'),
                  submission_dict.get('bag_number'),
                  submission_dict.get('created_at'))).fetchall()
            
            # Calculate running totals
            bag_running_total = 0
            machine_running_total = 0
            packaged_running_total = 0
            total_running_total = 0
            
            for bag_sub in bag_submissions:
                bag_sub_dict = dict(bag_sub)
                bag_sub_type = bag_sub_dict.get('submission_type', 'packaged')
                
                # Calculate individual total for this submission
                if bag_sub_type == 'machine':
                    # Use tablets_pressed_into_cards, fallback to loose_tablets, then calculate from cards_made
                    # Use tablets_per_package_final (with fallback) if available, otherwise try tablets_per_package
                    bag_tablets_per_package = (bag_sub_dict.get('tablets_per_package_final') or 
                                             bag_sub_dict.get('tablets_per_package') or 0)
                    individual_total = (bag_sub_dict.get('tablets_pressed_into_cards') or
                                       bag_sub_dict.get('loose_tablets') or
                                       ((bag_sub_dict.get('packs_remaining', 0) or 0) * bag_tablets_per_package) or
                                       0)
                    machine_running_total += individual_total
                    # Machine counts are NOT added to total - they're consumed in production
                elif bag_sub_type == 'bag':
                    # For bag count submissions, use loose_tablets (the actual count from form)
                    individual_total = bag_sub_dict.get('loose_tablets', 0) or 0
                    bag_running_total += individual_total
                    # Bag counts are NOT added to total - they're just inventory counts
                else:  # 'packaged'
                    packages_per_display = bag_sub_dict.get('packages_per_display', 0) or 0
                    tablets_per_package = bag_sub_dict.get('tablets_per_package', 0) or 0
                    displays_made = bag_sub_dict.get('displays_made', 0) or 0
                    packs_remaining = bag_sub_dict.get('packs_remaining', 0) or 0
                    loose_tablets = bag_sub_dict.get('loose_tablets', 0) or 0
                    damaged_tablets = bag_sub_dict.get('damaged_tablets', 0) or 0
                    individual_total = (
                        (displays_made * packages_per_display * tablets_per_package) +
                        (packs_remaining * tablets_per_package) +
                        loose_tablets + damaged_tablets
                    )
                    packaged_running_total += individual_total
                    # Only packaged counts are added to total - these are tablets actually in the bag
                    total_running_total += individual_total
            
            submission_dict['bag_running_total'] = bag_running_total
            submission_dict['machine_running_total'] = machine_running_total
            submission_dict['packaged_running_total'] = packaged_running_total
            # Total should only include packaged counts (tablets actually in the bag)
            # Machine counts are consumed, bag counts are just inventory
            submission_dict['running_total'] = packaged_running_total
            
            # Calculate count status and tablet difference
            # Use packaged_running_total for comparison - machine counts are consumed, not in bag
            bag_label_count = submission_dict.get('bag_label_count', 0) or 0
            if not submission_dict.get('bag_id'):
                submission_dict['count_status'] = 'no_bag'
                submission_dict['tablet_difference'] = None
            elif abs(packaged_running_total - bag_label_count) <= 5:  # Allow 5 tablet tolerance
                submission_dict['count_status'] = 'match'
                submission_dict['tablet_difference'] = abs(packaged_running_total - bag_label_count)
            elif packaged_running_total < bag_label_count:
                submission_dict['count_status'] = 'under'
                submission_dict['tablet_difference'] = bag_label_count - packaged_running_total
            else:
                submission_dict['count_status'] = 'over'
                submission_dict['tablet_difference'] = packaged_running_total - bag_label_count
        else:
            submission_dict['bag_running_total'] = 0
            submission_dict['machine_running_total'] = 0
            submission_dict['packaged_running_total'] = 0
            submission_dict['running_total'] = 0
            submission_dict['count_status'] = 'no_bag'
            submission_dict['tablet_difference'] = None
        
        conn.close()
        
        return jsonify({
            'success': True,
            'submission': submission_dict
        })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ GET SUBMISSION ERROR: {str(e)}")
        print(error_trace)
        if conn:
            try:
                conn.close()
            except:
                pass
        return jsonify({'error': str(e)}), 500



@bp.route('/api/submission/<int:submission_id>/edit', methods=['POST'])
@admin_required
def edit_submission(submission_id):
    """Edit a submission and recalculate PO counts (Admin and Manager only)"""
    # Allow managers to edit submissions (especially admin notes)
    if not (session.get('admin_authenticated') or 
            (session.get('employee_authenticated') and session.get('employee_role') in ['admin', 'manager'])):
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    conn = None
    try:
        data = request.get_json()
        conn = get_db()
        
        # Get the submission's current PO assignment
        submission = conn.execute('''
            SELECT assigned_po_id, product_name, displays_made, packs_remaining, 
                   loose_tablets, damaged_tablets, tablets_pressed_into_cards, inventory_item_id,
                   COALESCE(submission_type, 'packaged') as submission_type
            FROM warehouse_submissions
            WHERE id = ?
        ''', (submission_id,)).fetchone()
        
        if not submission:
            return jsonify({'success': False, 'error': 'Submission not found'}), 404
        
        # Convert Row to dict for safe access
        submission = dict(submission)
        
        old_po_id = submission['assigned_po_id']
        inventory_item_id = submission['inventory_item_id']
        
        # Check if product_name is being changed
        new_product_name = data.get('product_name')
        product_name_to_use = new_product_name if new_product_name else submission['product_name']
        
        # If product is being changed, update inventory_item_id
        if new_product_name and new_product_name != submission['product_name']:
            # Get the new inventory_item_id for the new product
            new_product_info = conn.execute('''
                SELECT tt.inventory_item_id
                FROM tablet_types tt
                JOIN product_details pd ON tt.id = pd.tablet_type_id
                WHERE pd.product_name = ?
                LIMIT 1
            ''', (new_product_name,)).fetchone()
            
            if new_product_info:
                inventory_item_id = new_product_info['inventory_item_id']
        
        # Get product details for calculations
        product = conn.execute('''
            SELECT pd.packages_per_display, pd.tablets_per_package
            FROM product_details pd
            JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            WHERE pd.product_name = ?
        ''', (product_name_to_use,)).fetchone()
        
        if not product:
            return jsonify({'success': False, 'error': 'Product configuration not found'}), 400
        
        # Convert Row to dict for safe access
        product = dict(product)
        
        # Validate product configuration values
        packages_per_display = product.get('packages_per_display')
        tablets_per_package = product.get('tablets_per_package')
        
        if packages_per_display is None or tablets_per_package is None or packages_per_display == 0 or tablets_per_package == 0:
            return jsonify({'success': False, 'error': 'Product configuration incomplete: packages_per_display and tablets_per_package are required and must be greater than 0'}), 400
        
        # Convert to int after validation
        try:
            packages_per_display = int(packages_per_display)
            tablets_per_package = int(tablets_per_package)
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid numeric values for product configuration'}), 400
        
        # Calculate old totals to subtract based on submission type
        submission_type = submission.get('submission_type', 'packaged')
        if submission_type == 'machine':
            old_good = submission.get('tablets_pressed_into_cards', 0) or 0
        else:
            old_good = (submission['displays_made'] * packages_per_display * tablets_per_package +
                       submission['packs_remaining'] * tablets_per_package +
                       submission['loose_tablets'])
        old_damaged = submission['damaged_tablets']
        
        # Validate and convert input data
        try:
            displays_made = int(data.get('displays_made', 0) or 0)
            packs_remaining = int(data.get('packs_remaining', 0) or 0)
            loose_tablets = int(data.get('loose_tablets', 0) or 0)
            damaged_tablets = int(data.get('damaged_tablets', 0) or 0)
            tablets_pressed_into_cards = int(data.get('tablets_pressed_into_cards', 0) or 0) if submission_type == 'machine' else 0
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid numeric values for counts'}), 400
        
        # Calculate new totals based on submission type
        if submission_type == 'machine':
            new_good = tablets_pressed_into_cards
        else:
            new_good = (displays_made * packages_per_display * tablets_per_package +
                       packs_remaining * tablets_per_package +
                       loose_tablets)
        new_damaged = damaged_tablets
        
        # Get receipt_number from form data
        receipt_number = (data.get('receipt_number') or '').strip() or None
        
        # Find the correct bag_id if box_number and bag_number are provided
        new_box_number = data.get('box_number')
        new_bag_number = data.get('bag_number')
        new_bag_id = None
        
        if new_box_number is not None and new_bag_number is not None and old_po_id:
            # Try to find the bag that matches the new box_number and bag_number for this PO
            bag_row = conn.execute('''
                SELECT b.id
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                WHERE r.po_id = ?
                AND sb.box_number = ?
                AND b.bag_number = ?
                LIMIT 1
            ''', (old_po_id, new_box_number, new_bag_number)).fetchone()
            
            if bag_row:
                new_bag_id = dict(bag_row).get('id')
            # If no bag found, set bag_id to NULL (submission will be unassigned)
        
        # Update the submission
        submission_date = data.get('submission_date', datetime.now().date().isoformat())
        if submission_type == 'machine':
            conn.execute('''
                UPDATE warehouse_submissions
                SET displays_made = ?, packs_remaining = ?, tablets_pressed_into_cards = ?, 
                    damaged_tablets = ?, box_number = ?, bag_number = ?, bag_id = ?, bag_label_count = ?,
                    submission_date = ?, admin_notes = ?, receipt_number = ?, product_name = ?, inventory_item_id = ?
                WHERE id = ?
            ''', (displays_made, packs_remaining, tablets_pressed_into_cards,
                  damaged_tablets, new_box_number, new_bag_number, new_bag_id,
                  data.get('bag_label_count'), submission_date, data.get('admin_notes'), receipt_number, 
                  product_name_to_use, inventory_item_id, submission_id))
        else:
            conn.execute('''
                UPDATE warehouse_submissions
                SET displays_made = ?, packs_remaining = ?, loose_tablets = ?, 
                        damaged_tablets = ?, box_number = ?, bag_number = ?, bag_id = ?, bag_label_count = ?,
                        submission_date = ?, admin_notes = ?, receipt_number = ?, product_name = ?, inventory_item_id = ?
                WHERE id = ?
            ''', (displays_made, packs_remaining, loose_tablets,
                      damaged_tablets, new_box_number, new_bag_number, new_bag_id,
                      data.get('bag_label_count'), submission_date, data.get('admin_notes'), receipt_number,
                      product_name_to_use, inventory_item_id, submission_id))
        
        # Update PO line counts if assigned to a PO
        if old_po_id and inventory_item_id:
            # Find the PO line
            po_line = conn.execute('''
                SELECT id FROM po_lines
                WHERE po_id = ? AND inventory_item_id = ?
                LIMIT 1
            ''', (old_po_id, inventory_item_id)).fetchone()
            
            if po_line:
                # Convert Row to dict for safe access
                po_line = dict(po_line)
                
                # Calculate the difference and update
                good_diff = new_good - old_good
                damaged_diff = new_damaged - old_damaged
                
                conn.execute('''
                    UPDATE po_lines
                    SET good_count = good_count + ?, damaged_count = damaged_count + ?
                    WHERE id = ?
                ''', (good_diff, damaged_diff, po_line['id']))
                
                # Update PO header totals
                totals = conn.execute('''
                    SELECT 
                        COALESCE(SUM(quantity_ordered), 0) as total_ordered,
                        COALESCE(SUM(good_count), 0) as total_good,
                        COALESCE(SUM(damaged_count), 0) as total_damaged
                    FROM po_lines 
                    WHERE po_id = ?
                ''', (old_po_id,)).fetchone()
                
                # Convert Row to dict for safe access
                totals = dict(totals)
                
                remaining = totals['total_ordered'] - totals['total_good'] - totals['total_damaged']
                conn.execute('''
                    UPDATE purchase_orders 
                    SET ordered_quantity = ?, current_good_count = ?, 
                        current_damaged_count = ?, remaining_quantity = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (totals['total_ordered'], totals['total_good'], 
                      totals['total_damaged'], remaining, old_po_id))
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': 'Submission updated successfully'
        })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ EDIT SUBMISSION ERROR: {str(e)}")
        print(error_trace)
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/submission/<int:submission_id>/delete', methods=['POST'])
@admin_required
def delete_submission(submission_id):
    """Delete a submission and remove its counts from PO (Admin only)"""
    conn = None
    try:
        conn = get_db()
        
        # Get the submission details
        submission = conn.execute('''
            SELECT assigned_po_id, product_name, displays_made, packs_remaining, 
                   loose_tablets, damaged_tablets, tablets_pressed_into_cards, inventory_item_id,
                   COALESCE(submission_type, 'packaged') as submission_type
            FROM warehouse_submissions
            WHERE id = ?
        ''', (submission_id,)).fetchone()
        
        if not submission:
            return jsonify({'success': False, 'error': 'Submission not found'}), 404
        
        # Convert Row to dict for safe access
        submission = dict(submission)
        
        old_po_id = submission['assigned_po_id']
        inventory_item_id = submission['inventory_item_id']
        
        # Get product details for calculations
        product = conn.execute('''
            SELECT pd.packages_per_display, pd.tablets_per_package
            FROM product_details pd
            JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            WHERE pd.product_name = ?
        ''', (submission['product_name'],)).fetchone()
        
        if not product:
            return jsonify({'success': False, 'error': 'Product configuration not found'}), 400
        
        # Convert Row to dict for safe access
        product = dict(product)
        
        # Calculate counts to remove based on submission type
        submission_type = submission.get('submission_type', 'packaged')
        if submission_type == 'machine':
            good_tablets = submission.get('tablets_pressed_into_cards', 0) or 0
        else:
            good_tablets = (submission['displays_made'] * product['packages_per_display'] * product['tablets_per_package'] +
                           submission['packs_remaining'] * product['tablets_per_package'] +
                           submission['loose_tablets'])
        damaged_tablets = submission['damaged_tablets']
        
        # Remove counts from PO line if assigned
        if old_po_id and inventory_item_id:
            # Find the PO line
            po_line = conn.execute('''
                SELECT id FROM po_lines
                WHERE po_id = ? AND inventory_item_id = ?
                LIMIT 1
            ''', (old_po_id, inventory_item_id)).fetchone()
            
            if po_line:
                # Get current counts first to calculate new values
                current_line = conn.execute('''
                    SELECT good_count, damaged_count FROM po_lines WHERE id = ?
                ''', (po_line['id'],)).fetchone()
                
                new_good = max(0, (current_line['good_count'] or 0) - good_tablets)
                new_damaged = max(0, (current_line['damaged_count'] or 0) - damaged_tablets)
                
                # Remove counts from PO line
                conn.execute('''
                    UPDATE po_lines
                    SET good_count = ?, 
                        damaged_count = ?
                    WHERE id = ?
                ''', (new_good, new_damaged, po_line['id']))
                
                # Update PO header totals
                totals = conn.execute('''
                    SELECT 
                        COALESCE(SUM(quantity_ordered), 0) as total_ordered,
                        COALESCE(SUM(good_count), 0) as total_good,
                        COALESCE(SUM(damaged_count), 0) as total_damaged
                    FROM po_lines 
                    WHERE po_id = ?
                ''', (old_po_id,)).fetchone()
                
                remaining = totals['total_ordered'] - totals['total_good'] - totals['total_damaged']
                conn.execute('''
                    UPDATE purchase_orders 
                    SET ordered_quantity = ?, current_good_count = ?, 
                        current_damaged_count = ?, remaining_quantity = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (totals['total_ordered'], totals['total_good'], 
                      totals['total_damaged'], remaining, old_po_id))
        
        # Delete the submission
        conn.execute('DELETE FROM warehouse_submissions WHERE id = ?', (submission_id,))
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': 'Submission deleted successfully'
        })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ DELETE SUBMISSION ERROR: {str(e)}")
        print(error_trace)
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/po/<int:po_id>/delete', methods=['POST'])
@admin_required
def delete_po(po_id):
    """Delete a PO and all its related data (Admin only)"""
    conn = None
    try:
        conn = get_db()
        
        # Get PO details first
        po = conn.execute('SELECT po_number FROM purchase_orders WHERE id = ?', (po_id,)).fetchone()
        
        if not po:
            return jsonify({'success': False, 'error': 'PO not found'}), 404
        
        # Delete related data
        # 1. Unassign all submissions (don't delete submissions, just unassign them)
        conn.execute('UPDATE warehouse_submissions SET assigned_po_id = NULL WHERE assigned_po_id = ?', (po_id,))
        
        # 2. Delete shipments
        conn.execute('DELETE FROM shipments WHERE po_id = ?', (po_id,))
        
        # 3. Delete PO lines
        conn.execute('DELETE FROM po_lines WHERE po_id = ?', (po_id,))
        
        # 4. Delete the PO itself
        conn.execute('DELETE FROM purchase_orders WHERE id = ?', (po_id,))
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': f'Successfully deleted {po["po_number"]} and all related data'
        })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ DELETE PO ERROR: {str(e)}")
        print(error_trace)
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/resync_unassigned_submissions', methods=['POST'])
@admin_required
def resync_unassigned_submissions():
    """Resync unassigned submissions to try matching them with POs based on updated item IDs"""
    conn = None
    try:
        conn = get_db()
        
        # Get all unassigned submissions - convert to dicts immediately
        # Note: Use 'id' instead of 'rowid' for better compatibility
        unassigned_rows = conn.execute('''
            SELECT ws.id, ws.product_name, ws.displays_made, 
                   ws.packs_remaining, ws.loose_tablets, ws.damaged_tablets, ws.tablets_pressed_into_cards,
                   COALESCE(ws.submission_type, 'packaged') as submission_type
            FROM warehouse_submissions ws
            WHERE ws.assigned_po_id IS NULL
            ORDER BY ws.created_at DESC
        ''').fetchall()
        
        # Convert Row objects to dicts to avoid key access issues
        unassigned = [dict(row) for row in unassigned_rows]
        
        if not unassigned:
            conn.close()
            return jsonify({'success': True, 'message': 'No unassigned submissions found'})
        
        matched_count = 0
        updated_pos = set()
        
        for submission in unassigned:
            try:
                # Get the product's details including inventory_item_id
                # submission['product_name'] matches product_details.product_name
                # then join to tablet_types to get inventory_item_id
                product_row = conn.execute('''
                    SELECT tt.inventory_item_id, pd.packages_per_display, pd.tablets_per_package
                    FROM product_details pd
                    JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                    WHERE pd.product_name = ?
                ''', (submission['product_name'],)).fetchone()
                
                if not product_row:
                    # Try direct tablet_type match if no product_details entry
                    product_row = conn.execute('''
                        SELECT inventory_item_id, 0 as packages_per_display, 0 as tablets_per_package
                        FROM tablet_types
                        WHERE tablet_type_name = ?
                    ''', (submission['product_name'],)).fetchone()
                
                if not product_row:
                    print(f"⚠️  No product config found for: {submission['product_name']}")
                    continue
                
                # Convert to dict for safe access
                product = dict(product_row)
                inventory_item_id = product.get('inventory_item_id')
                
                if not inventory_item_id:
                    print(f"⚠️  No inventory_item_id for: {submission['product_name']}")
                    continue
            except Exception as e:
                if conn:
                    try:
                        conn.rollback()
                    except:
                        pass
                print(f"❌ Error processing submission {submission.get('id', 'unknown')}: {e}")
                continue
            
            # Find open PO lines for this inventory item
            # Order by PO number (oldest PO numbers first) since they represent issue order
            # Exclude Draft POs - only assign to Issued/Active POs
            # Note: We do NOT filter by available quantity - POs can receive more than ordered
            po_lines_rows = conn.execute('''
                SELECT pl.*, po.closed
                FROM po_lines pl
                JOIN purchase_orders po ON pl.po_id = po.id
                WHERE pl.inventory_item_id = ? AND po.closed = FALSE
                AND COALESCE(po.internal_status, '') != 'Draft'
                ORDER BY po.po_number ASC
            ''', (inventory_item_id,)).fetchall()
            
            # Convert to dicts
            po_lines = [dict(row) for row in po_lines_rows]
            
            if not po_lines:
                continue
            
            # Calculate good and damaged counts based on submission type
            submission_type = submission.get('submission_type', 'packaged')
            if submission_type == 'machine':
                good_tablets = submission.get('tablets_pressed_into_cards', 0) or 0
            else:
                packages_per_display = product.get('packages_per_display') or 0
                tablets_per_package = product.get('tablets_per_package') or 0
                good_tablets = (submission.get('displays_made', 0) * packages_per_display * tablets_per_package + 
                              submission.get('packs_remaining', 0) * tablets_per_package + 
                              submission.get('loose_tablets', 0))
                damaged_tablets = submission.get('damaged_tablets', 0)
            
            # Assign to first available PO
            assigned_po_id = po_lines[0]['po_id']
            conn.execute('''
                UPDATE warehouse_submissions 
                SET assigned_po_id = ?
                WHERE id = ?
            ''', (assigned_po_id, submission['id']))
            
            # Allocate counts to PO lines
            # Note: We do NOT cap at ordered quantity - actual production may exceed the PO
            line = po_lines[0]
            
            # Apply all counts to the first line
            conn.execute('''
                UPDATE po_lines 
                SET good_count = good_count + ?, damaged_count = damaged_count + ?
                WHERE id = ?
            ''', (good_tablets, damaged_tablets, line['id']))
            
            updated_pos.add(line['po_id'])
            
            matched_count += 1
        
        # Update PO header totals for all affected POs
        for po_id in updated_pos:
            totals_row = conn.execute('''
                SELECT 
                    COALESCE(SUM(quantity_ordered), 0) as total_ordered,
                    COALESCE(SUM(good_count), 0) as total_good,
                    COALESCE(SUM(damaged_count), 0) as total_damaged
                FROM po_lines 
                WHERE po_id = ?
            ''', (po_id,)).fetchone()
            
            # Convert to dict
            totals = dict(totals_row)
            remaining = totals.get('total_ordered', 0) - totals.get('total_good', 0) - totals.get('total_damaged', 0)
            
            conn.execute('''
                UPDATE purchase_orders 
                SET ordered_quantity = ?, current_good_count = ?, 
                    current_damaged_count = ?, remaining_quantity = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (totals.get('total_ordered', 0), totals.get('total_good', 0), 
                  totals.get('total_damaged', 0), remaining, po_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': f'Successfully matched {matched_count} of {len(unassigned)} unassigned submissions to POs',
            'matched': matched_count,
            'total_unassigned': len(unassigned)
        })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌❌❌ RESYNC ERROR: {str(e)}")
        print(error_trace)
        if conn:
            try:
                conn.close()
            except:
                pass
        return jsonify({'error': str(e), 'trace': error_trace}), 500



@bp.route('/api/po/<int:po_id>/receives', methods=['GET'])
@role_required('dashboard')
def get_po_receives(po_id):
    """Get all receives (shipments received) for a specific PO"""
    conn = None
    try:
        conn = get_db()
        
        # Get PO details
        po = conn.execute('''
            SELECT po_number
            FROM purchase_orders
            WHERE id = ?
        ''', (po_id,)).fetchone()
        
        if not po:
            return jsonify({'error': 'PO not found'}), 404
        
        # Get all receiving records for this PO with their boxes and bags
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
        
        # Calculate shipment numbers for each receive (numbered sequentially by received_date, matching receiving page)
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
        
        # For each receiving record, get its boxes and bags
        receives = []
        for rec in receiving_records:
            # Add shipment number (matching receiving page logic)
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
            
            # Get bags for each box with tablet type info
            boxes_with_bags = []
            for box in boxes:
                box_dict = dict(box)
                bags = conn.execute('''
                    SELECT b.*, tt.tablet_type_name
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
        if conn:
            try:
                conn.rollback()
            except:
                pass
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/api/po/<int:po_id>/submissions', methods=['GET'])
@role_required('dashboard')
def get_po_submissions(po_id):
    """Get all submissions assigned to a specific PO"""
    conn = None
    try:
        conn = get_db()
        
        # Get PO details including machine counts
        po_row = conn.execute('''
            SELECT po_number, tablet_type, ordered_quantity, 
                   current_good_count, current_damaged_count, remaining_quantity,
                   machine_good_count, machine_damaged_count,
                   parent_po_number
            FROM purchase_orders
            WHERE id = ?
        ''', (po_id,)).fetchone()
        
        if not po_row:
            return jsonify({'error': 'PO not found'}), 404
        
        po = dict(po_row)
        
        # Check if submission_date and submission_type columns exist
        has_submission_date = False
        has_submission_type = False
        try:
            conn.execute('SELECT submission_date FROM warehouse_submissions LIMIT 1')
            has_submission_date = True
        except:
            pass
        try:
            conn.execute('SELECT submission_type FROM warehouse_submissions LIMIT 1')
            has_submission_type = True
        except:
            pass
        
        # For PO-specific views, show ALL submissions for auditing purposes
        
        # Determine which PO IDs to query:
        # 1. If this is a parent PO, also include submissions from related OVERS POs
        # 2. If this is an OVERS PO, also include submissions from the parent PO
        po_ids_to_query = [po_id]
        po_number = po.get('po_number')
        
        # Check if this is a parent PO - find related OVERS POs
        overs_pos = conn.execute('''
            SELECT id FROM purchase_orders 
            WHERE parent_po_number = ?
        ''', (po_number,)).fetchall()
        for overs_po_row in overs_pos:
            overs_po = dict(overs_po_row)
            po_ids_to_query.append(overs_po.get('id'))
        
        # Check if this is an OVERS PO - find parent PO
        if po.get('parent_po_number'):
            parent_po_row = conn.execute('''
                SELECT id FROM purchase_orders 
                WHERE po_number = ?
            ''', (po.get('parent_po_number'),)).fetchone()
            if parent_po_row:
                parent_po = dict(parent_po_row)
                parent_po_id = parent_po.get('id')
                if parent_po_id and parent_po_id not in po_ids_to_query:
                    po_ids_to_query.append(parent_po_id)
        
        # Build WHERE clause for multiple PO IDs
        po_ids_placeholders = ','.join(['?'] * len(po_ids_to_query))
        
        # Get all submissions for this PO (and related OVERS/parent POs) with product details
        # Include inventory_item_id for matching with PO line items
        # PO is source of truth - only include submissions where assigned_po_id matches
        submission_type_select = ', ws.submission_type' if has_submission_type else ", 'packaged' as submission_type"
        po_verified_select = ', COALESCE(ws.po_assignment_verified, 0) as po_verified' if has_submission_type else ", 0 as po_verified"
        if has_submission_date:
            submissions_query = f'''
                SELECT DISTINCT
                    ws.id,
                    ws.product_name,
                    ws.employee_name,
                    ws.displays_made,
                    ws.packs_remaining,
                    ws.loose_tablets,
                    ws.damaged_tablets,
                    ws.created_at,
                    ws.submission_date,
                    ws.box_number,
                    ws.bag_number,
                    ws.bag_id,
                    COALESCE(b.bag_label_count, ws.bag_label_count, 0) as bag_label_count,
                    ws.admin_notes,
                    pd.packages_per_display,
                    COALESCE(pd.tablets_per_package, pd_fallback.tablets_per_package) as tablets_per_package,
                    tt.inventory_item_id,
                    ws.assigned_po_id,
                    po.po_number,
                    po.closed as po_closed
                    {submission_type_select}
                    {po_verified_select}
                FROM warehouse_submissions ws
                LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                LEFT JOIN tablet_types tt_fallback ON ws.inventory_item_id = tt_fallback.inventory_item_id
                LEFT JOIN product_details pd_fallback ON tt_fallback.id = pd_fallback.tablet_type_id
                LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
                LEFT JOIN bags b ON ws.bag_id = b.id
                WHERE ws.assigned_po_id IN ({po_ids_placeholders})
                ORDER BY ws.created_at ASC
            '''
        else:
            submissions_query = f'''
                SELECT DISTINCT
                    ws.id,
                    ws.product_name,
                    ws.employee_name,
                    ws.displays_made,
                    ws.packs_remaining,
                    ws.loose_tablets,
                    ws.damaged_tablets,
                    ws.created_at,
                    ws.created_at as submission_date,
                    ws.box_number,
                    ws.bag_number,
                    ws.bag_id,
                    COALESCE(b.bag_label_count, ws.bag_label_count, 0) as bag_label_count,
                    ws.admin_notes,
                    pd.packages_per_display,
                    COALESCE(pd.tablets_per_package, pd_fallback.tablets_per_package) as tablets_per_package,
                    tt.inventory_item_id,
                    ws.assigned_po_id,
                    po.po_number,
                    po.closed as po_closed
                    {submission_type_select}
                    {po_verified_select}
                FROM warehouse_submissions ws
                LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                LEFT JOIN tablet_types tt_fallback ON ws.inventory_item_id = tt_fallback.inventory_item_id
                LEFT JOIN product_details pd_fallback ON tt_fallback.id = pd_fallback.tablet_type_id
                LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
                LEFT JOIN bags b ON ws.bag_id = b.id
                WHERE ws.assigned_po_id IN ({po_ids_placeholders})
                ORDER BY ws.created_at ASC
            '''
        
        # Execute query with PO IDs
        submissions_raw = conn.execute(submissions_query, tuple(po_ids_to_query)).fetchall()
        print(f"🔍 get_po_submissions: Found {len(submissions_raw)} submissions for PO {po_id} ({po_number}) including related POs: {po_ids_to_query}")
        
        # Calculate total tablets and running bag totals for each submission
        # Also calculate separate totals for machine vs packaged+bag counts
        bag_running_totals = {}
        submissions = []
        machine_total = 0
        packaged_total = 0
        bag_total = 0
        
        for sub in submissions_raw:
            sub_dict = dict(sub)
            submission_type = sub_dict.get('submission_type', 'packaged')
            
            # Calculate total tablets for this submission
            if submission_type == 'machine':
                # For machine submissions: use tablets_pressed_into_cards (fallback to loose_tablets, then calculate from cards_made)
                total_tablets = (sub_dict.get('tablets_pressed_into_cards') or 
                               sub_dict.get('loose_tablets') or
                               ((sub_dict.get('packs_remaining', 0) or 0) * (sub_dict.get('tablets_per_package', 0) or 0)) or
                               0)
            else:
                # For other submissions: calculate from displays, packs, loose, and damaged
                displays_tablets = (sub_dict.get('displays_made', 0) or 0) * (sub_dict.get('packages_per_display', 0) or 0) * (sub_dict.get('tablets_per_package', 0) or 0)
                package_tablets = (sub_dict.get('packs_remaining', 0) or 0) * (sub_dict.get('tablets_per_package', 0) or 0)
                loose_tablets = sub_dict.get('loose_tablets', 0) or 0
                damaged_tablets = sub_dict.get('damaged_tablets', 0) or 0
                total_tablets = displays_tablets + package_tablets + loose_tablets + damaged_tablets
            
            sub_dict['total_tablets'] = total_tablets
            
            # Track totals separately by submission type
            if submission_type == 'machine':
                machine_total += total_tablets
            elif submission_type == 'packaged':
                packaged_total += total_tablets
            elif submission_type == 'bag':
                bag_total += total_tablets
            # Bag counts are separate from packaged counts - they're just inventory counts, not production
            
            # Calculate running total by bag PER PO (only for packaged submissions, NOT bag counts)
            if submission_type == 'packaged':
                bag_identifier = f"{sub_dict.get('box_number', '')}/{sub_dict.get('bag_number', '')}"
                # Key includes PO ID so each PO tracks its own bag totals independently
                bag_key = (po_id, sub_dict.get('product_name', ''), bag_identifier)
                if bag_key not in bag_running_totals:
                    bag_running_totals[bag_key] = 0
                bag_running_totals[bag_key] += total_tablets
                sub_dict['running_total'] = bag_running_totals[bag_key]
                
                # Determine count status (only for packaged submissions)
                # Check if bag_id is NULL, not just bag_label_count
                # A bag can exist with label_count=0, but if bag_id is NULL, there's no bag assigned
                if not sub_dict.get('bag_id'):
                    sub_dict['count_status'] = 'no_bag'
                else:
                    bag_count = sub_dict.get('bag_label_count', 0) or 0
                    if abs(bag_running_totals[bag_key] - bag_count) <= 5:
                        sub_dict['count_status'] = 'match'
                    elif bag_running_totals[bag_key] < bag_count:
                        sub_dict['count_status'] = 'under'
                    else:
                        sub_dict['count_status'] = 'over'
            elif submission_type == 'bag':
                # Bag counts don't have running totals - they're just inventory counts
                sub_dict['running_total'] = total_tablets
                sub_dict['count_status'] = None
            else:
                # Machine counts don't have bag running totals
                sub_dict['running_total'] = total_tablets
                sub_dict['count_status'] = None
            
            submissions.append(sub_dict)
        
        # Reverse to show newest first in modal
        submissions.reverse()
        
        return jsonify({
            'success': True,
            'po': dict(po),
            'submissions': submissions,
            'count': len(submissions),
            'totals': {
                'machine': machine_total,
                'packaged': packaged_total,
                'bag': bag_total,
                'total': machine_total + packaged_total + bag_total
            }
        })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        import traceback
        error_trace = traceback.format_exc()
        print(f"❌ Error fetching PO submissions: {str(e)}")
        print(error_trace)
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

# ===== TEMPLATE CONTEXT PROCESSORS =====

@bp.app_template_filter('to_est')
def to_est_filter(dt_string):
    """Convert UTC datetime string to Eastern Time (EST/EDT)"""
    if not dt_string:
        return 'N/A'
    try:
        # Parse the datetime string (assumes UTC)
        if isinstance(dt_string, str):
            # Handle date-only strings (YYYY-MM-DD)
            if re.match(r'^\d{4}-\d{2}-\d{2}$', dt_string):
                return dt_string  # Return date-only as-is
            
            # Handle different datetime formats
            if '.' in dt_string:
                dt = datetime.strptime(dt_string.split('.')[0], '%Y-%m-%d %H:%M:%S')
            else:
                dt = datetime.strptime(dt_string, '%Y-%m-%d %H:%M:%S')
            # Assume UTC if no timezone info in string
            utc_dt = dt.replace(tzinfo=ZoneInfo('UTC'))
        else:
            # Already a datetime object
            dt = dt_string
            if dt.tzinfo is None:
                # Naive datetime - assume UTC (from database)
                utc_dt = dt.replace(tzinfo=ZoneInfo('UTC'))
            else:
                # Already has timezone - convert to UTC first if needed
                utc_dt = dt.astimezone(ZoneInfo('UTC'))
        
        # Convert from UTC to Eastern
        est_dt = utc_dt.astimezone(ZoneInfo('America/New_York'))
        
        # Format as YYYY-MM-DD HH:MM:SS
        return est_dt.strftime('%Y-%m-%d %H:%M:%S')
    except Exception as e:
        print(f"Error converting datetime to EST: {e}")
        return dt_string if isinstance(dt_string, str) else 'N/A'

@bp.app_template_filter('to_est_time')
def to_est_time_filter(dt_string):
    """Convert UTC datetime string to Eastern Time, showing only time portion"""
    if not dt_string:
        return 'N/A'
    try:
        # Parse the datetime string (assumes UTC)
        if isinstance(dt_string, str):
            # Handle date-only strings (YYYY-MM-DD) - return N/A for time-only display
            if re.match(r'^\d{4}-\d{2}-\d{2}$', dt_string):
                return 'N/A'  # No time component for date-only strings
            
            # Handle different datetime formats
            if '.' in dt_string:
                dt = datetime.strptime(dt_string.split('.')[0], '%Y-%m-%d %H:%M:%S')
            else:
                dt = datetime.strptime(dt_string, '%Y-%m-%d %H:%M:%S')
            # Assume UTC if no timezone info in string
            utc_dt = dt.replace(tzinfo=ZoneInfo('UTC'))
        else:
            # Already a datetime object
            dt = dt_string
            if dt.tzinfo is None:
                # Naive datetime - assume UTC (from database)
                utc_dt = dt.replace(tzinfo=ZoneInfo('UTC'))
            else:
                # Already has timezone - convert to UTC first if needed
                utc_dt = dt.astimezone(ZoneInfo('UTC'))
        
        # Convert from UTC to Eastern
        est_dt = utc_dt.astimezone(ZoneInfo('America/New_York'))
        
        # Format as HH:MM:SS
        return est_dt.strftime('%H:%M:%S')
    except Exception as e:
        print(f"Error converting datetime to EST: {e}")
        if isinstance(dt_string, str):
            # Fallback: try to extract time portion
            parts = dt_string.split(' ')
            if len(parts) > 1:
                return parts[1].split('.')[0] if '.' in parts[1] else parts[1]
        return 'N/A'

@bp.app_context_processor
def inject_version():
    """Make version information available to all templates"""
    locale = get_locale()
    # Convert Locale object to string if needed
    current_lang = str(locale) if hasattr(locale, 'language') else locale
    return {
        'version': lambda: __version__,
        'app_title': __title__,
        'app_description': __description__,
        'current_language': current_lang,
        'languages': current_app.config['LANGUAGES'],
        'gettext': gettext,
        'ngettext': ngettext
    }

@bp.route('/api/machines', methods=['GET'])
@employee_required  # Employees need to see machines to submit counts
def get_machines():
    """Get all machines"""
    conn = None
    try:
        conn = get_db()
        machines = conn.execute('''
            SELECT * FROM machines 
            WHERE is_active = TRUE
            ORDER BY machine_name
        ''').fetchall()
        
        machines_list = [dict(m) for m in machines]
        current_app.logger.info(f"🔧 GET /api/machines - Found {len(machines_list)} active machines")
        for m in machines_list:
            current_app.logger.info(f"   Machine: {m.get('machine_name')} (ID: {m.get('id')}, cards_per_turn: {m.get('cards_per_turn')})")
        return jsonify({'success': True, 'machines': machines_list})
    except Exception as e:
        current_app.logger.error(f"❌ GET /api/machines error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


@bp.route('/api/machines', methods=['POST'])
@admin_required
def create_machine():
    """Create a new machine"""
    conn = None
    try:
        data = request.get_json()
        machine_name = data.get('machine_name', '').strip()
        cards_per_turn = data.get('cards_per_turn')
        
        if not machine_name:
            return jsonify({'success': False, 'error': 'Machine name is required'}), 400
        
        try:
            cards_per_turn = int(cards_per_turn)
            if cards_per_turn < 1:
                return jsonify({'success': False, 'error': 'Cards per turn must be at least 1'}), 400
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid cards per turn value'}), 400
        
        conn = get_db()
        
        # Check if machine name already exists
        existing = conn.execute('SELECT id FROM machines WHERE machine_name = ?', (machine_name,)).fetchone()
        if existing:
            return jsonify({'success': False, 'error': 'Machine name already exists'}), 400
        
        # Create machine
        conn.execute('''
            INSERT INTO machines (machine_name, cards_per_turn, is_active)
            VALUES (?, ?, TRUE)
        ''', (machine_name, cards_per_turn))
        
        conn.commit()
        return jsonify({'success': True, 'message': f'Machine "{machine_name}" created successfully'})
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


@bp.route('/api/machines/<int:machine_id>', methods=['PUT'])
@admin_required
def update_machine(machine_id):
    """Update a machine's configuration"""
    conn = None
    try:
        data = request.get_json()
        machine_name = data.get('machine_name', '').strip()
        cards_per_turn = data.get('cards_per_turn')
        
        if not machine_name:
            return jsonify({'success': False, 'error': 'Machine name is required'}), 400
        
        try:
            cards_per_turn = int(cards_per_turn)
            if cards_per_turn < 1:
                return jsonify({'success': False, 'error': 'Cards per turn must be at least 1'}), 400
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid cards per turn value'}), 400
        
        conn = get_db()
        
        # Check if machine exists
        machine = conn.execute('SELECT id FROM machines WHERE id = ?', (machine_id,)).fetchone()
        if not machine:
            return jsonify({'success': False, 'error': 'Machine not found'}), 404
        
        # Check if new name conflicts with another machine
        existing = conn.execute('SELECT id FROM machines WHERE machine_name = ? AND id != ?', (machine_name, machine_id)).fetchone()
        if existing:
            return jsonify({'success': False, 'error': 'Machine name already exists'}), 400
        
        # Update machine
        conn.execute('''
            UPDATE machines 
            SET machine_name = ?, cards_per_turn = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (machine_name, cards_per_turn, machine_id))
        
        conn.commit()
        return jsonify({'success': True, 'message': f'Machine "{machine_name}" updated successfully'})
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


@bp.route('/api/machines/<int:machine_id>', methods=['DELETE'])
@admin_required
def delete_machine(machine_id):
    """Soft delete a machine (set is_active = FALSE)"""
    conn = None
    try:
        conn = get_db()
        
        # Check if machine exists
        machine = conn.execute('SELECT machine_name FROM machines WHERE id = ?', (machine_id,)).fetchone()
        if not machine:
            return jsonify({'success': False, 'error': 'Machine not found'}), 404
        
        # Soft delete (don't actually delete - just mark inactive)
        conn.execute('''
            UPDATE machines 
            SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (machine_id,))
        
        conn.commit()
        return jsonify({'success': True, 'message': f'Machine "{machine["machine_name"]}" deleted successfully'})
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


@bp.route('/api/receives/list', methods=['GET'])
@role_required('dashboard')
def get_receives_list():
    """Get list of all receives for reporting"""
    conn = None
    try:
        conn = get_db()
        
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
            # Use stored receive_name, or build it if missing (for legacy records)
            if not receive_dict.get('receive_name') and receive_dict.get('po_number'):
                # Calculate receive_number for legacy records
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
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


@bp.route('/api/submission/<int:submission_id>', methods=['DELETE'])
@role_required('dashboard')
def delete_submission_alt(submission_id):
    """Delete a submission (for removing duplicates) - DELETE method"""
    conn = None
    try:
        conn = get_db()
        
        # Check if submission exists
        submission = conn.execute('''
            SELECT id FROM warehouse_submissions WHERE id = ?
        ''', (submission_id,)).fetchone()
        
        if not submission:
            return jsonify({'success': False, 'error': 'Submission not found'}), 404
        
        # Delete the submission
        conn.execute('DELETE FROM warehouse_submissions WHERE id = ?', (submission_id,))
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': 'Submission deleted successfully'
        })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


@bp.route('/api/submission/<int:submission_id>/possible-receives', methods=['GET'])
@role_required('dashboard')
def get_possible_receives(submission_id):
    """Get all possible receives that match a submission's flavor, box, bag"""
    conn = None
    try:
        conn = get_db()
        
        # Get submission details
        submission = conn.execute('''
            SELECT ws.*, tt.id as tablet_type_id, tt.tablet_type_name
            FROM warehouse_submissions ws
            LEFT JOIN tablet_types tt ON ws.inventory_item_id = tt.inventory_item_id
            WHERE ws.id = ?
        ''', (submission_id,)).fetchone()
        
        if not submission:
            return jsonify({'success': False, 'error': 'Submission not found'}), 404
        
        # Convert Row to dict for easier access
        submission_dict = dict(submission)
        
        # Debug logging
        print(f"🔍 Finding possible receives for submission {submission_id}")
        print(f"   tablet_type_id: {submission_dict.get('tablet_type_id')}")
        print(f"   box_number: {submission_dict.get('box_number')}")
        print(f"   bag_number: {submission_dict.get('bag_number')}")
        print(f"   inventory_item_id: {submission_dict.get('inventory_item_id')}")
        
        if not submission_dict.get('bag_number'):
            return jsonify({
                'success': False, 
                'error': 'Submission missing bag_number. Cannot find matching receives.'
            }), 400
        
        # Box number is optional for flavor-based receives
        # Normalize empty strings/None to None for proper flavor-based matching
        box_number_raw = submission_dict.get('box_number')
        box_number = box_number_raw if (box_number_raw and str(box_number_raw).strip()) else None
        
        # Get tablet_type_id - if not found via JOIN, try to get it from inventory_item_id
        tablet_type_id = submission_dict.get('tablet_type_id')
        if not tablet_type_id and submission_dict.get('inventory_item_id'):
            # Try to get tablet_type_id from inventory_item_id
            tt_row = conn.execute('''
                SELECT id FROM tablet_types WHERE inventory_item_id = ?
            ''', (submission_dict.get('inventory_item_id'),)).fetchone()
            if tt_row:
                tablet_type_id = tt_row['id']
                print(f"   Found tablet_type_id via inventory_item_id lookup: {tablet_type_id}")
        
        if not tablet_type_id:
            return jsonify({
                'success': False,
                'error': f'Could not determine tablet_type_id for submission. Product: {submission_dict.get("product_name")}, inventory_item_id: {submission_dict.get("inventory_item_id")}'
            }), 400
        
        # Find all matching bags - must match find_bag_for_submission logic
        # If box_number provided: match with box (old style)
        # If box_number is None: match without box (new flavor-based style)
        if box_number is not None:
            matching_bags = conn.execute('''
                SELECT b.id as bag_id, 
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
                WHERE b.tablet_type_id = ? 
                AND sb.box_number = ? 
                AND b.bag_number = ?
                ORDER BY r.received_date DESC
            ''', (tablet_type_id, box_number, submission_dict['bag_number'])).fetchall()
        else:
            # New flavor-based: match without box number
            matching_bags = conn.execute('''
                SELECT b.id as bag_id, 
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
                WHERE b.tablet_type_id = ? 
                AND b.bag_number = ?
                ORDER BY r.received_date DESC
            ''', (tablet_type_id, submission_dict['bag_number'])).fetchall()
        
        print(f"   Found {len(matching_bags)} matching bags")
        
        # Build receive_name using stored receive_name from database
        receives = []
        for bag_row in matching_bags:
            # Convert Row to dict for .get() access
            bag = dict(bag_row)
            
            # Use stored receive_name and append box-bag
            stored_receive_name = bag.get('stored_receive_name')
            if stored_receive_name and bag['box_number'] is not None and bag['bag_number'] is not None:
                receive_name = f"{stored_receive_name}-{bag['box_number']}-{bag['bag_number']}"
            else:
                # Fallback for legacy records: calculate receive_number dynamically
                receive_number = conn.execute('''
                    SELECT COUNT(*) + 1
                    FROM receiving r2
                    WHERE r2.po_id = ?
                    AND (r2.received_date < (SELECT received_date FROM receiving WHERE id = ?)
                         OR (r2.received_date = (SELECT received_date FROM receiving WHERE id = ?) 
                             AND r2.id < ?))
                ''', (bag['po_id'], bag['receive_id'], bag['receive_id'], bag['receive_id'])).fetchone()[0]
                receive_name = f"{bag['po_number']}-{receive_number}-{bag['box_number']}-{bag['bag_number']}"
            
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
            'possible_receives': receives
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


@bp.route('/api/submission/<int:submission_id>/assign-receive', methods=['POST'])
@role_required('dashboard')
def assign_submission_to_receive(submission_id):
    """Assign a submission to a specific receive bag"""
    conn = None
    try:
        conn = get_db()
        data = request.get_json()
        bag_id = data.get('bag_id')
        
        if not bag_id:
            return jsonify({'success': False, 'error': 'bag_id is required'}), 400
        
        # Get bag details
        bag = conn.execute('''
            SELECT b.*, r.po_id
            FROM bags b
            JOIN small_boxes sb ON b.small_box_id = sb.id
            JOIN receiving r ON sb.receiving_id = r.id
            WHERE b.id = ?
        ''', (bag_id,)).fetchone()
        
        if not bag:
            return jsonify({'success': False, 'error': 'Bag not found'}), 404
        
        # Update submission
        conn.execute('''
            UPDATE warehouse_submissions
            SET bag_id = ?, assigned_po_id = ?, needs_review = FALSE
            WHERE id = ?
        ''', (bag_id, bag['po_id'], submission_id))
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': 'Submission assigned successfully'
        })
        
    except Exception as e:
        traceback.print_exc()
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


@bp.route('/api/admin/diagnose-submissions/<int:receive_id>', methods=['GET'])
@admin_required
def diagnose_submissions(receive_id):
    """Diagnose submission assignments for a specific receive"""
    conn = None
    try:
        conn = get_db()
        
        # Get receive info
        receive = conn.execute('''
            SELECT r.*, po.po_number
            FROM receiving r
            JOIN purchase_orders po ON r.po_id = po.id
            WHERE r.id = ?
        ''', (receive_id,)).fetchone()
        
        if not receive:
            return jsonify({'error': 'Receive not found'}), 404
        
        receive_dict = dict(receive)
        
        # Get all bags for this receive
        bags = conn.execute('''
            SELECT b.id as bag_id, b.bag_number, sb.box_number, b.bag_label_count,
                   tt.tablet_type_name, tt.inventory_item_id
            FROM bags b
            JOIN small_boxes sb ON b.small_box_id = sb.id
            JOIN tablet_types tt ON b.tablet_type_id = tt.id
            WHERE sb.receiving_id = ?
            ORDER BY sb.box_number, b.bag_number
        ''', (receive_id,)).fetchall()
        
        bag_info = []
        for bag in bags:
            bag_dict = dict(bag)
            
            # Find submissions that SHOULD be assigned to this bag
            submissions_by_bag_id = conn.execute('''
                SELECT id, submission_type, employee_name, product_name, created_at
                FROM warehouse_submissions
                WHERE bag_id = ?
            ''', (bag_dict['bag_id'],)).fetchall()
            
            # Find submissions with matching box/bag but different bag_id
            submissions_by_numbers = conn.execute('''
                SELECT id, submission_type, employee_name, product_name, bag_id, created_at
                FROM warehouse_submissions
                WHERE assigned_po_id = ?
                AND box_number = ?
                AND bag_number = ?
                AND (bag_id IS NULL OR bag_id != ?)
            ''', (receive_dict['po_id'], bag_dict['box_number'], bag_dict['bag_number'], bag_dict['bag_id'])).fetchall()
            
            bag_info.append({
                'bag_id': bag_dict['bag_id'],
                'box_bag': f"{bag_dict['box_number']}/{bag_dict['bag_number']}",
                'tablet_type': bag_dict['tablet_type_name'],
                'submissions_by_bag_id': [dict(s) for s in submissions_by_bag_id],
                'submissions_with_wrong_bag_id': [dict(s) for s in submissions_by_numbers]
            })
        
        return jsonify({
            'success': True,
            'receive': receive_dict,
            'bags': bag_info
        })
        
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


@bp.route('/api/admin/fix-bag-assignments', methods=['POST'])
@admin_required
def fix_bag_assignments():
    """
    Admin endpoint to fix bag_id assignments for submissions.
    Updates submissions to have the correct bag_id based on their box_number, bag_number, and assigned_po_id.
    """
    conn = None
    try:
        conn = get_db()
        
        # Find all submissions that need bag_id updates
        submissions = conn.execute('''
            SELECT ws.id, ws.box_number, ws.bag_number, ws.assigned_po_id, ws.bag_id as current_bag_id,
                   ws.product_name, ws.employee_name, ws.submission_type
            FROM warehouse_submissions ws
            WHERE ws.assigned_po_id IS NOT NULL
            AND ws.box_number IS NOT NULL
            AND ws.bag_number IS NOT NULL
            ORDER BY ws.assigned_po_id, ws.box_number, ws.bag_number
        ''').fetchall()
        
        updated_count = 0
        skipped_count = 0
        no_bag_found = 0
        multiple_bags_found = 0
        updates = []
        
        for sub in submissions:
            sub_dict = dict(sub)
            
            # Find ALL bags that match this box/bag/PO combination AND have the same inventory_item_id
            # This ensures submissions only go to bags with the SAME tablet type
            bag_rows = conn.execute('''
                SELECT b.id as bag_id, r.id as receive_id, r.receive_name, tt.tablet_type_name
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                JOIN tablet_types tt ON b.tablet_type_id = tt.id
                WHERE r.po_id = ?
                AND sb.box_number = ?
                AND b.bag_number = ?
                AND tt.inventory_item_id = (
                    SELECT inventory_item_id FROM tablet_types 
                    WHERE inventory_item_id = ?
                    LIMIT 1
                )
                ORDER BY r.received_date DESC, r.id DESC
            ''', (sub_dict['assigned_po_id'], sub_dict['box_number'], sub_dict['bag_number'], 
                  # Get inventory_item_id from submission
                  conn.execute('SELECT inventory_item_id FROM warehouse_submissions WHERE id = ?', 
                              (sub_dict['id'],)).fetchone()[0])).fetchall()
            
            if len(bag_rows) == 1:
                # Only one bag matches - safe to update
                bag_dict = dict(bag_rows[0])
                correct_bag_id = bag_dict['bag_id']
                
                if sub_dict['current_bag_id'] != correct_bag_id:
                    conn.execute('''
                        UPDATE warehouse_submissions
                        SET bag_id = ?
                        WHERE id = ?
                    ''', (correct_bag_id, sub_dict['id']))
                    
                    updates.append({
                        'submission_id': sub_dict['id'],
                        'type': sub_dict['submission_type'],
                        'product': sub_dict['product_name'],
                        'box_bag': f"{sub_dict['box_number']}/{sub_dict['bag_number']}",
                        'old_bag_id': sub_dict['current_bag_id'],
                        'new_bag_id': correct_bag_id,
                        'receive': bag_dict['receive_name']
                    })
                    updated_count += 1
                else:
                    skipped_count += 1
            elif len(bag_rows) > 1:
                # Multiple bags match - ambiguous, skip
                multiple_bags_found += 1
                updates.append({
                    'submission_id': sub_dict['id'],
                    'type': sub_dict['submission_type'],
                    'product': sub_dict['product_name'],
                    'box_bag': f"{sub_dict['box_number']}/{sub_dict['bag_number']}",
                    'old_bag_id': sub_dict['current_bag_id'],
                    'status': 'AMBIGUOUS',
                    'message': f'Found {len(bag_rows)} matching bags - needs manual review',
                    'possible_bags': [{'bag_id': dict(b)['bag_id'], 'receive': dict(b)['receive_name']} for b in bag_rows]
                })
            else:
                no_bag_found += 1
        
        conn.commit()
        
        return jsonify({
            'success': True,
            'message': f'Fixed {updated_count} bag assignments',
            'updated': updated_count,
            'skipped': skipped_count,
            'no_bag_found': no_bag_found,
            'multiple_bags_found': multiple_bags_found,
            'updates': updates
        })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        import traceback
        print(f"❌ FIX BAG ASSIGNMENTS ERROR: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


# Note: This blueprint is registered in app/__init__.py
# To run the application, use: flask run or python app.py
