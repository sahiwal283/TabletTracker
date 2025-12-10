"""
Dashboard routes
"""
from flask import Blueprint, render_template, flash
import traceback
from app.utils.db_utils import get_db
from app.utils.auth_utils import role_required

bp = Blueprint('dashboard', __name__)


@bp.route('/dashboard')
@role_required('dashboard')
def dashboard_view():
    """Desktop dashboard for managers/admins"""
    conn = None
    try:
        conn = get_db()
        
        # Get active POs that have submissions assigned (last 10)
        active_pos_query = '''
            SELECT po.*, 
                   COUNT(DISTINCT pl.id) as line_count,
                   COALESCE(SUM(pl.quantity_ordered), 0) as total_ordered,
                   COALESCE(po.internal_status, 'Active') as status_display,
                   COUNT(DISTINCT ws.id) as submission_count
            FROM purchase_orders po
            LEFT JOIN po_lines pl ON po.id = pl.po_id
            INNER JOIN warehouse_submissions ws ON po.id = ws.assigned_po_id
            WHERE po.closed = FALSE
            AND COALESCE(po.internal_status, '') != 'Cancelled'
            GROUP BY po.id
            HAVING submission_count > 0
            ORDER BY po.po_number DESC
            LIMIT 10
        '''
        active_pos = conn.execute(active_pos_query).fetchall()
        
        # Get active receives with submission counts (for dashboard widget)
        # Simplified query to avoid errors
        try:
            active_receives = []
        except Exception as e:
            print(f"Error loading active receives: {e}")
            active_receives = []
        
        # Get closed POs for historical reference (removed from dashboard)
        closed_pos = []
        
        # Get tablet types for report filters
        tablet_types = conn.execute('SELECT id, tablet_type_name FROM tablet_types ORDER BY tablet_type_name').fetchall()
        
        # Get recent submissions with calculated totals and running bag totals
        submissions_query = '''
            SELECT ws.*, po.po_number, po.closed as po_closed,
                   pd.packages_per_display, pd.tablets_per_package,
                   COALESCE(ws.po_assignment_verified, 0) as po_verified,
                   COALESCE(ws.needs_review, 0) as needs_review,
                   ws.admin_notes,
                   COALESCE(b.bag_label_count, ws.bag_label_count, 0) as bag_label_count,
                   (
                       (ws.displays_made * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
                       (ws.packs_remaining * COALESCE(pd.tablets_per_package, 0)) + 
                       ws.loose_tablets + ws.damaged_tablets
                   ) as calculated_total
            FROM warehouse_submissions ws
            LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            LEFT JOIN bags b ON ws.bag_id = b.id
            ORDER BY ws.created_at ASC
        '''
        submissions_raw = conn.execute(submissions_query).fetchall()
        
        # Calculate running totals by bag PER PO (each PO has its own physical bags)
        bag_running_totals = {}  # Key: (po_id, product_name, "box/bag"), Value: running_total
        submissions_processed = []
        
        for sub in submissions_raw:
            sub_dict = dict(sub)
            # Create bag identifier from box_number/bag_number
            bag_identifier = f"{sub_dict.get('box_number', '')}/{sub_dict.get('bag_number', '')}"
            # Key includes PO ID so each PO tracks its own bag totals independently
            bag_key = (sub_dict.get('assigned_po_id'), sub_dict.get('product_name'), bag_identifier)
            
            # Individual calculation for this submission
            individual_calc = sub_dict.get('calculated_total', 0) or 0
            
            # Update running total for this bag
            if bag_key not in bag_running_totals:
                bag_running_totals[bag_key] = 0
            bag_running_totals[bag_key] += individual_calc
            
            # Add running total and comparison fields
            sub_dict['individual_calc'] = individual_calc
            sub_dict['running_total'] = bag_running_totals[bag_key]
            
            # Compare running total to bag label count
            bag_count = sub_dict.get('bag_label_count', 0) or 0
            running_total = bag_running_totals[bag_key]
            
            # Determine status
            if bag_count == 0:
                sub_dict['count_status'] = 'no_bag'
            elif abs(running_total - bag_count) <= 5:  # Allow 5 tablet tolerance
                sub_dict['count_status'] = 'match'
            elif running_total < bag_count:
                sub_dict['count_status'] = 'under'
            else:
                sub_dict['count_status'] = 'over'
            
            sub_dict['has_discrepancy'] = 1 if sub_dict['count_status'] != 'match' and bag_count > 0 else 0
            
            submissions_processed.append(sub_dict)
        
        # Show only last 10 most recent submissions on dashboard
        submissions = list(reversed(submissions_processed[-10:]))  # Last 10, newest first
        
        # Get summary stats using closed field (boolean) and internal status (only count synced POs, not test data)
        stats = conn.execute('''
            SELECT 
                COUNT(CASE WHEN closed = FALSE AND zoho_po_id IS NOT NULL THEN 1 END) as open_pos,
                COUNT(CASE WHEN closed = TRUE AND zoho_po_id IS NOT NULL THEN 1 END) as closed_pos,
                COUNT(CASE WHEN internal_status = 'Draft' AND zoho_po_id IS NOT NULL THEN 1 END) as draft_pos,
                COALESCE(SUM(CASE WHEN closed = FALSE AND zoho_po_id IS NOT NULL THEN 
                    (ordered_quantity - current_good_count - current_damaged_count) END), 0) as total_remaining
            FROM purchase_orders
        ''').fetchone()
        
        # Count ALL submissions needing verification (not verified yet)
        verification_count = conn.execute('''
            SELECT COUNT(*) as count
            FROM warehouse_submissions
            WHERE COALESCE(po_assignment_verified, 0) = 0
        ''').fetchone()['count']
        
        return render_template('dashboard.html', active_pos=active_pos, active_receives=active_receives, closed_pos=closed_pos, submissions=submissions, stats=stats, verification_count=verification_count, tablet_types=tablet_types)
    except Exception as e:
        print(f"Error in dashboard_view: {e}")
        traceback.print_exc()
        flash('An error occurred while loading the dashboard. Please try again.', 'error')
        # Create default stats dict to match expected structure (SQLite Row-like object)
        default_stats = type('obj', (object,), {
            'open_pos': 0,
            'closed_pos': 0,
            'draft_pos': 0,
            'total_remaining': 0
        })()
        return render_template('dashboard.html', active_pos=[], active_receives=[], closed_pos=[], submissions=[], stats=default_stats, verification_count=0, tablet_types=[])
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

