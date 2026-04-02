"""
Production routes - warehouse submissions, bag counts, machine counts
"""
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, current_app
from datetime import datetime
import json
import traceback
from app.utils.db_utils import db_read_only, db_transaction
from app.utils.repack_po import apply_po_line_delta
from app.services.submission_calculator import calculate_repack_output_good
from app.services.repack_allocation_service import (
    allocate_repack_tablets,
    allocation_payload_to_json,
)
from app.services.submission_context_service import (
    resolve_submission_employee_name,
    normalize_optional_text,
)
from app.utils.auth_utils import employee_required
from app.utils.route_helpers import (
    ensure_submission_type_column,
    ensure_machine_counts_table, ensure_machine_count_columns
)
from app.utils.receive_tracking import find_bag_for_submission
from app.utils.eastern_datetime import (
    parse_optional_eastern,
    utc_now_naive_string,
)
from app.services.production_submission_helpers import (
    ProductionSubmissionError,
    parse_machine_submission_entries,
    execute_machine_submission,
    execute_packaged_submission,
)

bp = Blueprint('production', __name__)


@bp.route('/production')
@employee_required
def production_form():
    """Combined production submission and bag count form"""
    try:
        with db_read_only() as conn:
            # Get product list for dropdown (exclude bottle-only products and variety packs)
            products = conn.execute('''
            SELECT pd.id, pd.product_name, pd.tablet_type_id, pd.category,
                   tt.tablet_type_name, tt.category as tablet_category,
                   pd.packages_per_display, pd.tablets_per_package,
                   pd.is_bottle_product, pd.tablets_per_bottle, pd.bottles_per_display
            FROM product_details pd
            LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            WHERE pd.is_variety_pack = 0
            AND (pd.is_bottle_product = 0 OR pd.is_bottle_product IS NULL)
            ORDER BY COALESCE(pd.category, tt.category, 'ZZZ'), pd.product_name
            ''').fetchall()
            
            # Convert to list of dicts
            products = [dict(p) for p in products]
            
            # Get all tablet types for bag count dropdown
            tablet_types_raw = conn.execute('''
                SELECT * FROM tablet_types 
                ORDER BY tablet_type_name
            ''').fetchall()
            
            # Convert to list of dicts for proper JSON serialization
            tablet_types = [dict(tt) for tt in tablet_types_raw]
            
            # Get employee info for display (handle admin users)
            employee = None
            if session.get('admin_authenticated'):
                # Create a mock employee object for admin
                class MockEmployee:
                    full_name = 'Admin'
                employee = MockEmployee()
            elif session.get('employee_id'):
                employee = conn.execute('''
                    SELECT full_name FROM employees WHERE id = ?
                ''', (session.get('employee_id'),)).fetchone()
            
            # Get today's date for the date picker
            today_date = datetime.now().date().isoformat()
            
            # Check if user is admin or manager (for admin notes access)
            is_admin = session.get('admin_authenticated') or session.get('employee_role') in ['admin', 'manager']
            
            return render_template('production.html', products=products, tablet_types=tablet_types, employee=employee, today_date=today_date, is_admin=is_admin)
    except Exception as e:
        # Log error and re-raise to let Flask handle it
        current_app.logger.error(f"Error in production_form(): {str(e)}")
        raise


@bp.route('/warehouse')
@employee_required
def warehouse_form():
    """Legacy route - redirects to production page"""
    return redirect(url_for('production.production_form'))


@bp.route('/count')
@employee_required
def count_form():
    """Legacy route - redirects to production page"""
    return redirect(url_for('production.production_form'))


@bp.route('/api/submissions/packaged', methods=['POST'])
@employee_required
def submit_warehouse():
    """Process warehouse submission and update PO counts"""
    try:
        data = request.get_json() if request.is_json else request.form

        if not (data.get('product_name') or '').strip() and not data.get('product_id'):
            return jsonify({'error': 'product_name is required'}), 400

        ensure_submission_type_column()

        with db_transaction() as conn:
            employee_result = resolve_submission_employee_name(
                conn,
                data.get('employee_name'),
                session.get('employee_id'),
                bool(session.get('admin_authenticated')),
            )
            if not employee_result.get('success'):
                return jsonify({'error': employee_result.get('error', 'Employee resolution failed')}), employee_result.get('status_code', 400)
            employee_name = employee_result['employee_name']
            result = execute_packaged_submission(conn, data, employee_name)
        return jsonify(result), 200
    except ProductionSubmissionError as e:
        return jsonify(e.body), e.status_code
    except Exception as e:
        current_app.logger.error(f"Error in submit_warehouse: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/submissions/bag-count', methods=['POST'])
def submit_count():
    """Process manual count submission for PO close-outs - RECEIVE-BASED TRACKING
    
    Bag counts are for RAW MATERIAL (entire bags of tablets), not packaged products.
    Use tablet_type_id since we're counting unpackaged tablets.
    """
    try:
        data = request.get_json() if request.is_json else request.form
        
        # Ensure submission_type column exists
        ensure_submission_type_column()
        
        # Validate required fields
        tablet_type_id = data.get('tablet_type_id')
        if not tablet_type_id:
            return jsonify({'error': 'Tablet type is required'}), 400
        
        with db_transaction() as conn:
            employee_result = resolve_submission_employee_name(
                conn,
                data.get('employee_name'),
                session.get('employee_id'),
                bool(session.get('admin_authenticated')),
            )
            if not employee_result.get('success'):
                return jsonify({'error': employee_result.get('error', 'Employee resolution failed')}), employee_result.get('status_code', 400)
            employee_name = employee_result['employee_name']
            
            # Get tablet type details
            tablet_type = conn.execute('''
                SELECT id, tablet_type_name, inventory_item_id
                FROM tablet_types
                WHERE id = ?
            ''', (tablet_type_id,)).fetchone()
            
            if not tablet_type:
                return jsonify({'error': 'Tablet type not found'}), 400
            
            # Convert Row to dict for safe access
            tablet_type = dict(tablet_type)
            
            # Extract values
            inventory_item_id = tablet_type.get('inventory_item_id')
            if not inventory_item_id:
                return jsonify({'error': 'Tablet type inventory_item_id not found'}), 400
            
            # Safe type conversion
            try:
                actual_count = int(data.get('actual_count', 0) or 0)
            except (ValueError, TypeError):
                return jsonify({'error': 'Invalid numeric values for counts'}), 400
            
            # Get submission_date (defaults to today if not provided)
            submission_date = data.get('submission_date', datetime.now().date().isoformat())
            
            # Notes are optional and available to all users.
            admin_notes = normalize_optional_text(data.get('admin_notes', ''))
            
            # RECEIVE-BASED TRACKING: Find matching bag in receives
            # NEW: Pass bag_number first, box_number as optional parameter
            # Bag count submissions: exclude closed bags
            bag, needs_review, error_message = find_bag_for_submission(
                conn, tablet_type_id, data.get('bag_number'), data.get('box_number'), submission_type='bag'
            )
            
            if error_message:
                return jsonify({'error': error_message}), 404
            
            # If needs_review, bag will be None (ambiguous submission)
            bag_id = bag['id'] if bag else None
            assigned_po_id = bag['po_id'] if bag else None
            # Use box_number from matched bag if available (ensures we store actual box_number)
            submission_box_number = bag.get('box_number') if bag else data.get('box_number')
            
            # Insert count record with bag_id (or NULL if needs review)
            # Use tablet_type_name for product_name since this is raw material counting
            conn.execute('''
            INSERT INTO warehouse_submissions 
            (employee_name, product_name, inventory_item_id, box_number, bag_number, 
             bag_id, assigned_po_id, needs_review, loose_tablets, 
             submission_date, admin_notes, submission_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'bag')
            ''', (employee_name, tablet_type.get('tablet_type_name'), inventory_item_id, submission_box_number,
                  data.get('bag_number'), bag_id, assigned_po_id, needs_review,
                  actual_count, submission_date, admin_notes))
            
            message = 'Count flagged for manager review - multiple matching receives found.' if needs_review else 'Bag count submitted successfully!'
            
            return jsonify({
                'success': True,
                'message': message,
                'bag_id': bag_id,
                'po_id': assigned_po_id,
                'needs_review': needs_review
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/submissions/production-combined', methods=['POST'])
@employee_required
def submit_production_combined():
    """Machine submission then packaged submission in one database transaction."""
    try:
        data = request.get_json()
        ensure_submission_type_column()
        ensure_machine_counts_table()
        ensure_machine_count_columns()

        if not data.get('product_id'):
            return jsonify({'error': 'Product is required'}), 400

        entries, err_msg = parse_machine_submission_entries(data)
        if err_msg:
            return jsonify({'error': err_msg}), 400

        if not (data.get('receipt_number') or '').strip():
            return jsonify({'error': 'Receipt number is required'}), 400

        if 'displays_made' not in data or 'packs_remaining' not in data:
            return jsonify({'error': 'displays_made and packs_remaining are required'}), 400

        packaged_data = dict(data)

        with db_transaction() as conn:
            employee_result = resolve_submission_employee_name(
                conn,
                data.get('employee_name'),
                session.get('employee_id'),
                bool(session.get('admin_authenticated')),
            )
            if not employee_result.get('success'):
                return jsonify({'error': employee_result.get('error', 'Employee resolution failed')}), employee_result.get('status_code', 400)
            employee_name = employee_result['employee_name']
            machine_result = execute_machine_submission(conn, data, employee_name, entries)
            packaged_result = execute_packaged_submission(conn, packaged_data, employee_name)

        return jsonify({
            'success': True,
            'message': 'Machine and packaged submissions saved.',
            'machine': machine_result,
            'packaged': packaged_result,
        }), 200
    except ProductionSubmissionError as e:
        return jsonify(e.body), e.status_code
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/submissions/machine-count', methods=['POST'])
@employee_required
def submit_machine_count():
    """Submit machine count reading(s) and create warehouse submission row(s)."""
    try:
        data = request.get_json()

        ensure_submission_type_column()
        ensure_machine_counts_table()
        ensure_machine_count_columns()

        product_id = data.get('product_id')

        if not product_id:
            return jsonify({'error': 'Product is required'}), 400

        entries, err_msg = parse_machine_submission_entries(data)
        if err_msg:
            return jsonify({'error': err_msg}), 400

        with db_transaction() as conn:
            employee_result = resolve_submission_employee_name(
                conn,
                data.get('employee_name'),
                session.get('employee_id'),
                bool(session.get('admin_authenticated')),
            )
            if not employee_result.get('success'):
                return jsonify({'error': employee_result.get('error', 'Employee resolution failed')}), employee_result.get('status_code', 400)
            employee_name = employee_result['employee_name']
            result = execute_machine_submission(conn, data, employee_name, entries)
        return jsonify(result), 200
    except ProductionSubmissionError as e:
        return jsonify(e.body), e.status_code
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@bp.route('/api/machine-count/by-receipt', methods=['GET'])
@employee_required
def get_machine_count_by_receipt():
    """
    Lookup machine count submission by receipt number
    Returns box_number, bag_number, tablet_type_id, and tablet_type_name
    for use in packaging submission
    """
    try:
        receipt_number = request.args.get('receipt')
        
        if not receipt_number:
            return jsonify({'error': 'Receipt number required'}), 400
        
        with db_read_only() as conn:
            # Find all machine count submissions with this receipt number
            # Join with product_details and tablet_types to get tablet type info
            machine_counts = conn.execute('''
            SELECT ws.id, ws.box_number, ws.bag_number, ws.product_name,
                   ws.displays_made as turns, ws.employee_name, ws.submission_date,
                   ws.inventory_item_id, ws.bag_id, ws.machine_id, ws.bag_start_time,
                   pd.tablet_type_id, tt.tablet_type_name
            FROM warehouse_submissions ws
            JOIN product_details pd ON ws.product_name = pd.product_name
            JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            WHERE ws.receipt_number = ?
            AND ws.submission_type = 'machine'
            ORDER BY ws.created_at ASC
        ''', (receipt_number,)).fetchall()
        
        if len(machine_counts) == 0:
            return jsonify({
                'success': False,
                'error': 'No machine count found for this receipt number'
            })
        rows = [dict(mc) for mc in machine_counts]
        inv_ids = {r['inventory_item_id'] for r in rows}
        bag_ids = {r['bag_id'] for r in rows}
        if len(inv_ids) > 1 or len(bag_ids) > 1:
            return jsonify({
                'success': False,
                'inconsistent_receipt': True,
                'matches': rows,
                'error': (
                    'Machine counts on this receipt disagree on product or bag assignment. '
                    'Enter box/bag manually or ask a manager to fix the submissions.'
                ),
            })
        return jsonify({
            'success': True,
            'machine_count': rows[0],
            'machine_counts': rows,
            'machine_count_total': len(rows),
        })
    except Exception as e:
        current_app.logger.error(f"Error in get_machine_count_by_receipt: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/submissions/bottles', methods=['POST'])
@employee_required
def submit_bottles():
    """Submit bottle production - for bottle-only products and variety packs
    
    For bottle-only products: User specifies bag, deducts from that bag
    For variety packs: Auto-deducts from reserved bags per flavor based on config
    """
    try:
        data = request.get_json()
        
        # Ensure submission_type column exists
        ensure_submission_type_column()
        
        # Required fields - using product_details.id
        product_id = data.get('product_id')
        displays_made = data.get('displays_made', 0) or 0
        bottles_remaining = data.get('bottles_remaining', 0) or 0
        
        if not product_id:
            return jsonify({'error': 'Product is required'}), 400
        
        with db_transaction() as conn:
            employee_result = resolve_submission_employee_name(
                conn,
                data.get('employee_name'),
                session.get('employee_id'),
                bool(session.get('admin_authenticated')),
            )
            if not employee_result.get('success'):
                return jsonify({'error': employee_result.get('error', 'Employee resolution failed')}), employee_result.get('status_code', 400)
            employee_name = employee_result['employee_name']
            
            # Get product details (now from product_details table)
            product = conn.execute('''
                SELECT pd.*, tt.tablet_type_name, tt.inventory_item_id
                FROM product_details pd
                LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                WHERE pd.id = ?
            ''', (product_id,)).fetchone()
            
            if not product:
                return jsonify({'error': 'Product not found'}), 400
            
            product = dict(product)
            is_variety_pack = product.get('is_variety_pack', False)
            is_bottle_product = product.get('is_bottle_product', False)
            tablets_per_bottle = product.get('tablets_per_bottle', 0) or 0
            bottles_per_display = product.get('bottles_per_display', 0) or 0
            
            # Calculate total bottles made = (displays × bottles/display) + remaining
            bottles_made = (displays_made * bottles_per_display) + bottles_remaining
            
            if not is_variety_pack and not is_bottle_product:
                return jsonify({'error': 'This product is not configured for bottle production'}), 400
            
            # Get submission_date, receipt_number, and admin_notes
            submission_date = data.get('submission_date', datetime.now().date().isoformat())
            receipt_number = (data.get('receipt_number') or '').strip() or None
            admin_notes = normalize_optional_text(data.get('admin_notes', ''))
            
            deduction_details = []
            
            if is_variety_pack:
                # Variety pack: deduct from reserved bags per flavor
                variety_contents = product.get('variety_pack_contents')
                if not variety_contents:
                    return jsonify({'error': 'Variety pack contents not configured'}), 400
                
                try:
                    import json
                    contents = json.loads(variety_contents)
                except (json.JSONDecodeError, TypeError):
                    return jsonify({'error': 'Invalid variety pack contents configuration'}), 400
                
                # Deduct from reserved bags for each flavor
                for flavor in contents:
                    flavor_tt_id = flavor.get('tablet_type_id')
                    tablets_per_flavor = flavor.get('tablets_per_bottle', 0)
                    tablets_needed = bottles_made * tablets_per_flavor
                    
                    if tablets_needed <= 0:
                        continue
                    
                    # Find reserved bags for this flavor
                    reserved_bags = conn.execute('''
                        SELECT b.id, b.bag_number, b.bag_label_count, b.pill_count,
                               sb.box_number, tt.tablet_type_name, r.po_id
                        FROM bags b
                        JOIN small_boxes sb ON b.small_box_id = sb.id
                        JOIN receiving r ON sb.receiving_id = r.id
                        LEFT JOIN tablet_types tt ON b.tablet_type_id = tt.id
                        WHERE b.tablet_type_id = ?
                        AND b.reserved_for_bottles = 1
                        AND COALESCE(b.status, 'Available') != 'Closed'
                        ORDER BY b.bag_number
                    ''', (flavor_tt_id,)).fetchall()
                    
                    if not reserved_bags:
                        return jsonify({
                            'error': f'No reserved bags found for flavor ID {flavor_tt_id}. Please reserve bags first.'
                        }), 400
                    
                    # Calculate remaining tablets per bag and deduct
                    tablets_still_needed = tablets_needed
                    for bag_row in reserved_bags:
                        if tablets_still_needed <= 0:
                            break
                        
                        bag = dict(bag_row)
                        original_count = bag.get('bag_label_count') or bag.get('pill_count') or 0
                        
                        # Get already packaged count for this bag
                        packaged_total = conn.execute('''
                            SELECT COALESCE(SUM(
                                (COALESCE(ws.displays_made, 0) * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
                                (COALESCE(ws.packs_remaining, 0) * COALESCE(pd.tablets_per_package, 0))
                            ), 0) as total
                            FROM warehouse_submissions ws
                            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                            WHERE ws.bag_id = ? AND ws.submission_type = 'packaged'
                        ''', (bag['id'],)).fetchone()
                        
                        # Bottle submissions (bottle-only products with bag_id)
                        bottle_direct = conn.execute('''
                            SELECT COALESCE(SUM(
                                COALESCE(ws.bottles_made, 0) * COALESCE(pd.tablets_per_bottle, 0)
                            ), 0) as total
                            FROM warehouse_submissions ws
                            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                            WHERE ws.submission_type = 'bottle' AND ws.bag_id = ?
                        ''', (bag['id'],)).fetchone()
                        
                        # Variety pack deductions via junction table
                        bottle_junction = conn.execute('''
                            SELECT COALESCE(SUM(sbd.tablets_deducted), 0) as total
                            FROM submission_bag_deductions sbd
                            WHERE sbd.bag_id = ?
                        ''', (bag['id'],)).fetchone()
                        
                        already_used = (packaged_total['total'] if packaged_total else 0) + \
                                       (bottle_direct['total'] if bottle_direct else 0) + \
                                       (bottle_junction['total'] if bottle_junction else 0)
                        remaining = max(0, original_count - already_used)
                        
                        if remaining <= 0:
                            continue
                        
                        tablets_to_deduct = min(remaining, tablets_still_needed)
                        tablets_still_needed -= tablets_to_deduct
                        
                        deduction_details.append({
                            'bag_id': bag['id'],
                            'tablet_type_name': bag.get('tablet_type_name'),
                            'bag_number': bag.get('bag_number'),
                            'box_number': bag.get('box_number'),
                            'tablets_deducted': tablets_to_deduct,
                            'po_id': bag.get('po_id')
                        })
                    
                    if tablets_still_needed > 0:
                        return jsonify({
                            'error': f'Not enough tablets in reserved bags for {flavor.get("tablet_type_name", "flavor")}. Need {tablets_needed}, only have {tablets_needed - tablets_still_needed} available.'
                        }), 400
                
                # Create ONE submission record for the variety pack
                conn.execute('''
                    INSERT INTO warehouse_submissions 
                    (employee_name, product_name, inventory_item_id, bottles_made, displays_made,
                     packs_remaining, submission_date, receipt_number, admin_notes, submission_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'bottle')
                ''', (employee_name, product.get('product_name'), 
                      product.get('inventory_item_id'), bottles_made, displays_made,
                      bottles_remaining, submission_date, receipt_number, admin_notes))
                
                # Get the submission ID we just created
                submission_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
                
                # Create junction table entries for each bag deduction
                for deduction in deduction_details:
                    conn.execute('''
                        INSERT INTO submission_bag_deductions 
                        (submission_id, bag_id, tablets_deducted)
                        VALUES (?, ?, ?)
                    ''', (submission_id, deduction.get('bag_id'), deduction.get('tablets_deducted')))
                
            else:
                # Bottle-only product: deduct from user-specified bag
                bag_number = data.get('bag_number')
                box_number = data.get('box_number')
                
                if not bag_number:
                    return jsonify({'error': 'Bag number is required for bottle-only products'}), 400
                
                # Find the bag using product's tablet_type_id
                tablet_type_id_for_bag = product.get('tablet_type_id')
                bag, needs_review, error_message = find_bag_for_submission(
                    conn, tablet_type_id_for_bag, bag_number, box_number, submission_type='bottle'
                )
                
                if error_message:
                    return jsonify({'error': error_message}), 404
                
                bag_id = bag['id'] if bag else None
                assigned_po_id = bag['po_id'] if bag else None
                submission_box_number = bag.get('box_number') if bag else box_number
                
                # Calculate tablets used
                tablets_used = bottles_made * tablets_per_bottle
                
                # Verify bag has enough tablets
                if bag:
                    original_count = bag.get('bag_label_count') or bag.get('pill_count') or 0
                    
                    # Packaged submissions (card products)
                    packaged_total = conn.execute('''
                        SELECT COALESCE(SUM(
                            (COALESCE(ws.displays_made, 0) * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
                            (COALESCE(ws.packs_remaining, 0) * COALESCE(pd.tablets_per_package, 0))
                        ), 0) as total
                        FROM warehouse_submissions ws
                        LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                        WHERE ws.bag_id = ? AND ws.submission_type = 'packaged'
                    ''', (bag['id'],)).fetchone()
                    
                    # Bottle submissions (bottle-only products with bag_id)
                    bottle_direct = conn.execute('''
                        SELECT COALESCE(SUM(
                            COALESCE(ws.bottles_made, 0) * COALESCE(pd.tablets_per_bottle, 0)
                        ), 0) as total
                        FROM warehouse_submissions ws
                        LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                        WHERE ws.submission_type = 'bottle' AND ws.bag_id = ?
                    ''', (bag['id'],)).fetchone()
                    
                    # Variety pack deductions via junction table
                    bottle_junction = conn.execute('''
                        SELECT COALESCE(SUM(sbd.tablets_deducted), 0) as total
                        FROM submission_bag_deductions sbd
                        WHERE sbd.bag_id = ?
                    ''', (bag['id'],)).fetchone()
                    
                    already_used = (packaged_total['total'] if packaged_total else 0) + \
                                   (bottle_direct['total'] if bottle_direct else 0) + \
                                   (bottle_junction['total'] if bottle_junction else 0)
                    remaining = max(0, original_count - already_used)
                    
                    # Check if submission exceeds remaining count - warn but don't block
                    overpack_warning = None
                    if tablets_used > remaining:
                        overpack_warning = f'⚠️ Bag may be overpacked: Need {tablets_used}, only {remaining} calculated remaining. Submission allowed but flagged for review.'
                        current_app.logger.warning(f"Bottle submission for bag {bag['id']}: {overpack_warning}")
                    
                    deduction_details.append({
                        'bag_id': bag['id'],
                        'tablet_type_name': product.get('tablet_type_name') or product.get('product_name'),
                        'bag_number': bag.get('bag_number'),
                        'box_number': bag.get('box_number'),
                        'tablets_deducted': tablets_used,
                        'po_id': assigned_po_id,
                        'overpack_warning': overpack_warning
                    })
                
                # Create submission record for bottle-only product
                conn.execute('''
                    INSERT INTO warehouse_submissions 
                    (employee_name, product_name, inventory_item_id, box_number, bag_number,
                     bag_id, assigned_po_id, needs_review, bottles_made, displays_made,
                     packs_remaining, submission_date, receipt_number, admin_notes, submission_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'bottle')
                ''', (employee_name, product.get('product_name'), 
                      product.get('inventory_item_id'), submission_box_number, bag_number,
                      bag_id, assigned_po_id, needs_review, bottles_made, displays_made,
                      bottles_remaining, submission_date, receipt_number, admin_notes))
            
            total_tablets = bottles_made * tablets_per_bottle if tablets_per_bottle else sum(d['tablets_deducted'] for d in deduction_details)
            
            # Check if any deductions have warnings
            warnings = [d.get('overpack_warning') for d in deduction_details if d.get('overpack_warning')]
            warning_message = warnings[0] if warnings else None
            
            return jsonify({
                'success': True,
                'message': f'Bottle submission recorded: {bottles_made} bottles ({total_tablets} tablets)',
                'warning': warning_message,
                'bottles_made': bottles_made,
                'displays_made': displays_made,
                'total_tablets': total_tablets,
                'deduction_details': deduction_details
            })
    except Exception as e:
        current_app.logger.error(f"Error in submit_bottles: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/bottle-products', methods=['GET'])
@employee_required
def get_bottle_products():
    """Get products that can be used with the bottles form
    
    Returns products where is_bottle_product = true OR is_variety_pack = true
    """
    try:
        with db_read_only() as conn:
            products = conn.execute('''
                SELECT pd.id, pd.product_name, pd.tablet_type_id,
                       pd.is_bottle_product, pd.is_variety_pack, 
                       pd.tablets_per_bottle, pd.bottles_per_display,
                       pd.variety_pack_contents,
                       tt.tablet_type_name, tt.inventory_item_id
                FROM product_details pd
                LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                WHERE pd.is_bottle_product = 1 OR pd.is_variety_pack = 1
                ORDER BY pd.product_name
            ''').fetchall()
            
            return jsonify({
                'success': True,
                'products': [dict(p) for p in products]
            })
    except Exception as e:
        current_app.logger.error(f"Error getting bottle products: {e}")
        return jsonify({'error': str(e)}), 500


def _repack_lines_from_request(data):
    """Single product or multi-line batch sharing one receipt."""
    if not data:
        return None
    lines = data.get('lines')
    if lines and isinstance(lines, list):
        return lines
    if data.get('product_name'):
        return [
            {
                'product_name': data.get('product_name'),
                'displays_made': data.get('displays_made', 0),
                'packs_remaining': data.get('packs_remaining', 0),
            }
        ]
    return None


@bp.route('/api/submissions/repack/preview', methods=['POST'])
@employee_required
def repack_preview():
    """
    Dry-run bag allocation for one or more repack lines (same PO). Does not write to the database.
    """
    try:
        ensure_submission_type_column()
        data = request.get_json() if request.is_json else None
        if not data:
            return jsonify({'error': 'JSON body required'}), 400
        po_id = data.get('po_id')
        if not po_id:
            return jsonify({'error': 'po_id is required'}), 400
        try:
            po_id = int(po_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'po_id must be an integer'}), 400

        lines = _repack_lines_from_request(data)
        if not lines:
            return jsonify({'error': 'Provide product_name or lines[] with repack rows'}), 400

        previews = []
        with db_read_only() as conn:
            po_row = conn.execute(
                'SELECT id, closed FROM purchase_orders WHERE id = ?',
                (po_id,),
            ).fetchone()
            if not po_row:
                return jsonify({'error': 'Purchase order not found'}), 404
            if po_row['closed']:
                return jsonify({'error': 'PO is closed'}), 400

            for line in lines:
                product_name = (line.get('product_name') or '').strip()
                if not product_name:
                    return jsonify({'error': 'Each line must include product_name'}), 400
                try:
                    displays_made = int(line.get('displays_made', 0) or 0)
                    packs_remaining = int(line.get('packs_remaining', 0) or 0)
                except (TypeError, ValueError):
                    return jsonify({'error': 'Invalid displays_made or packs_remaining'}), 400

                product = conn.execute(
                    """
                    SELECT pd.*, tt.inventory_item_id, tt.id AS tablet_type_id, tt.tablet_type_name
                    FROM product_details pd
                    JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                    WHERE pd.product_name = ?
                    """,
                    (product_name,),
                ).fetchone()
                if not product:
                    return jsonify({'error': f"Product '{product_name}' not found"}), 400
                product = dict(product)
                if product.get('is_bottle_product') or product.get('is_variety_pack'):
                    return jsonify(
                        {'error': f"Repack is not available for bottle/variety product '{product_name}'"}
                    ), 400

                ppd = int(product.get('packages_per_display') or 0)
                tpp = int(product.get('tablets_per_package') or 0)
                if ppd <= 0 or tpp <= 0:
                    return jsonify(
                        {'error': f"Product '{product_name}' needs packages_per_display and tablets_per_package"}
                    ), 400

                inventory_item_id = product.get('inventory_item_id')
                tablet_type_id = product.get('tablet_type_id')
                if not inventory_item_id or not tablet_type_id:
                    return jsonify({'error': 'Product missing inventory_item_id or tablet_type'}), 400

                line_check = conn.execute(
                    """
                    SELECT 1 FROM po_lines pl
                    WHERE pl.po_id = ? AND pl.inventory_item_id = ?
                    LIMIT 1
                    """,
                    (po_id, inventory_item_id),
                ).fetchone()
                if not line_check:
                    return jsonify(
                        {'error': f"PO does not include line item for product '{product_name}'"}
                    ), 400

                sub = {'displays_made': displays_made, 'packs_remaining': packs_remaining}
                output_good = calculate_repack_output_good(sub, ppd, tpp)
                alloc_payload, alloc_needs_review = allocate_repack_tablets(
                    conn, po_id, tablet_type_id, output_good
                )
                previews.append(
                    {
                        'product_name': product_name,
                        'output_tablets': output_good,
                        'needs_review': bool(alloc_needs_review),
                        'allocation': json.loads(allocation_payload_to_json(alloc_payload)),
                    }
                )

        return jsonify({'success': True, 'previews': previews})
    except Exception as e:
        current_app.logger.error(f"repack_preview: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/submissions/repack/eligible-pos', methods=['GET'])
@employee_required
def repack_eligible_pos():
    """Open POs for repack PO selector (excludes Draft)."""
    try:
        with db_read_only() as conn:
            po_columns = [row["name"] for row in conn.execute("PRAGMA table_info(purchase_orders)").fetchall()]
            has_vendor_name = "vendor_name" in po_columns
            vendor_select = "vendor_name" if has_vendor_name else "NULL AS vendor_name"
            rows = conn.execute(
                f"""
                SELECT id, po_number, internal_status, {vendor_select}
                FROM purchase_orders
                WHERE closed = FALSE AND COALESCE(internal_status, '') != 'Draft'
                ORDER BY po_number DESC
                """
            ).fetchall()
            return jsonify({'success': True, 'pos': [dict(r) for r in rows]})
    except Exception as e:
        current_app.logger.error(f"repack_eligible_pos: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/api/submissions/repack', methods=['POST'])
@employee_required
def submit_repack():
    """
    Tablet search / repack: credits finished displays and partial cards to PO good_count only.
    One receipt may have multiple rows (one per flavor) via `lines` array.
    """
    try:
        ensure_submission_type_column()
        data = request.get_json() if request.is_json else request.form
        if not data:
            return jsonify({'error': 'JSON body required'}), 400

        po_id = data.get('po_id')
        receipt_number = (data.get('receipt_number') or '').strip()
        if not po_id:
            return jsonify({'error': 'po_id is required'}), 400
        try:
            po_id = int(po_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'po_id must be an integer'}), 400
        if not receipt_number:
            return jsonify({'error': 'receipt_number is required'}), 400

        try:
            repack_machine_count = int(data.get('repack_machine_count', 0) or 0)
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid repack_machine_count'}), 400
        if repack_machine_count < 0:
            repack_machine_count = 0

        lines = _repack_lines_from_request(data)
        if not lines:
            return jsonify({'error': 'Provide product_name or lines[] with repack rows'}), 400

        submission_date = data.get('submission_date', datetime.now().date().isoformat())
        admin_notes = normalize_optional_text(data.get('admin_notes'))
        vendor_notes = normalize_optional_text(
            data.get('repack_vendor_return_notes') or data.get('vendor_return_notes')
        )

        created = []
        with db_transaction() as conn:
            employee_result = resolve_submission_employee_name(
                conn,
                data.get('employee_name'),
                session.get('employee_id'),
                bool(session.get('admin_authenticated')),
            )
            if not employee_result.get('success'):
                return jsonify({'error': employee_result.get('error', 'Employee resolution failed')}), employee_result.get('status_code', 400)
            employee_name = employee_result['employee_name']

            po_row = conn.execute(
                'SELECT id, closed FROM purchase_orders WHERE id = ?',
                (po_id,),
            ).fetchone()
            if not po_row:
                return jsonify({'error': 'Purchase order not found'}), 404
            if po_row['closed']:
                return jsonify({'error': 'Cannot add repack to a closed PO'}), 400

            for line in lines:
                product_name = (line.get('product_name') or '').strip()
                if not product_name:
                    return jsonify({'error': 'Each line must include product_name'}), 400
                try:
                    displays_made = int(line.get('displays_made', 0) or 0)
                    packs_remaining = int(line.get('packs_remaining', 0) or 0)
                except (TypeError, ValueError):
                    return jsonify({'error': 'Invalid displays_made or packs_remaining'}), 400

                product = conn.execute(
                    """
                    SELECT pd.*, tt.inventory_item_id, tt.id AS tablet_type_id, tt.tablet_type_name
                    FROM product_details pd
                    JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                    WHERE pd.product_name = ?
                    """,
                    (product_name,),
                ).fetchone()
                if not product:
                    return jsonify({'error': f"Product '{product_name}' not found"}), 400
                product = dict(product)
                if product.get('is_bottle_product') or product.get('is_variety_pack'):
                    return jsonify(
                        {'error': f"Repack is not available for bottle/variety product '{product_name}'"}
                    ), 400

                ppd = int(product.get('packages_per_display') or 0)
                tpp = int(product.get('tablets_per_package') or 0)
                if ppd <= 0 or tpp <= 0:
                    return jsonify(
                        {'error': f"Product '{product_name}' needs packages_per_display and tablets_per_package"}
                    ), 400

                inventory_item_id = product.get('inventory_item_id')
                tablet_type_id = product.get('tablet_type_id')
                if not inventory_item_id or not tablet_type_id:
                    return jsonify({'error': 'Product missing inventory_item_id or tablet_type'}), 400

                line_check = conn.execute(
                    """
                    SELECT 1 FROM po_lines pl
                    WHERE pl.po_id = ? AND pl.inventory_item_id = ?
                    LIMIT 1
                    """,
                    (po_id, inventory_item_id),
                ).fetchone()
                if not line_check:
                    return jsonify(
                        {'error': f"PO does not include line item for product '{product_name}'"}
                    ), 400

                dup = conn.execute(
                    """
                    SELECT id FROM warehouse_submissions
                    WHERE receipt_number = ? AND submission_type = 'repack'
                    AND inventory_item_id = ?
                    LIMIT 1
                    """,
                    (receipt_number, inventory_item_id),
                ).fetchone()
                if dup:
                    return jsonify(
                        {
                            'error': (
                                f"Receipt {receipt_number} already used for repack of this product "
                                f"(submission id {dup['id']})."
                            )
                        }
                    ), 400

                sub = {
                    'displays_made': displays_made,
                    'packs_remaining': packs_remaining,
                }
                output_good = calculate_repack_output_good(sub, ppd, tpp)
                if output_good <= 0:
                    return jsonify(
                        {'error': f"No finished output for '{product_name}' (displays/packs are zero)"}
                    ), 400

                alloc_payload, alloc_needs_review = allocate_repack_tablets(
                    conn, po_id, tablet_type_id, output_good
                )
                alloc_json = allocation_payload_to_json(alloc_payload)
                needs_review = bool(alloc_needs_review)

                first_bag_id = None
                for a in alloc_payload.get('allocations') or []:
                    if a.get('bag_id') is not None and not a.get('overflow'):
                        first_bag_id = a['bag_id']
                        break

                conn.execute(
                    """
                    INSERT INTO warehouse_submissions
                    (employee_name, product_name, inventory_item_id, box_number, bag_number,
                     displays_made, packs_remaining, loose_tablets, damaged_tablets,
                     submission_date, admin_notes, submission_type,
                     bag_id, assigned_po_id, needs_review, receipt_number,
                     repack_bag_allocations, repack_vendor_return_notes, repack_allocation_version,
                     repack_machine_count)
                    VALUES (?, ?, ?, NULL, NULL, ?, ?, 0, 0, ?, ?, 'repack',
                            ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        employee_name,
                        product_name,
                        inventory_item_id,
                        displays_made,
                        packs_remaining,
                        submission_date,
                        admin_notes,
                        first_bag_id,
                        po_id,
                        needs_review,
                        receipt_number,
                        alloc_json,
                        vendor_notes,
                        alloc_payload.get('version', 1),
                        repack_machine_count,
                    ),
                )
                new_id = conn.execute('SELECT last_insert_rowid() AS id').fetchone()['id']

                if not apply_po_line_delta(conn, po_id, inventory_item_id, output_good, 0):
                    raise RuntimeError(f"Failed to update PO line for {product_name}")

                created.append(
                    {
                        'submission_id': new_id,
                        'product_name': product_name,
                        'output_tablets': output_good,
                        'needs_review': needs_review,
                        'allocation': json.loads(alloc_json),
                    }
                )

        return jsonify(
            {
                'success': True,
                'message': f"Recorded {len(created)} repack submission(s)",
                'created': created,
            }
        )
    except Exception as e:
        current_app.logger.error(f"submit_repack: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# Backwards-compatible route aliases (deprecated)
@bp.route('/submit_warehouse', methods=['POST'])
@employee_required
def submit_warehouse_deprecated():
    """DEPRECATED: Use /api/submissions/packaged instead"""
    import logging
    logging.warning("Route /submit_warehouse is deprecated, use /api/submissions/packaged instead")
    return submit_warehouse()

@bp.route('/submit_count', methods=['POST'])
@employee_required
def submit_count_deprecated():
    """DEPRECATED: Use /api/submissions/bag-count instead"""
    import logging
    logging.warning("Route /submit_count is deprecated, use /api/submissions/bag-count instead")
    return submit_count()

@bp.route('/submit_machine_count', methods=['POST'])
@employee_required
def submit_machine_count_deprecated():
    """DEPRECATED: Use /api/submissions/machine-count instead"""
    import logging
    logging.warning("Route /submit_machine_count is deprecated, use /api/submissions/machine-count instead")
    return submit_machine_count()
