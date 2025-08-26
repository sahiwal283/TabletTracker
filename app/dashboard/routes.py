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

# Additional dashboard routes would go here...
# (Reports, analytics, etc.)
