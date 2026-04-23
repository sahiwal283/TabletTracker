"""
API routes - all /api/* endpoints
"""
from datetime import datetime, timedelta

from flask import current_app, flash, jsonify, redirect, render_template, request, session, url_for

from app.utils.auth_utils import (
    employee_required,
    role_required,
    verify_password,
)
from app.utils.db_utils import db_read_only, db_transaction
from app.utils.receive_tracking import find_bag_for_submission
from app.utils.route_helpers import (
    ensure_machine_count_columns,
    ensure_machine_counts_table,
    ensure_submission_type_column,
    get_setting,
)

from . import bp


@bp.route('/api/po/<int:po_id>/max_bag_numbers', methods=['GET'])
@role_required('shipping')
def get_po_max_bag_numbers(po_id):
    """Get the maximum bag number for each flavor (tablet_type) in a PO across all receives"""
    try:
        with db_read_only() as conn:
            # Get max bag number per tablet_type_id for all bags in this PO
            # Join through receiving -> small_boxes -> bags
            max_bag_numbers = conn.execute('''
                SELECT b.tablet_type_id, MAX(b.bag_number) as max_bag_number
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                WHERE r.po_id = ?
                GROUP BY b.tablet_type_id
            ''', (po_id,)).fetchall()

            # Convert to dictionary: {tablet_type_id: max_bag_number}
            result = {}
            for row in max_bag_numbers:
                result[row['tablet_type_id']] = row['max_bag_number'] or 0

            return jsonify({
                'success': True,
                'max_bag_numbers': result
            })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# Route moved to api_receiving.py

# Route moved to api_purchase_orders.py



@bp.route('/login')
def employee_login():
    """Employee login page"""
    return render_template('employee_login.html')

@bp.route('/login', methods=['POST'])
def employee_login_post():
    """Handle employee login"""
    try:
        username = request.form.get('username') or request.json.get('username')
        password = request.form.get('password') or request.json.get('password')

        if not username or not password:
            if request.form:
                flash('Username and password required', 'error')
                return render_template('employee_login.html')
            else:
                return jsonify({'success': False, 'error': 'Username and password required'})

        with db_read_only() as conn:
            employee = conn.execute('''
            SELECT id, username, full_name, password_hash, role, is_active
            FROM employees
            WHERE username = ? AND is_active = TRUE
            ''', (username,)).fetchone()

            if employee and verify_password(password, employee['password_hash']):
                session['employee_authenticated'] = True
                session['employee_id'] = employee['id']
                session['employee_name'] = employee['full_name']
                session['employee_username'] = employee['username']
                session['employee_role'] = employee['role'] if employee['role'] else 'warehouse_staff'
                session.permanent = True
                current_app.permanent_session_lifetime = timedelta(hours=8)

                return redirect(url_for('production.warehouse_form')) if request.form else jsonify({'success': True})
            else:
                # Log failed login attempt
                current_app.logger.warning(f"Failed employee login attempt for {username} from {request.remote_addr} at {datetime.now()}")

                if request.form:
                    flash('Invalid username or password', 'error')
                    return render_template('employee_login.html')
                else:
                    return jsonify({'success': False, 'error': 'Invalid username or password'})
    except Exception as e:
        # Log error but don't expose details to user
        current_app.logger.error(f"Login error: {str(e)}")
        if request.form:
            flash('An error occurred during login', 'error')
            return render_template('employee_login.html')
        else:
            return jsonify({'success': False, 'error': 'An error occurred during login'}), 500

@bp.route('/logout')
def logout():
    """Unified logout for both employees and admin"""
    # Clear all session data
    session.pop('admin_authenticated', None)
    session.pop('employee_authenticated', None)
    session.pop('employee_id', None)
    session.pop('employee_name', None)
    session.pop('employee_username', None)
    session.pop('employee_role', None)
    session.pop('login_time', None)

    flash('You have been logged out successfully', 'success')
    return redirect(url_for('auth.index'))

@bp.route('/count')
@employee_required
def count_form():
    """Legacy route - redirects to production page"""
    return redirect(url_for('production.production_form'))

@bp.route('/submit_count', methods=['POST'])
def submit_count():
    """Process manual count submission for PO close-outs - RECEIVE-BASED TRACKING"""
    try:
        data = request.get_json() if request.is_json else request.form

        # Ensure submission_type column exists
        ensure_submission_type_column()

        # Validate required fields
        if not data.get('tablet_type'):
            return jsonify({'error': 'tablet_type is required'}), 400

        with db_transaction() as conn:
            # Get employee name from session (logged-in user)
            if session.get('admin_authenticated'):
                employee_name = 'Admin'
            else:
                employee = conn.execute('''
                    SELECT full_name FROM employees WHERE id = ?
                ''', (session.get('employee_id'),)).fetchone()

                if not employee:
                    return jsonify({'error': 'Employee not found'}), 400

                employee_name = employee['full_name']

            # Get tablet type details
            tablet_type = conn.execute('''
                SELECT * FROM tablet_types
                WHERE tablet_type_name = ?
            ''', (data.get('tablet_type'),)).fetchone()

            if not tablet_type:
                return jsonify({'error': 'Tablet type not found'}), 400

            # Convert Row to dict for safe access
            tablet_type = dict(tablet_type)

            # Safe type conversion
            try:
                actual_count = int(data.get('actual_count', 0) or 0)
            except (ValueError, TypeError):
                return jsonify({'error': 'Invalid numeric values for counts'}), 400

            # Get submission_date (defaults to today if not provided)
            submission_date = data.get('submission_date', datetime.now().date().isoformat())

            # Get admin_notes if user is admin or manager
            admin_notes = None
            if session.get('admin_authenticated') or session.get('employee_role') in ['admin', 'manager']:
                admin_notes_raw = data.get('admin_notes', '')
                if admin_notes_raw and isinstance(admin_notes_raw, str):
                    admin_notes = admin_notes_raw.strip() or None
                elif admin_notes_raw:
                    admin_notes = str(admin_notes_raw).strip() or None

            # Get inventory_item_id and tablet_type_id
            inventory_item_id = tablet_type.get('inventory_item_id')
            tablet_type_id = tablet_type.get('id')
            if not inventory_item_id:
                return jsonify({'error': 'Tablet type inventory_item_id not found'}), 400
            if not tablet_type_id:
                return jsonify({'error': 'Tablet type_id not found'}), 400

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

            # Insert count record with bag_id (or NULL if needs review)
            conn.execute('''
                INSERT INTO warehouse_submissions
                (employee_name, product_name, inventory_item_id, box_number, bag_number,
                 bag_id, assigned_po_id, needs_review, loose_tablets,
                 submission_date, admin_notes, submission_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'bag')
            ''', (employee_name, data.get('tablet_type'), inventory_item_id, data.get('box_number'),
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

@bp.route('/submit_machine_count', methods=['POST'])
@employee_required
def submit_machine_count():
    """Submit machine count reading and create warehouse submission"""
    try:
        data = request.get_json()

        # Ensure required tables/columns exist
        ensure_submission_type_column()
        ensure_machine_counts_table()
        ensure_machine_count_columns()

        tablet_type_id = data.get('tablet_type_id')
        machine_count = data.get('machine_count')
        count_date = data.get('count_date')

        # Validation
        if not tablet_type_id:
            return jsonify({'error': 'Tablet type is required'}), 400
        if machine_count is None or machine_count < 0:
            return jsonify({'error': 'Valid machine count is required'}), 400
        if not count_date:
            return jsonify({'error': 'Date is required'}), 400

        with db_transaction() as conn:
            # Get employee name from session (logged-in user)
            if session.get('admin_authenticated'):
                employee_name = 'Admin'
            else:
                employee = conn.execute('''
                    SELECT full_name FROM employees WHERE id = ?
                ''', (session.get('employee_id'),)).fetchone()

                if not employee:
                    return jsonify({'error': 'Employee not found'}), 400

                employee_name = employee['full_name']

            # Verify tablet type exists and get its info
            tablet_type = conn.execute('''
                SELECT id, tablet_type_name, inventory_item_id
                FROM tablet_types
                WHERE id = ?
            ''', (tablet_type_id,)).fetchone()
            if not tablet_type:
                return jsonify({'error': 'Invalid tablet type'}), 400

            tablet_type = dict(tablet_type)

            # Get a product for this tablet type to get tablets_per_package
            product = conn.execute('''
                SELECT product_name, tablets_per_package
                FROM product_details
                WHERE tablet_type_id = ?
                LIMIT 1
            ''', (tablet_type_id,)).fetchone()

            if not product:
                return jsonify({'error': 'No product found for this tablet type. Please configure a product first.'}), 400

            product = dict(product)
            tablets_per_package = product.get('tablets_per_package', 0)

            if tablets_per_package == 0:
                return jsonify({'error': 'Product configuration incomplete: tablets_per_package must be greater than 0'}), 400

            # Get machine_id from form data FIRST (before calculating cards_per_turn)
            machine_id = data.get('machine_id')
            if machine_id:
                try:
                    machine_id = int(machine_id)
                except (ValueError, TypeError):
                    machine_id = None

            # Get machine-specific cards_per_turn from machines table
            cards_per_turn = None
            if machine_id:
                machine_row = conn.execute('''
                    SELECT cards_per_turn FROM machines WHERE id = ?
                ''', (machine_id,)).fetchone()
                if machine_row:
                    machine = dict(machine_row)
                    cards_per_turn = machine.get('cards_per_turn')

            # Fallback to global setting if machine not found or doesn't have cards_per_turn
            if not cards_per_turn:
                cards_per_turn_setting = get_setting('cards_per_turn', '1')
                try:
                    cards_per_turn = int(cards_per_turn_setting)
                except (ValueError, TypeError):
                    cards_per_turn = 1

            # Calculate total tablets for machine submissions
            # Formula: turns × cards_per_turn × tablets_per_package = total tablets pressed into cards
            try:
                machine_count_int = int(machine_count)
                total_tablets = machine_count_int * cards_per_turn * tablets_per_package
                # For machine submissions: these tablets are pressed into blister cards (not loose)
                # Store in a clearly named variable to distinguish from actual loose tablets
                tablets_pressed_into_cards = total_tablets
            except (ValueError, TypeError):
                return jsonify({'error': 'Invalid machine count value'}), 400

            # Insert machine count record (for historical tracking)
            if machine_id:
                conn.execute('''
                    INSERT INTO machine_counts (tablet_type_id, machine_id, machine_count, employee_name, count_date)
                    VALUES (?, ?, ?, ?, ?)
                ''', (tablet_type_id, machine_id, machine_count_int, employee_name, count_date))
            else:
                conn.execute('''
                    INSERT INTO machine_counts (tablet_type_id, machine_count, employee_name, count_date)
                    VALUES (?, ?, ?, ?)
                ''', (tablet_type_id, machine_count_int, employee_name, count_date))

            # Get inventory_item_id and tablet_type_id
            inventory_item_id = tablet_type.get('inventory_item_id')
            tablet_type_id = tablet_type.get('id')

            if not inventory_item_id or not tablet_type_id:
                return jsonify({'warning': 'Tablet type inventory_item_id or id not found. Submission saved but not assigned to PO.', 'submission_saved': True})

            # Get box/bag numbers from form data
            box_number = data.get('box_number')
            bag_number = data.get('bag_number')

            # Get admin_notes if user is admin or manager
            admin_notes = None
            is_admin_or_manager = session.get('admin_authenticated') or session.get('employee_role') in ['admin', 'manager']
            if is_admin_or_manager:
                admin_notes_raw = data.get('admin_notes', '')
                if admin_notes_raw and isinstance(admin_notes_raw, str):
                    admin_notes = admin_notes_raw.strip() or None
                elif admin_notes_raw:
                    # Handle non-string values (shouldn't happen, but be safe)
                    admin_notes = str(admin_notes_raw).strip() or None
                # Debug logging
                current_app.logger.info(f"Machine submission admin_notes: raw='{admin_notes_raw}', processed='{admin_notes}', is_admin={is_admin_or_manager}")

            # RECEIVE-BASED TRACKING: Try to match to existing receive/bag
            bag = None
            needs_review = False
            error_message = None
            assigned_po_id = None
            bag_id = None

            if bag_number:
                # NEW: Pass bag_number first, box_number as optional parameter
                # Machine count submissions: exclude closed bags
                bag, needs_review, error_message = find_bag_for_submission(conn, tablet_type_id, bag_number, box_number, submission_type='machine')

                if bag:
                    # Exact match found - auto-assign
                    bag_id = bag['id']
                    assigned_po_id = bag['po_id']
                    box_ref = f", box={box_number}" if box_number else ""
                    current_app.logger.info(f"✅ Matched to receive: bag_id={bag_id}, po_id={assigned_po_id}, bag={bag_number}{box_ref}")
                elif needs_review:
                    # Multiple matches - needs manual review
                    box_ref = f" Box {box_number}," if box_number else ""
                    current_app.logger.info(f"⚠️ Multiple receives found for{box_ref} Bag {bag_number} - needs review")
                elif error_message:
                    # No match found
                    current_app.logger.info(f"❌ {error_message}")

            # Get receipt_number from form data
            receipt_number = (data.get('receipt_number') or '').strip() or None

            # Create warehouse submission with submission_type='machine'
            # For machine submissions:
            # - displays_made = machine_count_int (turns)
            # - packs_remaining = machine_count_int * cards_per_turn (cards made)
            # - tablets_pressed_into_cards = total tablets pressed into blister cards (properly named column)
            cards_made = machine_count_int * cards_per_turn
            conn.execute('''
                INSERT INTO warehouse_submissions
                (employee_name, product_name, inventory_item_id, box_number, bag_number,
                 displays_made, packs_remaining, tablets_pressed_into_cards,
                 submission_date, submission_type, bag_id, assigned_po_id, needs_review, machine_id, admin_notes, receipt_number)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'machine', ?, ?, ?, ?, ?, ?)
            ''', (employee_name, product['product_name'], inventory_item_id, box_number, bag_number,
                  machine_count_int, cards_made, tablets_pressed_into_cards,
                      count_date, bag_id, assigned_po_id, needs_review, machine_id, admin_notes, receipt_number))

            # If no receive match, submission is saved but not assigned
            if not assigned_po_id:
                if error_message:
                    return jsonify({
                        'success': True,
                        'warning': error_message,
                        'submission_saved': True,
                        'needs_review': needs_review,
                        'message': 'Machine count submitted successfully.'
                    })
                else:
                    return jsonify({
                        'success': True,
                        'warning': 'No receive found for this box/bag combination. Submission saved but not assigned to PO.',
                        'submission_saved': True,
                        'message': 'Machine count submitted successfully.'
                    })

            # Get PO lines for the matched PO to update counts
            po_lines = conn.execute('''
                SELECT pl.*, po.closed
                FROM po_lines pl
                JOIN purchase_orders po ON pl.po_id = po.id
                WHERE pl.inventory_item_id = ? AND po.id = ?
            ''', (inventory_item_id, assigned_po_id)).fetchall()

            # Only allocate to lines from the ASSIGNED PO
            assigned_po_lines = [line for line in po_lines if line['po_id'] == assigned_po_id]

            # Update machine_good_count (separate from regular good_count)
            if assigned_po_lines:
                line = assigned_po_lines[0]
                conn.execute('''
                    UPDATE po_lines
                    SET machine_good_count = machine_good_count + ?
                    WHERE id = ?
                ''', (tablets_pressed_into_cards, line['id']))
                current_app.logger.info(f"Machine count - Updated PO line {line['id']}: +{tablets_pressed_into_cards} tablets pressed into cards")

            # Update PO header totals (separate machine counts)
            updated_pos = set()
            for line in assigned_po_lines:
                if line['po_id'] not in updated_pos:
                    totals = conn.execute('''
                        SELECT
                            COALESCE(SUM(quantity_ordered), 0) as total_ordered,
                            COALESCE(SUM(good_count), 0) as total_good,
                            COALESCE(SUM(damaged_count), 0) as total_damaged,
                            COALESCE(SUM(machine_good_count), 0) as total_machine_good,
                            COALESCE(SUM(machine_damaged_count), 0) as total_machine_damaged
                        FROM po_lines
                        WHERE po_id = ?
                    ''', (line['po_id'],)).fetchone()

                    remaining = totals['total_ordered'] - totals['total_good'] - totals['total_damaged']

                    conn.execute('''
                        UPDATE purchase_orders
                        SET ordered_quantity = ?, current_good_count = ?,
                            current_damaged_count = ?, remaining_quantity = ?,
                            machine_good_count = ?, machine_damaged_count = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    ''', (totals['total_ordered'], totals['total_good'],
                          totals['total_damaged'], remaining,
                          totals['total_machine_good'], totals['total_machine_damaged'],
                          line['po_id']))

                    updated_pos.add(line['po_id'])

            return jsonify({
                'success': True,
                'message': 'Machine count submitted successfully.'
            })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500



# Note: /admin/employees route is in admin.py blueprint, not here

@bp.route('/api/set-language', methods=['POST'])
def set_language():
    """Set language preference for current session and save to employee profile"""
    try:
        data = request.get_json()
        language = data.get('language', '').strip()

        # Validate language
        if language not in current_app.config['LANGUAGES']:
            return jsonify({'success': False, 'error': 'Invalid language'}), 400

        # Set session language with manual override flag
        session['language'] = language
        session['manual_language_override'] = True
        session.permanent = True

        # Save to employee profile if authenticated
        if session.get('employee_authenticated') and session.get('employee_id'):
            try:
                with db_transaction() as conn:
                    conn.execute('''
                        UPDATE employees
                        SET preferred_language = ?
                        WHERE id = ?
                    ''', (language, session.get('employee_id')))
                    current_app.logger.info(f"Language preference saved to database: {language} for employee {session.get('employee_id')}")
            except Exception as e:
                current_app.logger.error(f"Failed to save language preference to database: {str(e)}")
                # Continue without database save - session is still set

        current_app.logger.info(f"Language manually set to {language} for session")

        return jsonify({'success': True, 'message': f'Language set to {language}'})

    except Exception as e:
        current_app.logger.error(f"Language setting error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


