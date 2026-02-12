"""
Submission-related API endpoints
"""
from flask import Blueprint, request, jsonify, session, current_app
from datetime import datetime
import traceback
from app.utils.db_utils import db_read_only, db_transaction
from app.utils.auth_utils import admin_required, role_required
from app.utils.receive_tracking import find_bag_for_submission

bp = Blueprint('api_submissions', __name__)


@bp.route('/api/bag/<int:bag_id>/submissions', methods=['GET'])
@role_required('dashboard')
def get_bag_submissions(bag_id):
    """Get all submissions for a specific bag (for duplicate review)"""
    try:
        with db_read_only() as conn:
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
            # Get raw submissions - we'll calculate each one individually with its own config
            submissions = conn.execute('''
                SELECT ws.*
                FROM warehouse_submissions ws
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
            
            # Calculate total_tablets for each submission using its specific product_name
            submissions_with_totals = []
            for row in submissions:
                sub = dict(row)
                submission_type = sub.get('submission_type') or 'packaged'
                product_name = sub.get('product_name')
                
                # Get config for THIS specific submission's product_name
                config = None
                if product_name:
                    # Try exact match first
                    config = conn.execute('''
                        SELECT packages_per_display, tablets_per_package, tablets_per_bottle
                        FROM product_details
                        WHERE product_name = ?
                    ''', (product_name,)).fetchone()
                    
                    # If no match, try case-insensitive with trimmed spaces
                    if not config:
                        config = conn.execute('''
                            SELECT packages_per_display, tablets_per_package, tablets_per_bottle
                            FROM product_details
                            WHERE TRIM(LOWER(product_name)) = TRIM(LOWER(?))
                        ''', (product_name,)).fetchone()
                
                # Fallback to inventory_item_id if product_name lookup fails
                if not config and sub.get('inventory_item_id'):
                    config = conn.execute('''
                        SELECT pd.packages_per_display, pd.tablets_per_package, pd.tablets_per_bottle
                        FROM tablet_types tt
                        LEFT JOIN product_details pd ON tt.id = pd.tablet_type_id
                        WHERE tt.inventory_item_id = ?
                        AND pd.id IS NOT NULL
                        ORDER BY 
                            CASE WHEN pd.is_bottle_product = 1 THEN 1 ELSE 0 END,
                            pd.packages_per_display DESC NULLS LAST
                        LIMIT 1
                    ''', (sub.get('inventory_item_id'),)).fetchone()
                
                # Extract config values
                ppd = 0
                tpp = 0
                tpb = 0
                if config:
                    config = dict(config)
                    ppd = config.get('packages_per_display') or 0
                    tpp = config.get('tablets_per_package') or 0
                    tpb = config.get('tablets_per_bottle') or 0
                
                # Calculate total based on submission type
                if submission_type == 'packaged':
                    displays = sub.get('displays_made') or 0
                    cards = sub.get('packs_remaining') or 0
                    total = (displays * ppd * tpp) + (cards * tpp)
                elif submission_type == 'bag':
                    total = sub.get('loose_tablets') or 0
                elif submission_type == 'machine':
                    tablets_pressed = sub.get('tablets_pressed_into_cards') or 0
                    cards = sub.get('packs_remaining') or 0
                    total = tablets_pressed or (cards * tpp)
                elif submission_type == 'bottle':
                    deductions = conn.execute('SELECT SUM(tablets_deducted) as total FROM submission_bag_deductions WHERE submission_id = ?', (sub['id'],)).fetchone()
                    if deductions and deductions['total']:
                        total = deductions['total']
                    else:
                        bottles = sub.get('bottles_made') or 0
                        total = bottles * tpb
                else:
                    total = 0
                
                sub['total_tablets'] = total
                submissions_with_totals.append(sub)
            
            current_app.logger.info(f"   Matched {len(submissions_with_totals)} direct submissions")
            
            # Also get variety pack deductions via junction table
            variety_pack_deductions = conn.execute('''
                SELECT sbd.id, sbd.submission_id, sbd.bag_id, sbd.tablets_deducted, sbd.created_at,
                       ws.employee_name, ws.product_name, ws.bottles_made, ws.displays_made,
                       ws.submission_date, ws.submission_type
                FROM submission_bag_deductions sbd
                JOIN warehouse_submissions ws ON sbd.submission_id = ws.id
                WHERE sbd.bag_id = ?
                ORDER BY sbd.created_at DESC
            ''', (bag_id,)).fetchall()
            
            current_app.logger.info(f"   Matched {len(variety_pack_deductions)} variety pack deductions")
            
            return jsonify({
                'success': True,
                'submissions': submissions_with_totals,
                'variety_pack_deductions': [dict(row) for row in variety_pack_deductions]
            })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500




