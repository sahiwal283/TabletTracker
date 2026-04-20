"""
Submission-related API endpoints
"""
from flask import Blueprint, jsonify, current_app
import traceback
from app.utils.db_utils import db_read_only
from app.utils.auth_utils import role_required
from app.services.submission_details_service import get_bag_submissions_payload
from app.services.receiving_service import get_bag_with_packaged_count

bp = Blueprint('api_submissions', __name__)


@bp.route('/api/bag/<int:bag_id>/submissions', methods=['GET'])
@role_required('submissions')
def get_bag_submissions(bag_id):
    """Get all submissions for a specific bag (for duplicate review)"""
    try:
        with db_read_only() as conn:
            payload = get_bag_submissions_payload(conn, bag_id)
            if not payload.get('success'):
                return jsonify({'error': payload.get('error', 'Failed to load bag submissions')}), payload.get('status_code', 400)

            bag = payload['bag']
            current_app.logger.info(f"🔍 GET /api/bag/{bag_id}/submissions")
            current_app.logger.info(f"   Bag criteria: inventory_item_id={bag.get('inventory_item_id')}, box={bag.get('box_number')}, bag={bag.get('bag_number')}, po_id={bag.get('po_id')}")
            current_app.logger.info(f"   Matched {len(payload['submissions'])} direct submissions")
            current_app.logger.info(f"   Matched {len(payload['variety_pack_deductions'])} variety pack deductions")

            bag_detail = get_bag_with_packaged_count(bag_id)
            po_summary = None
            if bag_detail:
                bag_detail['received_count'] = (
                    bag_detail.get('bag_label_count')
                    or bag_detail.get('pill_count')
                    or 0
                )
                po_summary = {
                    'id': bag_detail.get('po_id'),
                    'po_number': bag_detail.get('po_number'),
                }

            return jsonify({
                'success': True,
                'submissions': payload['submissions'],
                'variety_pack_deductions': payload['variety_pack_deductions'],
                'bag': bag_detail,
                'po': po_summary,
            })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500




