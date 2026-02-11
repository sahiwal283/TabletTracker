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
                           CASE COALESCE(ws.submission_type, 'packaged')
                               WHEN 'packaged' THEN (
                                   COALESCE(ws.displays_made, 0) * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0) + 
                                   COALESCE(ws.packs_remaining, 0) * COALESCE(pd.tablets_per_package, 0)
                               )
                               WHEN 'bag' THEN COALESCE(ws.loose_tablets, 0)
                               WHEN 'machine' THEN COALESCE(
                                   ws.tablets_pressed_into_cards,
                                   (ws.packs_remaining * COALESCE(pd.tablets_per_package, 0)),
                                   0
                               )
                               WHEN 'bottle' THEN COALESCE(
                                   (SELECT SUM(sbd.tablets_deducted) FROM submission_bag_deductions sbd WHERE sbd.submission_id = ws.id),
                                   COALESCE(ws.bottles_made, 0) * COALESCE(pd.tablets_per_bottle, 0)
                               )
                               ELSE 0
                           END
                       ) as total_tablets
                FROM warehouse_submissions ws
                LEFT JOIN (
                    SELECT tt.inventory_item_id, pd.*
                    FROM tablet_types tt
                    LEFT JOIN product_details pd ON tt.id = pd.tablet_type_id
                    WHERE pd.id IS NOT NULL
                    GROUP BY tt.inventory_item_id
                ) pd ON ws.inventory_item_id = pd.inventory_item_id
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
                GROUP BY ws.id
                ORDER BY ws.created_at DESC
            ''', (bag_id, bag['inventory_item_id'], bag['bag_number'], bag['po_id'], bag['box_number'])).fetchall()
            
            current_app.logger.info(f"   Matched {len(submissions)} direct submissions")
            
            # Also get variety pack deductions via junction table
            variety_pack_deductions = conn.execute('''
                SELECT sbd.id, sbd.submission_id, sbd.bag_id, sbd.tablets_deducted, sbd.created_at,
                       ws.employee_name, ws.product_name, ws.bottles_made, ws.displays_made,
                       ws.submission_date, ws.submission_type,
                       pd.tablets_per_bottle, pd.bottles_per_display
                FROM submission_bag_deductions sbd
                JOIN warehouse_submissions ws ON sbd.submission_id = ws.id
                LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                WHERE sbd.bag_id = ?
                ORDER BY sbd.created_at DESC
            ''', (bag_id,)).fetchall()
            
            current_app.logger.info(f"   Matched {len(variety_pack_deductions)} variety pack deductions")
            
            return jsonify({
                'success': True,
                'submissions': [dict(row) for row in submissions],
                'variety_pack_deductions': [dict(row) for row in variety_pack_deductions]
            })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500




