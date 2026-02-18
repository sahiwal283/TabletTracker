"""
Reports API routes for generating production and vendor reports.
"""
from flask import Blueprint, request, jsonify, make_response, current_app
from datetime import datetime
import traceback
from app.utils.db_utils import db_read_only
from app.utils.auth_utils import role_required
from app.utils.cache_utils import get, set as cache_set
from app.services.report_service import ProductionReportGenerator
from config import Config

PO_SUMMARY_CACHE_KEY = 'api_reports_po_summary'
PO_SUMMARY_CACHE_TTL = 30.0

bp = Blueprint('api_reports', __name__)


@bp.route('/api/reports/production', methods=['POST'])
@role_required('dashboard')
def generate_production_report():
    """Generate comprehensive production report PDF"""
    try:
        data = request.get_json() or {}
        
        start_date = data.get('start_date')
        end_date = data.get('end_date') 
        po_numbers = data.get('po_numbers', [])
        tablet_type_id = data.get('tablet_type_id')
        report_type = data.get('report_type', 'production')
        receive_id = data.get('receive_id')
        
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
        
        response = make_response(pdf_content)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response
        
    except Exception as e:
        error_trace = traceback.format_exc()
        current_app.logger.error(f"Report generation error: {str(e)}\n{error_trace}")
        return jsonify({
            'success': False,
            'error': f'Report generation failed: {str(e)}'
        }), 500


@bp.route('/api/reports/po-summary')
@role_required('dashboard')
def get_po_summary_for_reports():
    """Get summary of POs available for reporting (cached 30s)."""
    cached = get(PO_SUMMARY_CACHE_KEY)
    if cached is not None:
        return jsonify(cached)
    try:
        with db_read_only() as conn:
            po_count_row = conn.execute('SELECT COUNT(*) as count FROM purchase_orders').fetchone()
            po_count = dict(po_count_row) if po_count_row else {'count': 0}
            if not po_count or po_count.get('count', 0) == 0:
                return jsonify({
                    'success': True,
                    'pos': [],
                    'total_count': 0,
                    'message': 'No purchase orders found'
                })
        
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
            
            po_list = []
            for po_row in pos:
                po = dict(po_row)
                
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

            payload = {
                'success': True,
                'pos': po_list,
                'total_count': len(po_list)
            }
            cache_set(PO_SUMMARY_CACHE_KEY, payload, PO_SUMMARY_CACHE_TTL)
            return jsonify(payload)
    except Exception as e:
        error_trace = traceback.format_exc()
        current_app.logger.error(f"Error in get_po_summary_for_reports: {e}\n{error_trace}")
        return jsonify({
            'success': False,
            'error': f'Failed to get PO summary: {str(e)}',
            'trace': error_trace
        }), 500

