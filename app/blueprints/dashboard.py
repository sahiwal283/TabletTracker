"""
Dashboard routes
"""
import traceback

from flask import Blueprint, current_app, flash, render_template

from app.services.submission_list_enrichment import (
    attach_receive_name_for_submission_row,
    enrich_submission_row_running_totals,
    new_running_totals_state,
)
from app.services.submission_query_service import apply_resolved_bag_fields
from app.utils.auth_utils import role_required
from app.utils.db_utils import db_read_only
from app.utils.perf_utils import query_timer

bp = Blueprint('dashboard', __name__)


@bp.route('/dashboard')
@role_required('dashboard')
def dashboard_view():
    """Desktop dashboard for managers/admins"""
    try:
        with db_read_only() as conn:
            def _log_query(label: str, ms: float) -> None:
                current_app.logger.info("perf_query dashboard %s %.2f ms", label, ms)

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
            with query_timer("active_pos", _log_query):
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
                       SELECT SUM(COALESCE(ws2.cards_reopened, 0))
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
                with query_timer("active_receives", _log_query):
                    active_receives = conn.execute(active_receives_query).fetchall()
            except Exception as e:
                current_app.logger.error(f"Error loading active receives: {e}")
                traceback.print_exc()
                active_receives = []

            # Get closed POs for historical reference (removed from dashboard)
            closed_pos = []

            # Get tablet types for report filters
            with query_timer("tablet_types", _log_query):
                tablet_types = conn.execute('SELECT id, tablet_type_name FROM tablet_types ORDER BY tablet_type_name').fetchall()

            # Get recent submissions (last 10 most recent, no date filter) with calculated totals
            # Show the most recent submissions regardless of date
            submissions_query = '''
            SELECT ws.*, po.po_number, po.closed as po_closed, po.zoho_po_id,
                   pd.packages_per_display, pd.tablets_per_package,
                   COALESCE(ws.po_assignment_verified, 0) as po_verified,
                   COALESCE(ws.needs_review, 0) as needs_review,
                   COALESCE(pd.is_variety_pack, 0) as is_variety_pack,
                   ws.admin_notes,
                   COALESCE(ws.submission_type, 'packaged') as submission_type,
                   COALESCE(b.bag_label_count, ws.bag_label_count, 0) as bag_label_count,
                   b.bag_label_count as receive_bag_count,
                   r.id as receive_id,
                   r.received_date,
                   r.receive_name as stored_receive_name,
                   COALESCE(sb.box_number, ws.box_number) AS resolved_box_number,
                   COALESCE(b.bag_number, ws.bag_number) AS resolved_bag_number,
                   CASE COALESCE(ws.submission_type, 'packaged')
                       WHEN 'machine' THEN COALESCE(
                           ws.tablets_pressed_into_cards,
                           ws.loose_tablets,
                           (ws.packs_remaining * COALESCE(COALESCE(pd.tablets_per_package, (
                               SELECT pd2.tablets_per_package
                               FROM product_details pd2
                               JOIN tablet_types tt2 ON pd2.tablet_type_id = tt2.id
                               WHERE tt2.inventory_item_id = ws.inventory_item_id
                               LIMIT 1
                           )), 0)),
                           0
                       )
                       WHEN 'repack' THEN (
                           (ws.displays_made * COALESCE(pd.packages_per_display, 0) * COALESCE(COALESCE(pd.tablets_per_package, (
                               SELECT pd2.tablets_per_package
                               FROM product_details pd2
                               JOIN tablet_types tt2 ON pd2.tablet_type_id = tt2.id
                               WHERE tt2.inventory_item_id = ws.inventory_item_id
                               LIMIT 1
                           )), 0)) +
                           (ws.packs_remaining * COALESCE(COALESCE(pd.tablets_per_package, (
                               SELECT pd2.tablets_per_package
                               FROM product_details pd2
                               JOIN tablet_types tt2 ON pd2.tablet_type_id = tt2.id
                               WHERE tt2.inventory_item_id = ws.inventory_item_id
                               LIMIT 1
                           )), 0))
                       )
                       ELSE (
                           (ws.displays_made * COALESCE(pd.packages_per_display, 0) * COALESCE(COALESCE(pd.tablets_per_package, (
                               SELECT pd2.tablets_per_package
                               FROM product_details pd2
                               JOIN tablet_types tt2 ON pd2.tablet_type_id = tt2.id
                               WHERE tt2.inventory_item_id = ws.inventory_item_id
                               LIMIT 1
                           )), 0)) +
                           (ws.packs_remaining * COALESCE(COALESCE(pd.tablets_per_package, (
                               SELECT pd2.tablets_per_package
                               FROM product_details pd2
                               JOIN tablet_types tt2 ON pd2.tablet_type_id = tt2.id
                               WHERE tt2.inventory_item_id = ws.inventory_item_id
                               LIMIT 1
                           )), 0)) +
                       ws.loose_tablets
                       )
                   END as calculated_total
            FROM warehouse_submissions ws
            LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            LEFT JOIN bags b ON ws.bag_id = b.id
            LEFT JOIN small_boxes sb ON b.small_box_id = sb.id
            LEFT JOIN receiving r ON sb.receiving_id = r.id
            WHERE ws.created_at IS NOT NULL
            ORDER BY ws.created_at DESC, ws.id DESC
            LIMIT 10
        '''
            with query_timer("submissions_recent", _log_query):
                submissions_raw = conn.execute(submissions_query).fetchall()
            current_app.logger.info(f"📊 Dashboard: Found {len(submissions_raw)} recent submissions (query returned {len(submissions_raw)} rows)")

            totals_state = new_running_totals_state()
            submissions_processed = []

            for sub in submissions_raw:
                sub_dict = dict(sub)
                apply_resolved_bag_fields(sub_dict)
                enrich_submission_row_running_totals(
                    sub_dict, totals_state, bag_submission_use="individual_calc"
                )
                attach_receive_name_for_submission_row(conn, sub_dict)
                submissions_processed.append(sub_dict)

            # Submissions are already ordered DESC and limited to 10, newest first
            submissions = submissions_processed

            # Get summary stats using closed field (boolean) and internal status (only count synced POs, not test data)
            with query_timer("stats", _log_query):
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
            with query_timer("verification_count", _log_query):
                verification_count = conn.execute('''
            SELECT COUNT(*) as count
            FROM warehouse_submissions
            WHERE COALESCE(po_assignment_verified, 0) = 0
            ''').fetchone()['count']

            # Find submissions that need review (ambiguous submissions)
            # They have needs_review=TRUE and bag_id=NULL (not yet assigned)
            with query_timer("submissions_needing_review", _log_query):
                submissions_needing_review = conn.execute('''
            SELECT ws.*,
                   tt.tablet_type_name,
                   (
                       CASE ws.submission_type
                           WHEN 'packaged' THEN (ws.displays_made * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0) +
                                                ws.packs_remaining * COALESCE(pd.tablets_per_package, 0))
                           WHEN 'bag' THEN ws.loose_tablets
                           WHEN 'machine' THEN COALESCE(
                               ws.tablets_pressed_into_cards,
                               ws.loose_tablets,
                               (ws.packs_remaining * COALESCE(COALESCE(pd.tablets_per_package, (
                               SELECT pd2.tablets_per_package
                               FROM product_details pd2
                               JOIN tablet_types tt2 ON pd2.tablet_type_id = tt2.id
                               WHERE tt2.inventory_item_id = ws.inventory_item_id
                               LIMIT 1
                           )), 0)),
                               0
                           )
                           ELSE ws.loose_tablets
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
        current_app.logger.error(f"Error in dashboard_view: {e}")
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

