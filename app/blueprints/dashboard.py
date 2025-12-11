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
        
        # Get active POs that have submissions assigned (last 10) - for PO section
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
        
        # Get active receives that have submissions assigned (last 2)
        active_receives_query = '''
            SELECT r.*,
                   po.po_number,
                   po.id as po_id,
                   -- Calculate receive number (which shipment # for this PO)
                   (
                       SELECT COUNT(*) + 1
                       FROM receiving r2
                       WHERE r2.po_id = r.po_id
                       AND (r2.received_date < r.received_date 
                            OR (r2.received_date = r.received_date AND r2.id < r.id))
                   ) as receive_number,
                   COUNT(DISTINCT b.id) as bag_count,
                   COALESCE(SUM(b.bag_label_count), 0) as total_received,
                   COUNT(DISTINCT ws.id) as submission_count,
                   -- Calculate good count from submissions (via bag_id)
                   COALESCE((
                       SELECT SUM(
                           (COALESCE(ws2.displays_made, 0) * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
                           (COALESCE(ws2.packs_remaining, 0) * COALESCE(pd.tablets_per_package, 0)) +
                           COALESCE(ws2.loose_tablets, 0)
                       )
                       FROM warehouse_submissions ws2
                       LEFT JOIN product_details pd ON ws2.product_name = pd.product_name
                       LEFT JOIN bags b2 ON ws2.bag_id = b2.id
                       LEFT JOIN small_boxes sb2 ON b2.small_box_id = sb2.id
                       WHERE sb2.receiving_id = r.id
                   ), 0) as current_good_count,
                   -- Calculate damaged count from submissions (via bag_id)
                   COALESCE((
                       SELECT SUM(COALESCE(ws2.damaged_tablets, 0))
                       FROM warehouse_submissions ws2
                       LEFT JOIN bags b2 ON ws2.bag_id = b2.id
                       LEFT JOIN small_boxes sb2 ON b2.small_box_id = sb2.id
                       WHERE sb2.receiving_id = r.id
                   ), 0) as current_damaged_count,
                   -- Get primary tablet type (most common in this receive)
                   (
                       SELECT tt.tablet_type_name
                       FROM bags b3
                       JOIN small_boxes sb3 ON b3.small_box_id = sb3.id
                       JOIN tablet_types tt ON b3.tablet_type_id = tt.id
                       WHERE sb3.receiving_id = r.id
                       GROUP BY tt.tablet_type_name
                       ORDER BY COUNT(*) DESC
                       LIMIT 1
                   ) as tablet_type
            FROM receiving r
            LEFT JOIN purchase_orders po ON r.po_id = po.id
            LEFT JOIN small_boxes sb ON sb.receiving_id = r.id
            LEFT JOIN bags b ON b.small_box_id = sb.id
            LEFT JOIN warehouse_submissions ws ON ws.bag_id = b.id
            WHERE r.received_date IS NOT NULL
            AND r.id IS NOT NULL
            GROUP BY r.id
            HAVING submission_count > 0
            ORDER BY r.received_date DESC
            LIMIT 2
        '''
        try:
            active_receives = conn.execute(active_receives_query).fetchall()
        except Exception as e:
            print(f"Error loading active receives: {e}")
            traceback.print_exc()
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
                   COALESCE(ws.submission_type, 'packaged') as submission_type,
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
        # Separate running totals for each submission type
        bag_running_totals = {}  # Key: (po_id, product_name, "box/bag"), Value: running_total (all types)
        bag_running_totals_bag = {}  # Key: (po_id, product_name, "box/bag"), Value: running_total (bag type only)
        bag_running_totals_machine = {}  # Key: (po_id, product_name, "box/bag"), Value: running_total (machine type only)
        bag_running_totals_packaged = {}  # Key: (po_id, product_name, "box/bag"), Value: running_total (packaged type only)
        submissions_processed = []
        
        for sub in submissions_raw:
            sub_dict = dict(sub)
            # Create bag identifier from box_number/bag_number
            bag_identifier = f"{sub_dict.get('box_number', '')}/{sub_dict.get('bag_number', '')}"
            # Key includes PO ID so each PO tracks its own bag totals independently
            bag_key = (sub_dict.get('assigned_po_id'), sub_dict.get('product_name'), bag_identifier)
            
            # Individual calculation for this submission
            individual_calc = sub_dict.get('calculated_total', 0) or 0
            submission_type = sub_dict.get('submission_type', 'packaged')
            
            # Initialize running totals for this bag if not exists
            if bag_key not in bag_running_totals:
                bag_running_totals[bag_key] = 0
            if bag_key not in bag_running_totals_bag:
                bag_running_totals_bag[bag_key] = 0
            if bag_key not in bag_running_totals_machine:
                bag_running_totals_machine[bag_key] = 0
            if bag_key not in bag_running_totals_packaged:
                bag_running_totals_packaged[bag_key] = 0
            
            # Update appropriate running total based on submission type
            if submission_type == 'bag':
                bag_running_totals_bag[bag_key] += individual_calc
            elif submission_type == 'machine':
                bag_running_totals_machine[bag_key] += individual_calc
            else:  # 'packaged'
                bag_running_totals_packaged[bag_key] += individual_calc
            
            # Update total running total (all types combined)
            bag_running_totals[bag_key] += individual_calc
            
            # Add running total and comparison fields
            sub_dict['individual_calc'] = individual_calc
            sub_dict['bag_running_total'] = bag_running_totals_bag[bag_key]
            sub_dict['machine_running_total'] = bag_running_totals_machine[bag_key]
            sub_dict['packaged_running_total'] = bag_running_totals_packaged[bag_key]
            sub_dict['running_total'] = bag_running_totals[bag_key]
            
            # Compare running total to bag label count
            bag_count = sub_dict.get('bag_label_count', 0) or 0
            running_total = bag_running_totals[bag_key]
            
            # Determine status - check if bag_id is NULL, not just bag_label_count
            # A bag can exist with label_count=0, but if bag_id is NULL, there's no bag assigned
            if not sub_dict.get('bag_id'):
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
        
        # Find submissions that need review (ambiguous submissions)
        # These are submissions where flavor + box + bag match multiple receives
        # They have needs_review=TRUE and bag_id=NULL (not yet assigned)
        submissions_needing_review = conn.execute('''
            SELECT ws.*, 
                   tt.tablet_type_name,
                   (
                       CASE ws.submission_type
                           WHEN 'packaged' THEN (ws.displays_made * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0) + 
                                                ws.packs_remaining * COALESCE(pd.tablets_per_package, 0))
                           WHEN 'bag' THEN ws.loose_tablets
                           WHEN 'machine' THEN ws.loose_tablets
                           ELSE ws.loose_tablets + ws.damaged_tablets
                       END
                   ) as calculated_total
            FROM warehouse_submissions ws
            LEFT JOIN tablet_types tt ON ws.inventory_item_id = tt.inventory_item_id
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            WHERE COALESCE(ws.needs_review, 0) = 1
            ORDER BY ws.created_at DESC
        ''').fetchall()
        
        # Convert to list of dicts
        review_submissions = [dict(row) for row in submissions_needing_review]
        
        return render_template('dashboard.html', active_pos=active_pos, active_receives=active_receives, closed_pos=closed_pos, submissions=submissions, stats=stats, verification_count=verification_count, tablet_types=tablet_types, submissions_needing_review=review_submissions)
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

