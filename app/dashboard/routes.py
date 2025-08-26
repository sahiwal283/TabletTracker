"""
Dashboard and reporting routes
"""

from flask import render_template, request, session, redirect, url_for, flash, jsonify
from . import bp
from ..utils.decorators import role_required, admin_required
from ..models.database import get_db

@bp.route('/')
@role_required('dashboard')
def admin_dashboard():
    """Main admin dashboard"""
    try:
        conn = get_db()
        
        # Get active POs
        active_pos = conn.execute('''
            SELECT po.*, 
                   COUNT(pl.id) as line_count,
                   COALESCE(SUM(pl.quantity_ordered), 0) as total_ordered,
                   COALESCE(po.internal_status, 'Active') as status_display
            FROM purchase_orders po
            LEFT JOIN po_lines pl ON po.id = pl.po_id
            WHERE po.closed = FALSE
            GROUP BY po.id
            ORDER BY po.po_number DESC
            LIMIT 50
        ''').fetchall()
        
        # Get closed POs (last 20)
        closed_pos = conn.execute('''
            SELECT po.*, 
                   COUNT(pl.id) as line_count,
                   COALESCE(SUM(pl.quantity_ordered), 0) as total_ordered,
                   'Closed' as status_display
            FROM purchase_orders po
            LEFT JOIN po_lines pl ON po.id = pl.po_id
            WHERE po.closed = TRUE
            GROUP BY po.id
            ORDER BY po.po_number DESC
            LIMIT 20
        ''').fetchall()
        
        # Get recent submissions
        recent_submissions = conn.execute('''
            SELECT ws.*, pd.packages_per_display, pd.tablets_per_package,
                   (
                       (ws.displays_made * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
                       (ws.packs_remaining * COALESCE(pd.tablets_per_package, 0)) + 
                       ws.loose_tablets + ws.damaged_tablets
                   ) as calculated_total,
                   CASE 
                       WHEN ws.bag_label_count != (
                           (ws.displays_made * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
                           (ws.packs_remaining * COALESCE(pd.tablets_per_package, 0)) + 
                           ws.loose_tablets + ws.damaged_tablets
                       ) THEN 1
                       ELSE 0
                   END as has_discrepancy
            FROM warehouse_submissions ws
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            ORDER BY ws.created_at DESC 
            LIMIT 50
        ''').fetchall()
        
        # Calculate statistics
        stats = {
            'draft_pos': 0,
            'closed_pos': len(closed_pos),
            'total_remaining': sum(po.get('remaining_quantity', 0) for po in active_pos)
        }
        
        conn.close()
        
        return render_template('dashboard.html', 
                             active_pos=active_pos,
                             closed_pos=closed_pos, 
                             recent_submissions=recent_submissions,
                             stats=stats)
                             
    except Exception as e:
        flash(f'Error loading dashboard: {str(e)}', 'error')
        return redirect(url_for('auth.index'))

@bp.route('/reports/production', methods=['POST'])
@admin_required
def generate_production_report():
    """Generate production PDF report"""
    try:
        data = request.get_json()
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        if not start_date or not end_date:
            return jsonify({'success': False, 'error': 'Start and end dates required'}), 400
        
        # Import the report service
        from report_service import ProductionReportGenerator
        
        # Generate the report
        report_generator = ProductionReportGenerator()
        report_path = report_generator.generate_report(start_date, end_date)
        
        if report_path:
            return jsonify({
                'success': True, 
                'message': 'Report generated successfully',
                'report_path': report_path
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to generate report'}), 500
            
    except Exception as e:
        current_app.logger.error(f"Report generation error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route('/reports/po-summary')
@admin_required 
def get_po_summary_for_reports():
    """Get PO summary data for reports"""
    try:
        conn = get_db()
        
        # Get comprehensive PO summary
        po_summary = conn.execute('''
            SELECT 
                po.po_number,
                po.tablet_type,
                po.ordered_quantity,
                po.current_good_count,
                po.current_damaged_count,
                po.remaining_quantity,
                po.internal_status,
                po.created_at,
                COUNT(ws.id) as submission_count,
                COUNT(DISTINCT ws.employee_name) as employee_count,
                COALESCE(SUM(CASE WHEN ws.discrepancy_flag THEN 1 ELSE 0 END), 0) as discrepancy_count
            FROM purchase_orders po
            LEFT JOIN warehouse_submissions ws ON po.id = ws.assigned_po_id
            GROUP BY po.id
            ORDER BY po.po_number DESC
        ''').fetchall()
        
        conn.close()
        
        # Convert to list of dicts for JSON serialization
        summary_data = []
        for po in po_summary:
            summary_data.append({
                'po_number': po['po_number'],
                'tablet_type': po['tablet_type'],
                'ordered_quantity': po['ordered_quantity'],
                'current_good_count': po['current_good_count'],
                'current_damaged_count': po['current_damaged_count'],
                'remaining_quantity': po['remaining_quantity'],
                'internal_status': po['internal_status'],
                'created_at': po['created_at'],
                'submission_count': po['submission_count'],
                'employee_count': po['employee_count'],
                'discrepancy_count': po['discrepancy_count']
            })
        
        return jsonify({
            'success': True,
            'data': summary_data,
            'total_pos': len(summary_data)
        })
        
    except Exception as e:
        current_app.logger.error(f"PO summary error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
