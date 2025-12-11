"""
Submissions routes
"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, make_response
from datetime import datetime
import traceback
import csv
import io
from app.utils.db_utils import get_db
from app.utils.auth_utils import role_required

bp = Blueprint('submissions', __name__)

@bp.route('/submissions')
@role_required('dashboard')
def submissions_list():
    """Full submissions page showing all submissions"""
    conn = None
    try:
        conn = get_db()
        
        # Get filter parameters from query string
        filter_po_id = request.args.get('po_id', type=int)
        filter_item_id = request.args.get('item_id', type=str)
        filter_date_from = request.args.get('date_from', type=str)
        filter_date_to = request.args.get('date_to', type=str)
        filter_tablet_type_id = request.args.get('tablet_type_id', type=int)
        filter_submission_type = request.args.get('submission_type', type=str)
        
        # Build query with optional filters
        # Use stored receive_name from receiving table
        query = '''
            SELECT ws.*, po.po_number, po.closed as po_closed, po.id as po_id_for_filter, po.zoho_po_id,
                   pd.packages_per_display, pd.tablets_per_package,
                   tt.inventory_item_id, tt.id as tablet_type_id, tt.tablet_type_name,
                   COALESCE(ws.po_assignment_verified, 0) as po_verified,
                   COALESCE(ws.needs_review, 0) as needs_review,
                   ws.admin_notes,
                   COALESCE(ws.submission_type, 'packaged') as submission_type,
                   COALESCE(ws.submission_date, DATE(ws.created_at)) as filter_date,
                   COALESCE(b.bag_label_count, ws.bag_label_count, 0) as bag_label_count,
                   b.bag_label_count as receive_bag_count,
                   ws.bag_id,
                   r.id as receive_id,
                   r.received_date,
                   r.receive_name as stored_receive_name,
                   sb.box_number,
                   b.bag_number,
                   (
                       (ws.displays_made * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
                       (ws.packs_remaining * COALESCE(pd.tablets_per_package, 0)) + 
                       ws.loose_tablets + ws.damaged_tablets
                   ) as calculated_total
            FROM warehouse_submissions ws
            LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            LEFT JOIN bags b ON ws.bag_id = b.id
            LEFT JOIN small_boxes sb ON b.small_box_id = sb.id
            LEFT JOIN receiving r ON sb.receiving_id = r.id
            WHERE 1=1
        '''
        
        params = []
        
        # Apply PO filter if provided
        if filter_po_id:
            query += ' AND ws.assigned_po_id = ?'
            params.append(filter_po_id)
        
        # Apply item filter if provided
        if filter_item_id:
            query += ' AND tt.inventory_item_id = ?'
            params.append(filter_item_id)
        
        # Apply date range filters
        if filter_date_from:
            query += ' AND COALESCE(ws.submission_date, DATE(ws.created_at)) >= ?'
            params.append(filter_date_from)
        
        if filter_date_to:
            query += ' AND COALESCE(ws.submission_date, DATE(ws.created_at)) <= ?'
            params.append(filter_date_to)
        
        # Apply tablet type filter if provided
        if filter_tablet_type_id:
            query += ' AND tt.id = ?'
            params.append(filter_tablet_type_id)
        
        # Apply submission type filter if provided
        if filter_submission_type:
            query += ' AND COALESCE(ws.submission_type, \'packaged\') = ?'
            params.append(filter_submission_type)
        
        # Get submissions ordered by created_at ASC for running total calculation
        query_asc = query.replace('ORDER BY ws.created_at DESC', 'ORDER BY ws.created_at ASC')
        submissions_raw_asc = conn.execute(query_asc, params).fetchall()
        
        # Calculate running totals by bag PER PO (each PO has its own physical bags)
        # Separate running totals for each submission type
        # Process in chronological order (oldest first) for correct running totals
        bag_running_totals = {}  # Key: (po_id, product_name, "box/bag"), Value: running_total (all types)
        bag_running_totals_bag = {}  # Key: (po_id, product_name, "box/bag"), Value: running_total (bag type only)
        bag_running_totals_machine = {}  # Key: (po_id, product_name, "box/bag"), Value: running_total (machine type only)
        bag_running_totals_packaged = {}  # Key: (po_id, product_name, "box/bag"), Value: running_total (packaged type only)
        submissions_dict = {}  # Store by submission ID for later lookup
        
        # First pass: Calculate running totals in chronological order (oldest first)
        for sub in submissions_raw_asc:
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
                # For bag count submissions, use loose_tablets (the actual count from form)
                bag_count_value = sub_dict.get('loose_tablets', 0) or 0
                bag_running_totals_bag[bag_key] += bag_count_value
            elif submission_type == 'machine':
                bag_running_totals_machine[bag_key] += individual_calc
            else:  # 'packaged'
                bag_running_totals_packaged[bag_key] += individual_calc
            
            # Update total running total (only packaged counts - machine counts are consumed, not in bag)
            # Bag counts are also separate inventory counts, not added to total
            if submission_type == 'packaged':
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
            
            # Build receive name using stored receive_name from database
            # Format: PO-receive-box-bag (e.g., PO-00164-1-1-2)
            receive_name = None
            stored_receive_name = sub_dict.get('stored_receive_name')
            box_number = sub_dict.get('box_number')
            bag_number = sub_dict.get('bag_number')
            
            if stored_receive_name and box_number is not None and bag_number is not None:
                # Use stored receive_name (e.g., "PO-00164-1") and append box-bag
                receive_name = f"{stored_receive_name}-{box_number}-{bag_number}"
            elif sub_dict.get('receive_id') and sub_dict.get('po_number'):
                # Fallback for legacy records: calculate receive_number dynamically
                # This should only happen if receive_name wasn't backfilled
                receive_number_result = conn.execute('''
                    SELECT COUNT(*) + 1 as receive_number
                    FROM receiving r2
                    WHERE r2.po_id = ?
                    AND (r2.received_date < (SELECT received_date FROM receiving WHERE id = ?)
                         OR (r2.received_date = (SELECT received_date FROM receiving WHERE id = ?) 
                             AND r2.id < ?))
                ''', (sub_dict.get('assigned_po_id'), sub_dict.get('receive_id'), 
                      sub_dict.get('receive_id'), sub_dict.get('receive_id'))).fetchone()
                receive_number = receive_number_result['receive_number'] if receive_number_result else 1
                if box_number is not None and bag_number is not None:
                    receive_name = f"{sub_dict.get('po_number')}-{receive_number}-{box_number}-{bag_number}"
            
            sub_dict['receive_name'] = receive_name
            
            # Store in dict by submission ID for lookup
            submissions_dict[sub_dict.get('id')] = sub_dict
        
        # Second pass: Get submissions in display order (newest first) and apply pre-calculated running totals
        query += ' ORDER BY ws.created_at DESC'
        submissions_raw = conn.execute(query, params).fetchall()
        submissions_processed = []
        
        for sub in submissions_raw:
            sub_dict = dict(sub)
            sub_id = sub_dict.get('id')
            # Get the pre-calculated running totals from the first pass
            if sub_id in submissions_dict:
                pre_calculated = submissions_dict[sub_id]
                sub_dict['bag_running_total'] = pre_calculated.get('bag_running_total', 0)
                sub_dict['machine_running_total'] = pre_calculated.get('machine_running_total', 0)
                sub_dict['packaged_running_total'] = pre_calculated.get('packaged_running_total', 0)
                sub_dict['running_total'] = pre_calculated.get('running_total', 0)
                sub_dict['count_status'] = pre_calculated.get('count_status', 'no_bag')
                sub_dict['has_discrepancy'] = pre_calculated.get('has_discrepancy', 0)
                sub_dict['receive_name'] = pre_calculated.get('receive_name')
            
            # Individual calculation for display
            individual_calc = sub_dict.get('calculated_total', 0) or 0
            sub_dict['individual_calc'] = individual_calc
            
            submissions_processed.append(sub_dict)
        
        # Query already orders by DESC (newest first), so use as-is
        all_submissions = submissions_processed  # All submissions, newest first
        
        # Pagination
        page = request.args.get('page', 1, type=int)
        per_page = 15
        total_submissions = len(all_submissions)
        total_pages = (total_submissions + per_page - 1) // per_page  # Ceiling division
        
        # Calculate start and end indices
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        
        # Get submissions for current page
        submissions = all_submissions[start_idx:end_idx]
        
        # Count unverified submissions (respecting current filters)
        unverified_query = '''
            SELECT COUNT(*) as count
            FROM warehouse_submissions ws
            LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            WHERE COALESCE(ws.po_assignment_verified, 0) = 0
        '''
        unverified_params = []
        if filter_po_id:
            unverified_query += ' AND ws.assigned_po_id = ?'
            unverified_params.append(filter_po_id)
        if filter_item_id:
            unverified_query += ' AND tt.inventory_item_id = ?'
            unverified_params.append(filter_item_id)
        if filter_date_from:
            unverified_query += ' AND COALESCE(ws.submission_date, DATE(ws.created_at)) >= ?'
            unverified_params.append(filter_date_from)
        if filter_date_to:
            unverified_query += ' AND COALESCE(ws.submission_date, DATE(ws.created_at)) <= ?'
            unverified_params.append(filter_date_to)
        if filter_tablet_type_id:
            unverified_query += ' AND tt.id = ?'
            unverified_params.append(filter_tablet_type_id)
        if filter_submission_type:
            unverified_query += ' AND COALESCE(ws.submission_type, \'packaged\') = ?'
            unverified_params.append(filter_submission_type)
        
        unverified_count = conn.execute(unverified_query, unverified_params).fetchone()['count']
        
        # Pagination info
        pagination = {
            'page': page,
            'per_page': per_page,
            'total': total_submissions,
            'total_pages': total_pages,
            'has_prev': page > 1,
            'has_next': page < total_pages,
            'prev_page': page - 1 if page > 1 else None,
            'next_page': page + 1 if page < total_pages else None
        }
        
        # Get filter info for display
        filter_info = {}
        if filter_po_id:
            po_info = conn.execute('SELECT po_number FROM purchase_orders WHERE id = ?', (filter_po_id,)).fetchone()
            if po_info:
                filter_info['po_number'] = po_info['po_number']
                filter_info['po_id'] = filter_po_id
        
        if filter_item_id:
            item_info = conn.execute('SELECT line_item_name FROM po_lines WHERE inventory_item_id = ? LIMIT 1', (filter_item_id,)).fetchone()
            if item_info:
                filter_info['item_name'] = item_info['line_item_name']
                filter_info['item_id'] = filter_item_id
        
        if filter_date_from:
            filter_info['date_from'] = filter_date_from
        if filter_date_to:
            filter_info['date_to'] = filter_date_to
        if filter_tablet_type_id:
            tablet_type_info = conn.execute('SELECT tablet_type_name FROM tablet_types WHERE id = ?', (filter_tablet_type_id,)).fetchone()
            if tablet_type_info:
                filter_info['tablet_type_name'] = tablet_type_info['tablet_type_name']
                filter_info['tablet_type_id'] = filter_tablet_type_id
        
        if filter_submission_type:
            filter_info['submission_type'] = filter_submission_type
        
        # Get all tablet types for the filter dropdown
        tablet_types = conn.execute('SELECT id, tablet_type_name FROM tablet_types ORDER BY tablet_type_name').fetchall()
        
        return render_template('submissions.html', submissions=submissions, pagination=pagination, filter_info=filter_info, unverified_count=unverified_count, tablet_types=tablet_types, 
                             filter_date_from=filter_date_from, filter_date_to=filter_date_to, filter_tablet_type_id=filter_tablet_type_id, filter_submission_type=filter_submission_type)
    except Exception as e:
        print(f"Error in all_submissions: {e}")
        traceback.print_exc()
        flash('An error occurred while loading submissions. Please try again.', 'error')
        return render_template('submissions.html', submissions=[], pagination={'page': 1, 'per_page': 15, 'total': 0, 'total_pages': 0, 'has_prev': False, 'has_next': False}, filter_info={}, unverified_count=0)
    finally:
        if conn:
            conn.close()

@bp.route('/submissions/export')
@role_required('dashboard')
def export_submissions_csv():
    """Export submissions to CSV with all active filters applied"""
    conn = None
    try:
        conn = get_db()
        
        # Get filter parameters from query string (same as all_submissions)
        filter_po_id = request.args.get('po_id', type=int)
        filter_item_id = request.args.get('item_id', type=str)
        filter_date_from = request.args.get('date_from', type=str)
        filter_date_to = request.args.get('date_to', type=str)
        filter_tablet_type_id = request.args.get('tablet_type_id', type=int)
        
        # Build query with optional filters (same logic as all_submissions)
        query = '''
            SELECT ws.*, po.po_number, po.closed as po_closed,
                   pd.packages_per_display, pd.tablets_per_package,
                   tt.inventory_item_id, tt.tablet_type_name,
                   COALESCE(ws.po_assignment_verified, 0) as po_verified,
                   ws.admin_notes,
                   COALESCE(ws.submission_date, DATE(ws.created_at)) as filter_date,
                   (
                       (ws.displays_made * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
                       (ws.packs_remaining * COALESCE(pd.tablets_per_package, 0)) + 
                       ws.loose_tablets + ws.damaged_tablets
                   ) as calculated_total
            FROM warehouse_submissions ws
            LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            WHERE 1=1
        '''
        
        params = []
        
        # Apply PO filter if provided
        if filter_po_id:
            query += ' AND ws.assigned_po_id = ?'
            params.append(filter_po_id)
        
        # Apply item filter if provided
        if filter_item_id:
            query += ' AND tt.inventory_item_id = ?'
            params.append(filter_item_id)
        
        # Apply date range filters
        if filter_date_from:
            query += ' AND COALESCE(ws.submission_date, DATE(ws.created_at)) >= ?'
            params.append(filter_date_from)
        
        if filter_date_to:
            query += ' AND COALESCE(ws.submission_date, DATE(ws.created_at)) <= ?'
            params.append(filter_date_to)
        
        # Apply tablet type filter if provided
        if filter_tablet_type_id:
            query += ' AND tt.id = ?'
            params.append(filter_tablet_type_id)
        
        query += ' ORDER BY ws.created_at ASC'
        
        submissions_raw = conn.execute(query, params).fetchall()
        
        # Calculate running totals by bag PER PO (same logic as all_submissions)
        bag_running_totals = {}
        submissions_processed = []
        
        for sub in submissions_raw:
            sub_dict = dict(sub)
            bag_identifier = f"{sub_dict.get('box_number', '')}/{sub_dict.get('bag_number', '')}"
            bag_key = (sub_dict.get('assigned_po_id'), sub_dict.get('product_name'), bag_identifier)
            
            individual_calc = sub_dict.get('calculated_total', 0) or 0
            
            if bag_key not in bag_running_totals:
                bag_running_totals[bag_key] = 0
            bag_running_totals[bag_key] += individual_calc
            
            sub_dict['individual_calc'] = individual_calc
            sub_dict['running_total'] = bag_running_totals[bag_key]
            
            bag_count = sub_dict.get('bag_label_count', 0) or 0
            running_total = bag_running_totals[bag_key]
            
            if bag_count == 0:
                sub_dict['count_status'] = 'No Bag Label'
            elif abs(running_total - bag_count) <= 5:
                sub_dict['count_status'] = 'Match'
            elif running_total < bag_count:
                sub_dict['count_status'] = 'Under'
            else:
                sub_dict['count_status'] = 'Over'
            
            submissions_processed.append(sub_dict)
        
        # Create CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header row
        writer.writerow([
            'Submission Date',
            'Created At',
            'Employee Name',
            'Product Name',
            'Tablet Type',
            'PO Number',
            'Box Number',
            'Bag Number',
            'Displays Made',
            'Packs Remaining',
            'Loose Tablets',
            'Damaged Tablets',
            'Total Tablets (Individual)',
            'Running Total (Bag)',
            'Bag Label Count',
            'Count Status',
            'PO Assignment Verified',
            'Admin Notes'
        ])
        
        # Write data rows (oldest first for CSV)
        for sub in submissions_processed:
            submission_date = sub.get('submission_date') or sub.get('filter_date') or ''
            created_at = sub.get('created_at', '')
            if created_at:
                try:
                    # Format datetime for CSV
                    if isinstance(created_at, str):
                        created_at = created_at[:19]  # Truncate to seconds
                except:
                    pass
            
            writer.writerow([
                submission_date,
                created_at,
                sub.get('employee_name', ''),
                sub.get('product_name', ''),
                sub.get('tablet_type_name', ''),
                sub.get('po_number', ''),
                sub.get('box_number', ''),
                sub.get('bag_number', ''),
                sub.get('displays_made', 0),
                sub.get('packs_remaining', 0),
                sub.get('loose_tablets', 0),
                sub.get('damaged_tablets', 0),
                sub.get('individual_calc', 0),
                sub.get('running_total', 0),
                sub.get('bag_label_count', 0),
                sub.get('count_status', ''),
                'Yes' if sub.get('po_verified', 0) else 'No',
                sub.get('admin_notes', '')
            ])
        
        # Generate filename with date range if applicable
        filename_parts = ['submissions']
        if filter_date_from:
            filename_parts.append(f'from_{filter_date_from}')
        if filter_date_to:
            filename_parts.append(f'to_{filter_date_to}')
        if filter_tablet_type_id:
            filename_parts.append(f'type_{submissions_processed[0].get("tablet_type_name", "unknown") if submissions_processed else "unknown"}')
        if filter_po_id:
            po_info = conn.execute('SELECT po_number FROM purchase_orders WHERE id = ?', (filter_po_id,)).fetchone()
            if po_info:
                filename_parts.append(f'po_{po_info["po_number"]}')
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{'_'.join(filename_parts)}_{timestamp}.csv"
        
        # Create response
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv; charset=utf-8'
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response
        
    except Exception as e:
        print(f"Error exporting submissions CSV: {e}")
        traceback.print_exc()
        flash('An error occurred while exporting submissions. Please try again.', 'error')
        return redirect(url_for('submissions.all_submissions'))
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

