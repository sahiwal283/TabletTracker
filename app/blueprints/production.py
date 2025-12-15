"""
Production routes - warehouse submissions, bag counts, machine counts
"""
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from datetime import datetime
import traceback
from app.utils.db_utils import get_db
from app.utils.auth_utils import employee_required
from app.utils.route_helpers import (
    get_setting, ensure_submission_type_column,
    ensure_machine_counts_table, ensure_machine_count_columns
)
from app.utils.receive_tracking import find_bag_for_submission

bp = Blueprint('production', __name__)


@bp.route('/production')
@employee_required
def production_form():
    """Combined production submission and bag count form"""
    conn = None
    try:
        conn = get_db()
        
        # Get product list for dropdown
        products = conn.execute('''
            SELECT pd.product_name, tt.tablet_type_name, pd.packages_per_display, pd.tablets_per_package
            FROM product_details pd
            JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            ORDER BY pd.product_name
        ''').fetchall()
        
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
        print(f"Error in production_form(): {str(e)}")
        raise
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


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
    conn = None
    try:
        data = request.get_json() if request.is_json else request.form
        
        # Validate required fields
        if not data.get('product_name'):
            return jsonify({'error': 'product_name is required'}), 400
        
        # Ensure submission_type column exists
        ensure_submission_type_column()
        
        # Get employee name from session
        conn = get_db()
        
        # Handle admin users (they don't have employee_id in session)
        if session.get('admin_authenticated'):
            employee_name = 'Admin'
        else:
            employee = conn.execute('''
                SELECT full_name FROM employees WHERE id = ?
            ''', (session.get('employee_id'),)).fetchone()
            
            if not employee:
                return jsonify({'error': 'Employee not found'}), 400
            
            employee_name = employee['full_name']
        
        # Get product details
        product = conn.execute('''
            SELECT pd.*, tt.inventory_item_id, tt.tablet_type_name
            FROM product_details pd
            JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            WHERE pd.product_name = ?
        ''', (data.get('product_name'),)).fetchone()
        
        if not product:
            return jsonify({'error': 'Product not found'}), 400
        
        # Convert Row to dict for safe access
        product = dict(product)
        
        # Validate product configuration
        packages_per_display = product.get('packages_per_display')
        tablets_per_package = product.get('tablets_per_package')
        
        if packages_per_display is None or tablets_per_package is None or packages_per_display == 0 or tablets_per_package == 0:
            return jsonify({'error': 'Product configuration incomplete: packages_per_display and tablets_per_package are required and must be greater than 0'}), 400
        
        # Convert to int after validation
        try:
            packages_per_display = int(packages_per_display)
            tablets_per_package = int(tablets_per_package)
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid numeric values for product configuration'}), 400
        
        # Calculate tablet counts with safe type conversion
        try:
            displays_made = int(data.get('displays_made', 0) or 0)
            packs_remaining = int(data.get('packs_remaining', 0) or 0)
            loose_tablets = int(data.get('loose_tablets', 0) or 0)
            damaged_tablets = int(data.get('damaged_tablets', 0) or 0)
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid numeric values for counts'}), 400
        
        good_tablets = (displays_made * packages_per_display * tablets_per_package + 
                       packs_remaining * tablets_per_package + 
                       loose_tablets)
        
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
        
        # Insert submission record using logged-in employee name WITH inventory_item_id
        inventory_item_id = product.get('inventory_item_id')
        if not inventory_item_id:
            return jsonify({'error': 'Product inventory_item_id not found'}), 400
        
        # Get tablet_type_id for receive-based matching
        tablet_type_id = product.get('tablet_type_id')
        if not tablet_type_id:
            return jsonify({'error': 'Product tablet_type_id not found'}), 400
        
        box_number = data.get('box_number')
        bag_number = data.get('bag_number')
        
        # RECEIVE-BASED TRACKING: Try to match to existing receive/bag
        bag = None
        needs_review = False
        error_message = None
        assigned_po_id = None
        bag_id = None
        
        if box_number and bag_number:
            bag, needs_review, error_message = find_bag_for_submission(conn, tablet_type_id, box_number, bag_number)
            
            if bag:
                # Exact match found - auto-assign
                bag_id = bag['id']
                assigned_po_id = bag['po_id']
                bag_label_count = bag.get('bag_label_count', 0)
                print(f"✅ Matched to receive: bag_id={bag_id}, po_id={assigned_po_id}, box={box_number}, bag={bag_number}")
            elif needs_review:
                # Multiple matches - needs manual review
                print(f"⚠️ Multiple receives found for Box {box_number}, Bag {bag_number} - needs review")
            elif error_message:
                # No match found
                print(f"❌ {error_message}")
        
        # Get receipt_number from form data
        receipt_number = data.get('receipt_number', '').strip() or None
        
        # Insert submission with bag_id and po_id if matched
        conn.execute('''
            INSERT INTO warehouse_submissions 
            (employee_name, product_name, inventory_item_id, box_number, bag_number, bag_label_count,
             displays_made, packs_remaining, loose_tablets, damaged_tablets, submission_date, admin_notes, 
             submission_type, bag_id, assigned_po_id, needs_review, receipt_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'packaged', ?, ?, ?, ?)
        ''', (employee_name, data.get('product_name'), inventory_item_id, box_number, bag_number,
              bag.get('bag_label_count', 0) if bag else data.get('bag_label_count'),
              displays_made, packs_remaining, loose_tablets, damaged_tablets, submission_date, admin_notes,
              bag_id, assigned_po_id, needs_review, receipt_number))
        
        conn.commit()
        
        # Return appropriate message based on matching result
        if error_message:
            return jsonify({
                'success': True,
                'warning': error_message,
                'submission_saved': True,
                'needs_review': needs_review,
                'bag_id': bag_id,
                'po_id': assigned_po_id
            })
        elif needs_review:
            return jsonify({
                'success': True,
                'message': 'Submission flagged for manager review - multiple matching receives found.',
                'bag_id': bag_id,
                'po_id': assigned_po_id,
                'needs_review': needs_review
            })
        else:
            return jsonify({
                'success': True,
                'message': 'Packaged count submitted successfully',
                'bag_id': bag_id,
                'po_id': assigned_po_id,
                'needs_review': needs_review
            })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        print(f"Error in submit_warehouse: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


@bp.route('/api/submissions/bag-count', methods=['POST'])
def submit_count():
    """Process manual count submission for PO close-outs - RECEIVE-BASED TRACKING"""
    conn = None
    try:
        data = request.get_json() if request.is_json else request.form
        
        # Ensure submission_type column exists
        ensure_submission_type_column()
        
        # Validate required fields
        if not data.get('tablet_type'):
            return jsonify({'error': 'tablet_type is required'}), 400
        
        conn = get_db()
        
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
        bag, needs_review, error_message = find_bag_for_submission(
            conn, tablet_type_id, data.get('box_number'), data.get('bag_number')
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
        
        conn.commit()
        
        message = 'Count flagged for manager review - multiple matching receives found.' if needs_review else 'Bag count submitted successfully!'
        
        return jsonify({
            'success': True,
            'message': message,
            'bag_id': bag_id,
            'po_id': assigned_po_id,
            'needs_review': needs_review
        })
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


@bp.route('/api/submissions/machine-count', methods=['POST'])
@employee_required
def submit_machine_count():
    """Submit machine count reading and create warehouse submission"""
    conn = None
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
        
        conn = get_db()
        
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
        
        # Get cards_per_turn setting
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
        
        # Get machine_id from form data
        machine_id = data.get('machine_id')
        if machine_id:
            try:
                machine_id = int(machine_id)
            except (ValueError, TypeError):
                machine_id = None
        
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
            conn.commit()
            return jsonify({'warning': 'Tablet type inventory_item_id or id not found. Submission saved but not assigned to PO.', 'submission_saved': True})
        
        # Get box/bag numbers from form data
        box_number = data.get('box_number')
        bag_number = data.get('bag_number')
        
        # Get admin_notes if user is admin or manager
        admin_notes = None
        if session.get('admin_authenticated') or session.get('employee_role') in ['admin', 'manager']:
            admin_notes_raw = data.get('admin_notes', '')
            if admin_notes_raw and isinstance(admin_notes_raw, str):
                admin_notes = admin_notes_raw.strip() or None
            elif admin_notes_raw:
                # Handle non-string values (shouldn't happen, but be safe)
                admin_notes = str(admin_notes_raw).strip() or None
        
        # RECEIVE-BASED TRACKING: Try to match to existing receive/bag
        bag = None
        needs_review = False
        error_message = None
        assigned_po_id = None
        bag_id = None
        
        if box_number and bag_number:
            bag, needs_review, error_message = find_bag_for_submission(conn, tablet_type_id, box_number, bag_number)
            
            if bag:
                # Exact match found - auto-assign
                bag_id = bag['id']
                assigned_po_id = bag['po_id']
                print(f"✅ Matched to receive: bag_id={bag_id}, po_id={assigned_po_id}, box={box_number}, bag={bag_number}")
            elif needs_review:
                # Multiple matches - needs manual review
                print(f"⚠️ Multiple receives found for Box {box_number}, Bag {bag_number} - needs review")
            elif error_message:
                # No match found
                print(f"❌ {error_message}")
        
        # Get receipt_number from form data
        receipt_number = data.get('receipt_number', '').strip() or None
        
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
            conn.commit()
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
            print(f"Machine count - Updated PO line {line['id']}: +{tablets_pressed_into_cards} tablets pressed into cards")
        
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
        
        conn.commit()
        
        return jsonify({
            'success': True, 
            'message': 'Machine count submitted successfully.'
        })
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


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
