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



