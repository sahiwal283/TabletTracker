"""
API routes - all /api/* endpoints
"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session, make_response, current_app
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from werkzeug.utils import secure_filename
import json
import traceback
import csv
import io
import os
import re
import requests
import sqlite3
from config import Config
from __version__ import __version__, __title__, __description__
from flask_babel import gettext, ngettext, get_locale
from app.services.zoho_service import zoho_api
from app.services.tracking_service import refresh_shipment_row
from app.services.report_service import ProductionReportGenerator
from app.utils.db_utils import get_db, db_read_only, db_transaction
from app.utils.auth_utils import admin_required, role_required, employee_required
from app.utils.route_helpers import get_setting, ensure_app_settings_table, ensure_submission_type_column
from app.utils.receive_tracking import find_bag_for_submission

bp = Blueprint('api', __name__)


# Route moved to api_submissions.py

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



@bp.route('/api/po_tracking/<int:po_id>')
def get_po_tracking(po_id):
    """Get all tracking information for a PO (supports multiple shipments)"""
    try:
        with db_read_only() as conn:
            # Get all shipments for this PO
            shipments = conn.execute('''
                SELECT id, tracking_number, carrier, shipped_date, estimated_delivery, actual_delivery, notes, created_at
                FROM shipments 
                WHERE po_id = ?
                ORDER BY created_at DESC
            ''', (po_id,)).fetchall()
            
            if shipments:
                # Return all shipments
                shipments_list = []
                for shipment in shipments:
                    shipments_list.append({
                        'id': shipment['id'],
                        'tracking_number': shipment['tracking_number'],
                        'carrier': shipment['carrier'],
                        'shipped_date': shipment['shipped_date'],
                        'estimated_delivery': shipment['estimated_delivery'],
                        'actual_delivery': shipment['actual_delivery'],
                        'notes': shipment['notes']
                    })
                
                return jsonify({
                    'shipments': shipments_list,
                    'has_tracking': True
                })
            else:
                return jsonify({
                    'shipments': [],
                    'has_tracking': False
                })
    except Exception as e:
        return jsonify({'error': str(e)}), 500



@bp.route('/api/find_org_id')
def find_organization_id():
    """Help find the correct Zoho Organization ID"""
    try:
        # Get token first
        token = zoho_api.get_access_token()
        if not token:
            return jsonify({
                'success': False,
                'error': 'Failed to get access token. Check your credentials.'
            })
        
        # Try to get organizations
        url = 'https://www.zohoapis.com/inventory/v1/organizations'
        headers = {'Authorization': f'Zoho-oauthtoken {token}'}
        
        response = requests.get(url, headers=headers)
        current_app.logger.debug(f"Organizations API - Status: {response.status_code}")
        current_app.logger.debug(f"Organizations API - Response: {response.text}")
        
        if response.status_code == 200:
            data = response.json()
            orgs = data.get('organizations', [])
            return jsonify({
                'success': True,
                'organizations': orgs,
                'message': f'Found {len(orgs)} organizations. Use the organization_id from the one you want.'
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Failed to get organizations: {response.status_code} - {response.text}'
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error finding organizations: {str(e)}'
        })



@bp.route('/api/test_zoho_connection')
@admin_required
def test_zoho_connection():
    """Test if Zoho API credentials are working - admin only"""
    try:
        # Try to get an access token
        token = zoho_api.get_access_token()
        if not token:
            return jsonify({
                'success': False,
                'error': 'Failed to get access token. Check your CLIENT_ID, CLIENT_SECRET, and REFRESH_TOKEN in .env file'
            })
        
        # Try to make a simple API call
        result = zoho_api.make_request('items', method='GET', extra_params={'per_page': 10})
        if result:
            item_count = len(result.get('items', []))
            return jsonify({
                'success': True,
                'message': f'✅ Connected to Zoho! Found {item_count} inventory items.',
                'organization_id': zoho_api.organization_id
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Got access token but API call failed. Check your ORGANIZATION_ID or check the terminal for detailed error info.'
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Connection test failed: {str(e)}'
        })



@bp.route('/api/clear_po_data', methods=['POST'])
@admin_required
def clear_po_data():
    """Clear all PO data for fresh sync testing"""
    try:
        with db_transaction() as conn:
            # Clear all PO-related data
            conn.execute('DELETE FROM po_lines')
            conn.execute('DELETE FROM purchase_orders WHERE zoho_po_id IS NOT NULL')  # Keep sample test POs
            conn.execute('DELETE FROM warehouse_submissions')
            
            return jsonify({
                'success': True,
                'message': '✅ Cleared all synced PO data. Ready for fresh sync!'
            })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Clear failed: {str(e)}'
        }), 500

# ===== PRODUCTION REPORT ENDPOINTS =====



# Temporarily removed force-reload route due to import issues

@bp.route('/debug/server-info')
@admin_required
def server_debug_info():
    """Debug route to check server state - admin only"""
    import os
    import time
    import sqlite3
    
    try:
        # Check file timestamps
        app_py_time = os.path.getmtime('app.py')
        version_time = os.path.getmtime('__version__.py')
        
        # Check if we can read version
        try:
            from __version__ import __version__, __title__
            version_info = f"{__title__} v{__version__}"
        except:
            version_info = "Version import failed"
        
        # Check current working directory
        cwd = os.getcwd()
        
        # Check if template exists (using absolute path)
        template_path = os.path.join(current_app.root_path, '..', 'templates', 'receiving_management.html')
        template_path = os.path.abspath(template_path)
        template_exists = os.path.exists(template_path)
        
        # Find database path and check what tables exist (use Config.DATABASE_PATH)
        db_path = Config.DATABASE_PATH
        db_full_path = os.path.abspath(db_path)
        db_exists = os.path.exists(db_path)
        
        # Check what tables actually exist in this database
        tables_info = "Database not accessible"
        if db_exists:
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cursor.fetchall()]
                tables_info = f"Tables: {tables}"
                conn.close()
            except Exception as e:
                tables_info = f"Database error: {e}"
        
        return f"""
        <h2>Server Debug Info</h2>
        <p><strong>Version:</strong> {version_info}</p>
        <p><strong>Working Directory:</strong> {cwd}</p>
        <p><strong>App.py Modified:</strong> {time.ctime(app_py_time)}</p>
        <p><strong>Version.py Modified:</strong> {time.ctime(version_time)}</p>
        <p><strong>Receiving Template Exists:</strong> {template_exists}</p>
        <p><strong>Python Path:</strong> {os.sys.path[0]}</p>
        <hr>
        <p><strong>Database Path:</strong> {db_full_path}</p>
        <p><strong>Database Exists:</strong> {db_exists}</p>
        <p><strong>{tables_info}</strong></p>
        <hr>
        <p><a href="/receiving">Test Receiving Route</a></p>
        <p><a href="/receiving/debug">Test Debug Route</a></p>
        """
        
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        return f"<h2>Server Debug Error</h2><p>{str(e)}</p>"

@bp.route('/api/update_submission_date', methods=['POST'])
@role_required('dashboard')
def update_submission_date():
    """Update the submission date for an existing submission"""
    try:
        data = request.get_json()
        submission_id = data.get('submission_id')
        submission_date = data.get('submission_date')
        
        if not submission_id or not submission_date:
            return jsonify({'error': 'Missing submission_id or submission_date'}), 400
        
        with db_transaction() as conn:
            # Update the submission date
            conn.execute('''
                UPDATE warehouse_submissions 
                SET submission_date = ?
                WHERE id = ?
            ''', (submission_date, submission_id))
            
            return jsonify({
                'success': True,
                'message': f'Submission date updated to {submission_date}'
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500



@bp.route('/api/submission/<int:submission_id>/available_pos', methods=['GET'])
@role_required('dashboard')
def get_available_pos_for_submission(submission_id):
    """Get list of POs that can accept this submission (filtered by product/inventory_item_id)"""
    try:
        with db_read_only() as conn:
            # Get submission details
            submission = conn.execute('''
                SELECT ws.*, pd.packages_per_display, pd.tablets_per_package, tt.inventory_item_id
                FROM warehouse_submissions ws
                LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                WHERE ws.id = ?
            ''', (submission_id,)).fetchone()
            
            if not submission:
                return jsonify({'error': 'Submission not found'}), 404
            
            inventory_item_id = submission['inventory_item_id']
            if not inventory_item_id:
                return jsonify({'error': 'Could not determine product inventory_item_id'}), 400
            
            # Get all POs (open and closed) that have this inventory_item_id
            # Exclude Draft POs, order newest first (DESC) for less scrolling
            pos = conn.execute('''
                SELECT DISTINCT po.id, po.po_number, po.closed, po.internal_status,
                       po.ordered_quantity, po.current_good_count, po.current_damaged_count
                FROM purchase_orders po
                INNER JOIN po_lines pl ON po.id = pl.po_id
                WHERE pl.inventory_item_id = ?
                AND COALESCE(po.internal_status, '') != 'Draft'
                ORDER BY po.po_number DESC
            ''', (inventory_item_id,)).fetchall()
            
            pos_list = []
            for po in pos:
                pos_list.append({
                    'id': po['id'],
                    'po_number': po['po_number'],
                    'closed': bool(po['closed']),
                    'status': 'Cancelled' if po['internal_status'] == 'Cancelled' else ('Closed' if po['closed'] else (po['internal_status'] or 'Active')),
                    'ordered': po['ordered_quantity'] or 0,
                    'good': po['current_good_count'] or 0,
                    'damaged': po['current_damaged_count'] or 0,
                    'remaining': (po['ordered_quantity'] or 0) - (po['current_good_count'] or 0) - (po['current_damaged_count'] or 0)
                })
            
            return jsonify({
                'success': True,
                'available_pos': pos_list,
                'submission_product': submission['product_name'],
                'current_po_id': submission['assigned_po_id']
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500



@bp.route('/api/submission/<int:submission_id>/approve', methods=['POST'])
@role_required('dashboard')
def approve_submission_assignment(submission_id):
    """Approve and lock the current PO assignment for a submission"""
    try:
        with db_transaction() as conn:
            # Check if submission exists and isn't already verified
            submission = conn.execute('''
                SELECT id, assigned_po_id, po_assignment_verified
                FROM warehouse_submissions
                WHERE id = ?
            ''', (submission_id,)).fetchone()
            
            if not submission:
                return jsonify({'error': 'Submission not found'}), 404
            
            if submission['po_assignment_verified']:
                return jsonify({'error': 'Submission already verified and locked'}), 400
            
            if not submission['assigned_po_id']:
                return jsonify({'error': 'Cannot approve unassigned submission'}), 400
            
            # Mark as verified/locked
            conn.execute('''
                UPDATE warehouse_submissions 
                SET po_assignment_verified = TRUE
                WHERE id = ?
            ''', (submission_id,))
            
            return jsonify({
                'success': True,
                'message': 'PO assignment approved and locked'
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500



@bp.route('/api/submission/<int:submission_id>/reassign', methods=['POST'])
@role_required('dashboard')
def reassign_submission_to_po(submission_id):
    """Reassign a submission to a different PO (manager verification/correction)"""
    try:
        data = request.get_json()
        new_po_id = data.get('new_po_id')
        
        if not new_po_id:
            return jsonify({'error': 'Missing new_po_id'}), 400
        
        with db_transaction() as conn:
            # Get submission details
            submission = conn.execute('''
                SELECT ws.*, pd.packages_per_display, pd.tablets_per_package, tt.inventory_item_id,
                       COALESCE(ws.submission_type, 'packaged') as submission_type
                FROM warehouse_submissions ws
                LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                WHERE ws.id = ?
            ''', (submission_id,)).fetchone()
            
            if not submission:
                return jsonify({'error': 'Submission not found'}), 404
            
            # Check if already verified/locked
            if submission['po_assignment_verified']:
                return jsonify({'error': 'Cannot reassign: PO assignment is already verified and locked'}), 403
            
            old_po_id = submission['assigned_po_id']
            inventory_item_id = submission['inventory_item_id']
            
            # Verify new PO has this product
            new_po_check = conn.execute('''
                SELECT COUNT(*) as count
                FROM po_lines pl
                WHERE pl.po_id = ? AND pl.inventory_item_id = ?
            ''', (new_po_id, inventory_item_id)).fetchone()
            
            if new_po_check['count'] == 0:
                return jsonify({'error': 'Selected PO does not have this product'}), 400
            
            # Calculate counts based on submission type
            submission_type = submission.get('submission_type', 'packaged')
            if submission_type == 'machine':
                good_tablets = submission.get('tablets_pressed_into_cards', 0) or 0
            else:
                packages_per_display = submission['packages_per_display'] or 0
                tablets_per_package = submission['tablets_per_package'] or 0
                good_tablets = (submission['displays_made'] * packages_per_display * tablets_per_package + 
                               submission['packs_remaining'] * tablets_per_package + 
                               submission['loose_tablets'])
            damaged_tablets = submission['damaged_tablets']
            
            # Remove counts from old PO if assigned
            if old_po_id:
                # Remove from old PO line
                old_line = conn.execute('''
                    SELECT id FROM po_lines 
                    WHERE po_id = ? AND inventory_item_id = ?
                    LIMIT 1
                ''', (old_po_id, inventory_item_id)).fetchone()
                
                if old_line:
                    # Get current counts first to calculate new values
                    current_line = conn.execute('''
                        SELECT good_count, damaged_count FROM po_lines WHERE id = ?
                    ''', (old_line['id'],)).fetchone()
                    
                    new_good = max(0, (current_line['good_count'] or 0) - good_tablets)
                    new_damaged = max(0, (current_line['damaged_count'] or 0) - damaged_tablets)
                    
                    conn.execute('''
                        UPDATE po_lines 
                        SET good_count = ?, 
                            damaged_count = ?
                        WHERE id = ?
                    ''', (new_good, new_damaged, old_line['id']))
                    
                    # Update old PO header
                    old_totals = conn.execute('''
                        SELECT 
                            COALESCE(SUM(quantity_ordered), 0) as total_ordered,
                            COALESCE(SUM(good_count), 0) as total_good,
                            COALESCE(SUM(damaged_count), 0) as total_damaged
                        FROM po_lines 
                        WHERE po_id = ?
                    ''', (old_po_id,)).fetchone()
                    
                    remaining = old_totals['total_ordered'] - old_totals['total_good'] - old_totals['total_damaged']
                    conn.execute('''
                        UPDATE purchase_orders 
                        SET ordered_quantity = ?, current_good_count = ?, 
                            current_damaged_count = ?, remaining_quantity = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    ''', (old_totals['total_ordered'], old_totals['total_good'], 
                          old_totals['total_damaged'], remaining, old_po_id))
            
            # Add counts to new PO line
            new_line = conn.execute('''
                SELECT id FROM po_lines 
                WHERE po_id = ? AND inventory_item_id = ?
                LIMIT 1
            ''', (new_po_id, inventory_item_id)).fetchone()
            
            if new_line:
                conn.execute('''
                    UPDATE po_lines 
                    SET good_count = good_count + ?, damaged_count = damaged_count + ?
                    WHERE id = ?
                ''', (good_tablets, damaged_tablets, new_line['id']))
                
                # Update new PO header
                new_totals = conn.execute('''
                    SELECT 
                        COALESCE(SUM(quantity_ordered), 0) as total_ordered,
                        COALESCE(SUM(good_count), 0) as total_good,
                        COALESCE(SUM(damaged_count), 0) as total_damaged
                    FROM po_lines 
                    WHERE po_id = ?
                ''', (new_po_id,)).fetchone()
                
                remaining = new_totals['total_ordered'] - new_totals['total_good'] - new_totals['total_damaged']
                conn.execute('''
                    UPDATE purchase_orders 
                    SET ordered_quantity = ?, current_good_count = ?, 
                        current_damaged_count = ?, remaining_quantity = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (new_totals['total_ordered'], new_totals['total_good'], 
                      new_totals['total_damaged'], remaining, new_po_id))
            
            # Update submission assignment and mark as verified (locked)
            conn.execute('''
                UPDATE warehouse_submissions 
                SET assigned_po_id = ?, po_assignment_verified = TRUE
                WHERE id = ?
            ''', (new_po_id, submission_id))
            
            # Get new PO number for response
            new_po = conn.execute('SELECT po_number FROM purchase_orders WHERE id = ?', (new_po_id,)).fetchone()
            
            return jsonify({
                'success': True,
                'message': f'Submission reassigned to PO-{new_po["po_number"]} and locked',
                'new_po_number': new_po['po_number']
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500



@bp.route('/api/reassign_all_submissions', methods=['POST'])
@admin_required
def reassign_all_submissions():
    """Reassign ALL submissions to POs using correct PO order (by PO number, not created_at)"""
    try:
        with db_transaction() as conn:
            # Step 1: Clear all PO assignments and counts (soft reassign - reset verification)
            current_app.logger.info("Clearing all PO assignments and counts...")
            conn.execute('UPDATE warehouse_submissions SET assigned_po_id = NULL, po_assignment_verified = FALSE')
            conn.execute('UPDATE po_lines SET good_count = 0, damaged_count = 0')
            conn.execute('UPDATE purchase_orders SET current_good_count = 0, current_damaged_count = 0, remaining_quantity = ordered_quantity')
        
            # Step 2: Get all submissions in order with their creation timestamp
            all_submissions_rows = conn.execute('''
                SELECT ws.id, ws.product_name, ws.displays_made, 
                       ws.packs_remaining, ws.loose_tablets, ws.damaged_tablets, ws.tablets_pressed_into_cards,
                       COALESCE(ws.submission_type, 'packaged') as submission_type, ws.created_at
                FROM warehouse_submissions ws
                ORDER BY ws.created_at ASC
            ''').fetchall()
            
            all_submissions = [dict(row) for row in all_submissions_rows]
            
            if not all_submissions:
                return jsonify({'success': True, 'message': 'No submissions found'})
            
            matched_count = 0
            updated_pos = set()
            
            # Track running totals for each PO line during reassignment
            # This helps us know when to move to the next PO (when current one has enough)
            po_line_running_totals = {}  # {line_id: {'good': count, 'damaged': count}}
            
            # Step 3: Reassign each submission using correct PO order
            for submission in all_submissions:
                try:
                    # Get product details
                    product_row = conn.execute('''
                    SELECT tt.inventory_item_id, pd.packages_per_display, pd.tablets_per_package
                    FROM product_details pd
                    JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                    WHERE pd.product_name = ?
                ''', (submission['product_name'],)).fetchone()
                    
                    if not product_row:
                        # Try direct tablet_type match
                        product_row = conn.execute('''
                        SELECT inventory_item_id, 0 as packages_per_display, 0 as tablets_per_package
                        FROM tablet_types
                        WHERE tablet_type_name = ?
                    ''', (submission['product_name'],)).fetchone()
                
                    if not product_row:
                        continue
                    
                    product = dict(product_row)
                    inventory_item_id = product.get('inventory_item_id')
                    
                    if not inventory_item_id:
                        continue
                    
                    # Find OPEN PO lines only - ORDER BY PO NUMBER
                    # Automatic bulk reassignment assigns to open POs only
                    # Managers can still manually reassign to closed POs via "Change" button
                    # Exclude Draft POs - only assign to Active/Issued open POs
                    # Note: We do NOT filter by available quantity - POs can receive more than ordered
                    po_lines_rows = conn.execute('''
                        SELECT pl.*, po.closed, po.po_number
                        FROM po_lines pl
                        JOIN purchase_orders po ON pl.po_id = po.id
                        WHERE pl.inventory_item_id = ?
                        AND COALESCE(po.internal_status, '') != 'Draft'
                        AND po.closed = FALSE
                        AND COALESCE(po.internal_status, '') != 'Cancelled'
                        ORDER BY po.po_number ASC
                    ''', (inventory_item_id,)).fetchall()
                    
                    po_lines = [dict(row) for row in po_lines_rows]
                    
                    if not po_lines:
                        continue
                    
                    # Calculate good and damaged counts based on submission type
                    submission_type = submission.get('submission_type', 'packaged')
                    if submission_type == 'machine':
                        good_tablets = submission.get('tablets_pressed_into_cards', 0) or 0
                    else:
                        packages_per_display = product.get('packages_per_display') or 0
                        tablets_per_package = product.get('tablets_per_package') or 0
                        good_tablets = (submission.get('displays_made', 0) * packages_per_display * tablets_per_package + 
                                      submission.get('packs_remaining', 0) * tablets_per_package + 
                                      submission.get('loose_tablets', 0))
                    damaged_tablets = submission.get('damaged_tablets', 0)
                    
                    # Find the first PO that hasn't reached its ordered quantity yet
                    # This allows sequential filling: complete PO-127, then PO-131, then PO-135, etc.
                    # But final counts can still exceed ordered quantities (no artificial cap)
                    assigned_po_id = None
                    for line in po_lines:
                        # Initialize running total if first time seeing this line
                        if line['id'] not in po_line_running_totals:
                            po_line_running_totals[line['id']] = {'good': 0, 'damaged': 0, 'quantity_ordered': line['quantity_ordered']}
                        
                        # Check if this PO line still needs more tablets
                        current_total = po_line_running_totals[line['id']]['good'] + po_line_running_totals[line['id']]['damaged']
                        if current_total < line['quantity_ordered']:
                            # This PO still has room, assign to it
                            assigned_po_id = line['po_id']
                            break
                    
                    # If all POs are at or above their ordered quantities, assign to the last (newest) PO
                    if assigned_po_id is None and po_lines:
                        assigned_po_id = po_lines[-1]['po_id']
                    conn.execute('''
                        UPDATE warehouse_submissions 
                        SET assigned_po_id = ?
                        WHERE id = ?
                    ''', (assigned_po_id, submission['id']))
                    
                    # IMPORTANT: Only allocate counts to lines from the ASSIGNED PO
                    # This ensures older POs are completely filled before newer ones receive submissions
                    assigned_po_lines = [line for line in po_lines if line['po_id'] == assigned_po_id]
                    
                    # Allocate counts to PO lines from the assigned PO only
                    # Note: We do NOT cap at ordered quantity - actual production may exceed the PO
                    remaining_good = good_tablets
                    remaining_damaged = damaged_tablets
                    
                    for line in assigned_po_lines:
                        if remaining_good <= 0 and remaining_damaged <= 0:
                            break
                        
                        # Apply all remaining good count to this line
                        if remaining_good > 0:
                            conn.execute('''
                                UPDATE po_lines 
                                SET good_count = good_count + ?
                                WHERE id = ?
                            ''', (remaining_good, line['id']))
                            # Update running total
                            if line['id'] in po_line_running_totals:
                                po_line_running_totals[line['id']]['good'] += remaining_good
                            remaining_good = 0
                        
                        # Apply all remaining damaged count to this line
                        if remaining_damaged > 0:
                            conn.execute('''
                                UPDATE po_lines 
                                SET damaged_count = damaged_count + ?
                                WHERE id = ?
                            ''', (remaining_damaged, line['id']))
                            # Update running total
                            if line['id'] in po_line_running_totals:
                                po_line_running_totals[line['id']]['damaged'] += remaining_damaged
                            remaining_damaged = 0
                        
                        updated_pos.add(line['po_id'])
                        break  # All counts applied to first line
                    
                    matched_count += 1
                except Exception as e:
                    current_app.logger.error(f"Error processing submission {submission.get('id')}: {e}")
                    continue
            
            # Step 4: Update PO header totals
            for po_id in updated_pos:
                totals_row = conn.execute('''
                    SELECT 
                        COALESCE(SUM(quantity_ordered), 0) as total_ordered,
                        COALESCE(SUM(good_count), 0) as total_good,
                        COALESCE(SUM(damaged_count), 0) as total_damaged
                    FROM po_lines 
                    WHERE po_id = ?
                ''', (po_id,)).fetchone()
                
                totals = dict(totals_row)
                remaining = totals.get('total_ordered', 0) - totals.get('total_good', 0) - totals.get('total_damaged', 0)
                
                conn.execute('''
                    UPDATE purchase_orders 
                    SET ordered_quantity = ?, current_good_count = ?, 
                        current_damaged_count = ?, remaining_quantity = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (totals.get('total_ordered', 0), totals.get('total_good', 0), 
                      totals.get('total_damaged', 0), remaining, po_id))
            
            return jsonify({
                'success': True, 
                'message': f'✅ Reassigned all {matched_count} submissions to POs using correct order (by PO number)',
                'matched': matched_count,
                'total_submissions': len(all_submissions)
            })
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        current_app.logger.error(f"REASSIGN ERROR: {str(e)}")
        current_app.logger.error(error_trace)
        return jsonify({'error': str(e), 'trace': error_trace}), 500



@bp.route('/api/recalculate_po_counts', methods=['POST'])
@admin_required
def recalculate_po_counts():
    """
    Recalculate PO line counts based on currently assigned submissions.
    Does NOT change any PO assignments - just fixes the counts to match actual submissions.
    """
    try:
        with db_transaction() as conn:
            current_app.logger.info("🔄 Recalculating PO counts without changing assignments...")
            
            # Step 1: Reset all PO line counts to zero
            conn.execute('UPDATE po_lines SET good_count = 0, damaged_count = 0')
        
            # Step 2: Get all submissions with inventory_item_id (now stored directly!)
            # Use COALESCE to fallback to JOIN for old submissions without inventory_item_id
            submissions_query = '''
                SELECT 
                    ws.id as submission_id,
                    ws.assigned_po_id,
                    ws.product_name,
                    ws.displays_made,
                    ws.packs_remaining,
                    ws.loose_tablets,
                    ws.damaged_tablets,
                    ws.tablets_pressed_into_cards,
                    COALESCE(ws.submission_type, 'packaged') as submission_type,
                    ws.created_at,
                    pd.packages_per_display,
                    pd.tablets_per_package,
                    COALESCE(ws.inventory_item_id, tt.inventory_item_id) as inventory_item_id
                FROM warehouse_submissions ws
                LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                WHERE ws.assigned_po_id IS NOT NULL
                ORDER BY ws.created_at ASC
            '''
            submissions = conn.execute(submissions_query).fetchall()
            
            # Group submissions by PO and inventory_item_id
            po_line_totals = {}  # {(po_id, inventory_item_id): {'good': X, 'damaged': Y}}
            skipped_submissions = []
            
            for sub in submissions:
                po_id = sub['assigned_po_id']
                inventory_item_id = sub['inventory_item_id']
                
                if not inventory_item_id:
                    submission_type = sub.get('submission_type', 'packaged')
                    if submission_type == 'machine':
                        good_tablets = sub.get('tablets_pressed_into_cards', 0) or 0
                    else:
                        packages_per_display = sub['packages_per_display'] or 0
                        tablets_per_package = sub['tablets_per_package'] or 0
                        good_tablets = (
                            (sub['displays_made'] or 0) * packages_per_display * tablets_per_package +
                            (sub['packs_remaining'] or 0) * tablets_per_package +
                            (sub['loose_tablets'] or 0)
                        )
                    skipped_submissions.append({
                        'submission_id': sub['submission_id'],
                        'product_name': sub['product_name'],
                        'good_tablets': good_tablets,
                        'damaged_tablets': sub['damaged_tablets'] or 0,
                        'created_at': sub['created_at'],
                        'po_id': sub['assigned_po_id']
                    })
                    current_app.logger.warning(f"⚠️ Skipped submission ID {sub['submission_id']}: {sub['product_name']} - {good_tablets} tablets (no inventory_item_id)")
                    continue
                
                # Calculate good and damaged counts based on submission type
                submission_type = sub.get('submission_type', 'packaged')
                if submission_type == 'machine':
                    good_tablets = sub.get('tablets_pressed_into_cards', 0) or 0
                else:
                    packages_per_display = sub['packages_per_display'] or 0
                    tablets_per_package = sub['tablets_per_package'] or 0
                    good_tablets = (
                        (sub['displays_made'] or 0) * packages_per_display * tablets_per_package +
                        (sub['packs_remaining'] or 0) * tablets_per_package +
                        (sub['loose_tablets'] or 0)
                    )
                damaged_tablets = sub['damaged_tablets'] or 0
                
                # Add to running total for this PO line
                key = (po_id, inventory_item_id)
                if key not in po_line_totals:
                    po_line_totals[key] = {'good': 0, 'damaged': 0}
                
                po_line_totals[key]['good'] += good_tablets
                po_line_totals[key]['damaged'] += damaged_tablets
            
            # Step 3: Update each PO line with the calculated totals
            updated_count = 0
            for (po_id, inventory_item_id), totals in po_line_totals.items():
                # Find the PO line for this PO and inventory item
                line = conn.execute('''
                    SELECT id FROM po_lines
                    WHERE po_id = ? AND inventory_item_id = ?
                    LIMIT 1
                ''', (po_id, inventory_item_id)).fetchone()
                
                if line:
                    conn.execute('''
                        UPDATE po_lines
                        SET good_count = ?, damaged_count = ?
                        WHERE id = ?
                    ''', (totals['good'], totals['damaged'], line['id']))
                    updated_count += 1
                    current_app.logger.debug(f"✅ Updated PO line {line['id']}: {totals['good']} good, {totals['damaged']} damaged")
            
            # Step 4: Update PO header totals from line totals
            conn.execute('''
                UPDATE purchase_orders
                SET 
                    ordered_quantity = (
                        SELECT COALESCE(SUM(quantity_ordered), 0)
                        FROM po_lines
                        WHERE po_lines.po_id = purchase_orders.id
                    ),
                    current_good_count = (
                        SELECT COALESCE(SUM(good_count), 0)
                        FROM po_lines
                        WHERE po_lines.po_id = purchase_orders.id
                    ),
                    current_damaged_count = (
                        SELECT COALESCE(SUM(damaged_count), 0)
                        FROM po_lines
                        WHERE po_lines.po_id = purchase_orders.id
                    ),
                    remaining_quantity = (
                        SELECT COALESCE(SUM(quantity_ordered), 0) - COALESCE(SUM(good_count), 0) - COALESCE(SUM(damaged_count), 0)
                        FROM po_lines
                        WHERE po_lines.po_id = purchase_orders.id
                    ),
                    updated_at = CURRENT_TIMESTAMP
            ''')
            
            # Build response message
            message = f'Successfully recalculated counts for {updated_count} PO lines. No assignments were changed.'
            skipped_by_product = {}
            
            if skipped_submissions:
                # Group skipped by product
                for skip in skipped_submissions:
                    product = skip['product_name']
                    if product not in skipped_by_product:
                        skipped_by_product[product] = {'good': 0, 'damaged': 0}
                    skipped_by_product[product]['good'] += skip['good_tablets']
                    skipped_by_product[product]['damaged'] += skip['damaged_tablets']
                
                message += f'\n\n⚠️ WARNING: {len(skipped_submissions)} submissions were skipped (missing product configuration):\n'
                for product, totals in skipped_by_product.items():
                    message += f'\n• {product}: {totals["good"]} tablets (damaged: {totals["damaged"]})'
                message += '\n\nTo fix: Go to "Manage Products" and ensure each product is linked to a tablet type with an inventory_item_id.'
            
            return jsonify({
                'success': True,
                'message': message,
                'skipped_count': len(skipped_submissions),
                'skipped_details': skipped_by_product
            })
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        current_app.logger.error(f"RECALCULATE ERROR: {str(e)}")
        current_app.logger.error(error_trace)
        return jsonify({'error': str(e), 'trace': error_trace}), 500



@bp.route('/api/submission/<int:submission_id>/details', methods=['GET'])
@role_required('dashboard')
def get_submission_details(submission_id):
    """Get full details of a submission (viewable by all authenticated users)"""
    try:
        with db_read_only() as conn:
            submission = conn.execute('''
            SELECT ws.*, po.po_number, po.closed as po_closed, po.zoho_po_id,
                   COALESCE(ws.po_assignment_verified, 0) as po_verified,
                   pd.packages_per_display, pd.tablets_per_package,
                   COALESCE(pd.tablets_per_package, pd_fallback.tablets_per_package) as tablets_per_package_final,
                   COALESCE(b.bag_label_count, ws.bag_label_count, 0) as bag_label_count, 
                   r.id as receive_id, r.received_date,
                   m.machine_name, m.cards_per_turn as machine_cards_per_turn,
                   (
                       SELECT COUNT(*) + 1
                       FROM receiving r2
                       WHERE r2.po_id = r.po_id
                       AND (r2.received_date < r.received_date 
                            OR (r2.received_date = r.received_date AND r2.id < r.id))
                   ) as shipment_number
            FROM warehouse_submissions ws
            LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            LEFT JOIN tablet_types tt_fallback ON ws.inventory_item_id = tt_fallback.inventory_item_id
            LEFT JOIN product_details pd_fallback ON tt_fallback.id = pd_fallback.tablet_type_id
            LEFT JOIN bags b ON ws.bag_id = b.id
            LEFT JOIN small_boxes sb ON b.small_box_id = sb.id
            LEFT JOIN receiving r ON sb.receiving_id = r.id
            LEFT JOIN machines m ON ws.machine_id = m.id
                WHERE ws.id = ?
            ''', (submission_id,)).fetchone()
            
            if not submission:
                return jsonify({'success': False, 'error': 'Submission not found'}), 404
            
            submission_dict = dict(submission)
            db_submission_type = submission_dict.get('submission_type')
            submission_type = db_submission_type or 'packaged'
            
            current_app.logger.info(f"GET SUBMISSION DETAILS: id={submission_id}, product_name='{submission_dict.get('product_name')}', db_submission_type='{db_submission_type}'")
            
            # If submission_type is already 'bottle' in the database, use it
            if db_submission_type == 'bottle':
                submission_type = 'bottle'
                current_app.logger.info(f"Submission {submission_id} already has submission_type='bottle' in database")
            
            # Always check product config to determine if this is a bottle/variety pack submission
            # This handles both new submissions and legacy ones where submission_type might not be set
            product_name = submission_dict.get('product_name')
            if product_name:
                product_config = conn.execute('''
                    SELECT is_variety_pack, is_bottle_product, variety_pack_contents, tablets_per_bottle 
                    FROM product_details WHERE product_name = ?
                ''', (product_name,)).fetchone()
                
                if product_config:
                    product_config_dict = dict(product_config)
                    # Check flags OR if it has variety_pack_contents (fallback for legacy data)
                    is_variety = product_config_dict.get('is_variety_pack')
                    is_bottle = product_config_dict.get('is_bottle_product')
                    has_variety_contents = product_config_dict.get('variety_pack_contents')
                    has_bottle_config = product_config_dict.get('tablets_per_bottle')
                    
                    current_app.logger.info(f"Product config for '{product_name}': is_variety={is_variety}, is_bottle={is_bottle}, has_contents={bool(has_variety_contents)}, has_bottle_config={bool(has_bottle_config)}")
                    
                    if is_variety or is_bottle or has_variety_contents or has_bottle_config:
                        submission_type = 'bottle'
                        submission_dict['submission_type'] = 'bottle'
                        current_app.logger.info(f"Detected bottle/variety pack submission {submission_id} for product '{product_name}'")
                else:
                    current_app.logger.warning(f"No product_config found for product_name='{product_name}' in submission {submission_id}")
            else:
                current_app.logger.warning(f"Submission {submission_id} has no product_name, cannot check product config")
            
            # If bag_label_count is 0 or missing but bag_id exists, try to get it directly from bags table
            if submission_dict.get('bag_id') and (not submission_dict.get('bag_label_count') or submission_dict.get('bag_label_count') == 0):
                bag_row = conn.execute('SELECT bag_label_count FROM bags WHERE id = ?', (submission_dict.get('bag_id'),)).fetchone()
                if bag_row:
                    bag_dict = dict(bag_row)
                    if bag_dict.get('bag_label_count'):
                        submission_dict['bag_label_count'] = bag_dict.get('bag_label_count')
            
            # Get machine information for machine submissions
            # First try to get from the JOIN we already did
            machine_name = submission_dict.get('machine_name')
            cards_per_turn = submission_dict.get('machine_cards_per_turn')
            
            if submission_type == 'machine':
                # If not found from JOIN, try to get from machine_id in submission
                machine_row = None
                if not cards_per_turn and submission_dict.get('machine_id'):
                    machine_row = conn.execute('''
                        SELECT machine_name, cards_per_turn
                        FROM machines
                        WHERE id = ?
                    ''', (submission_dict.get('machine_id'),)).fetchone()
                if machine_row:
                    machine = dict(machine_row)
                    if not machine_name:
                        machine_name = machine.get('machine_name')
                    if not cards_per_turn:
                        cards_per_turn = machine.get('cards_per_turn')
            
            # If still not found, try to find from machine_counts table by matching submission details
            if not cards_per_turn:
                tablet_type_row = conn.execute('''
                    SELECT id FROM tablet_types WHERE inventory_item_id = ?
                ''', (submission_dict.get('inventory_item_id'),)).fetchone()
                
                if tablet_type_row:
                    tablet_type = dict(tablet_type_row)
                    tablet_type_id = tablet_type.get('id')
                    
                    # Try to find machine_count record that matches this submission
                    submission_date = submission_dict.get('submission_date') or submission_dict.get('created_at')
                    machine_count_record_row = conn.execute('''
                        SELECT mc.machine_id, m.machine_name, m.cards_per_turn
                        FROM machine_counts mc
                        LEFT JOIN machines m ON mc.machine_id = m.id
                        WHERE mc.tablet_type_id = ?
                        AND mc.machine_count = ?
                        AND mc.employee_name = ?
                        AND DATE(mc.count_date) = DATE(?)
                        ORDER BY mc.created_at DESC
                        LIMIT 1
                    ''', (tablet_type_id, 
                          submission_dict.get('displays_made'),
                          submission_dict.get('employee_name'),
                          submission_date)).fetchone()
                    
                    if machine_count_record_row:
                        machine_count_record = dict(machine_count_record_row)
                        if not machine_name:
                            machine_name = machine_count_record.get('machine_name')
                        if not cards_per_turn:
                            cards_per_turn = machine_count_record.get('cards_per_turn')
            
            # Fallback to app_settings if machine not found
            if not cards_per_turn:
                cards_per_turn_setting_row = conn.execute(
                    'SELECT setting_value FROM app_settings WHERE setting_key = ?',
                    ('cards_per_turn',)
                ).fetchone()
                if cards_per_turn_setting_row:
                    cards_per_turn_setting = dict(cards_per_turn_setting_row)
                    cards_per_turn = int(cards_per_turn_setting.get('setting_value', 1))
                else:
                    cards_per_turn = 1
            
            # Recalculate cards_made using correct machine-specific cards_per_turn
            # This fixes submissions that were saved with wrong cards_per_turn
            machine_count = submission_dict.get('displays_made', 0) or 0  # displays_made stores machine_count (turns)
            cards_made = machine_count * cards_per_turn
            submission_dict['cards_made'] = cards_made  # Add recalculated cards_made
            
            # For machine submissions: total tablets pressed into cards is stored in tablets_pressed_into_cards
            # Fallback to loose_tablets, then calculate from cards_made × tablets_per_package
            packs_remaining = submission_dict.get('packs_remaining', 0) or 0
            # Use tablets_per_package_final (with fallback) if available, otherwise try tablets_per_package
            tablets_per_package = (submission_dict.get('tablets_per_package_final') or 
                                 submission_dict.get('tablets_per_package') or 0)
            
            # If tablets_per_package is still 0 or None, try to get it directly from database using inventory_item_id
            if not tablets_per_package or tablets_per_package == 0:
                inventory_item_id = submission_dict.get('inventory_item_id')
                if inventory_item_id:
                    # Try to get tablets_per_package via inventory_item_id -> tablet_types -> product_details
                    tpp_row = conn.execute('''
                        SELECT pd.tablets_per_package
                        FROM tablet_types tt
                        JOIN product_details pd ON tt.id = pd.tablet_type_id
                        WHERE tt.inventory_item_id = ?
                        LIMIT 1
                    ''', (inventory_item_id,)).fetchone()
                    if tpp_row:
                        tpp_dict = dict(tpp_row)
                        tablets_per_package = tpp_dict.get('tablets_per_package', 0) or 0
                
                submission_dict['individual_calc'] = (submission_dict.get('tablets_pressed_into_cards') or
                                                     submission_dict.get('loose_tablets') or
                                                     (packs_remaining * tablets_per_package) or
                                                     0)
                submission_dict['total_tablets'] = submission_dict['individual_calc']
                submission_dict['cards_per_turn'] = cards_per_turn
                submission_dict['machine_name'] = machine_name
                # Use recalculated cards_made instead of packs_remaining (which may have wrong value)
                submission_dict['packs_remaining'] = cards_made
            else:
                # For packaged/bag submissions: calculate from displays and packs
                packages_per_display = submission_dict.get('packages_per_display', 0) or 0
                tablets_per_package = submission_dict.get('tablets_per_package', 0) or 0
                displays_made = submission_dict.get('displays_made', 0) or 0
                packs_remaining = submission_dict.get('packs_remaining', 0) or 0
                loose_tablets = submission_dict.get('loose_tablets', 0) or 0
                damaged_tablets = submission_dict.get('damaged_tablets', 0) or 0
                
                calculated_total = (
                    (displays_made * packages_per_display * tablets_per_package) +
                    (packs_remaining * tablets_per_package) +
                    loose_tablets + damaged_tablets
                )
                submission_dict['individual_calc'] = calculated_total
                submission_dict['total_tablets'] = calculated_total
            
            # Build receive name if we have the necessary information
            receive_name = None
            if submission_dict.get('receive_id') and submission_dict.get('po_number') and submission_dict.get('shipment_number'):
                receive_name = f"{submission_dict.get('po_number')}-{submission_dict.get('shipment_number')}-{submission_dict.get('box_number', '')}-{submission_dict.get('bag_number', '')}"
            submission_dict['receive_name'] = receive_name
            
            # Calculate bag running totals for this submission
            # Get all submissions to the same bag up to and including this submission (chronological order)
            if submission_dict.get('assigned_po_id') and submission_dict.get('product_name') and submission_dict.get('box_number') is not None and submission_dict.get('bag_number') is not None:
                bag_identifier = f"{submission_dict.get('box_number')}/{submission_dict.get('bag_number')}"
                bag_key = (submission_dict.get('assigned_po_id'), submission_dict.get('product_name'), bag_identifier)
                
                # Get all submissions to this bag up to and including this one, in chronological order
                bag_submissions = conn.execute('''
                    SELECT ws.*, pd.packages_per_display, pd.tablets_per_package,
                           COALESCE(pd.tablets_per_package, pd_fallback.tablets_per_package) as tablets_per_package_final
                    FROM warehouse_submissions ws
                    LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                    LEFT JOIN tablet_types tt_fallback ON ws.inventory_item_id = tt_fallback.inventory_item_id
                    LEFT JOIN product_details pd_fallback ON tt_fallback.id = pd_fallback.tablet_type_id
                    WHERE ws.assigned_po_id = ?
                    AND ws.product_name = ?
                    AND ws.box_number = ?
                    AND ws.bag_number = ?
                    AND ws.created_at <= ?
                    ORDER BY ws.created_at ASC
                ''', (submission_dict.get('assigned_po_id'),
                      submission_dict.get('product_name'),
                      submission_dict.get('box_number'),
                      submission_dict.get('bag_number'),
                      submission_dict.get('created_at'))).fetchall()
                
                # Calculate running totals
                bag_running_total = 0
                machine_running_total = 0
                packaged_running_total = 0
                total_running_total = 0
                
                for bag_sub in bag_submissions:
                    bag_sub_dict = dict(bag_sub)
                    bag_sub_type = bag_sub_dict.get('submission_type', 'packaged')
                    
                    # Calculate individual total for this submission
                    if bag_sub_type == 'machine':
                        # Use tablets_pressed_into_cards, fallback to loose_tablets, then calculate from cards_made
                        # Use tablets_per_package_final (with fallback) if available, otherwise try tablets_per_package
                        bag_tablets_per_package = (bag_sub_dict.get('tablets_per_package_final') or 
                                                 bag_sub_dict.get('tablets_per_package') or 0)
                        individual_total = (bag_sub_dict.get('tablets_pressed_into_cards') or
                                           bag_sub_dict.get('loose_tablets') or
                                           ((bag_sub_dict.get('packs_remaining', 0) or 0) * bag_tablets_per_package) or
                                           0)
                        machine_running_total += individual_total
                        # Machine counts are NOT added to total - they're consumed in production
                    elif bag_sub_type == 'bag':
                        # For bag count submissions, use loose_tablets (the actual count from form)
                        individual_total = bag_sub_dict.get('loose_tablets', 0) or 0
                        bag_running_total += individual_total
                        # Bag counts are NOT added to total - they're just inventory counts
                    else:  # 'packaged'
                        packages_per_display = bag_sub_dict.get('packages_per_display', 0) or 0
                        tablets_per_package = bag_sub_dict.get('tablets_per_package', 0) or 0
                        displays_made = bag_sub_dict.get('displays_made', 0) or 0
                        packs_remaining = bag_sub_dict.get('packs_remaining', 0) or 0
                        loose_tablets = bag_sub_dict.get('loose_tablets', 0) or 0
                        damaged_tablets = bag_sub_dict.get('damaged_tablets', 0) or 0
                        individual_total = (
                            (displays_made * packages_per_display * tablets_per_package) +
                            (packs_remaining * tablets_per_package) +
                            loose_tablets + damaged_tablets
                        )
                        packaged_running_total += individual_total
                        # Only packaged counts are added to total - these are tablets actually in the bag
                        total_running_total += individual_total
                
                submission_dict['bag_running_total'] = bag_running_total
                submission_dict['machine_running_total'] = machine_running_total
                submission_dict['packaged_running_total'] = packaged_running_total
                # Total should only include packaged counts (tablets actually in the bag)
                # Machine counts are consumed, bag counts are just inventory
                submission_dict['running_total'] = packaged_running_total
                
                # Calculate count status and tablet difference
                # Use packaged_running_total for comparison - machine counts are consumed, not in bag
                bag_label_count = submission_dict.get('bag_label_count', 0) or 0
                if not submission_dict.get('bag_id'):
                    submission_dict['count_status'] = 'no_bag'
                    submission_dict['tablet_difference'] = None
                elif abs(packaged_running_total - bag_label_count) <= 5:  # Allow 5 tablet tolerance
                    submission_dict['count_status'] = 'match'
                    submission_dict['tablet_difference'] = abs(packaged_running_total - bag_label_count)
                elif packaged_running_total < bag_label_count:
                    submission_dict['count_status'] = 'under'
                    submission_dict['tablet_difference'] = bag_label_count - packaged_running_total
                else:
                    submission_dict['count_status'] = 'over'
                    submission_dict['tablet_difference'] = packaged_running_total - bag_label_count
            else:
                submission_dict['bag_running_total'] = 0
                submission_dict['machine_running_total'] = 0
                submission_dict['packaged_running_total'] = 0
                submission_dict['running_total'] = 0
                submission_dict['count_status'] = 'no_bag'
                submission_dict['tablet_difference'] = None
            
            # For bottle submissions, get bag deductions from junction table
            bag_deductions = []
            if submission_type == 'bottle':
                deductions = conn.execute('''
                    SELECT sbd.id, sbd.bag_id, sbd.tablets_deducted, sbd.created_at,
                           b.bag_number, b.bag_label_count,
                           sb.box_number,
                           tt.tablet_type_name,
                           r.receive_name, po.po_number
                    FROM submission_bag_deductions sbd
                    JOIN bags b ON sbd.bag_id = b.id
                    LEFT JOIN small_boxes sb ON b.small_box_id = sb.id
                    LEFT JOIN receiving r ON sb.receiving_id = r.id
                    LEFT JOIN purchase_orders po ON r.po_id = po.id
                    LEFT JOIN tablet_types tt ON b.tablet_type_id = tt.id
                    WHERE sbd.submission_id = ?
                    ORDER BY tt.tablet_type_name, sbd.created_at
                ''', (submission_id,)).fetchall()
                
                bag_deductions = [dict(d) for d in deductions]
                
                # Calculate total tablets from bag deductions (for variety packs)
                total_from_deductions = sum(d.get('tablets_deducted', 0) for d in bag_deductions)
                if total_from_deductions > 0:
                    submission_dict['individual_calc'] = total_from_deductions
                    submission_dict['total_tablets'] = total_from_deductions
                elif submission_dict.get('bottles_made'):
                    # For bottle-only products without junction table entries
                    bottles_made = submission_dict.get('bottles_made', 0) or 0
                    # Get tablets_per_bottle from product_details
                    product_row = conn.execute('''
                        SELECT tablets_per_bottle FROM product_details WHERE product_name = ?
                    ''', (submission_dict.get('product_name'),)).fetchone()
                    if product_row:
                        tablets_per_bottle = dict(product_row).get('tablets_per_bottle', 0) or 0
                        submission_dict['individual_calc'] = bottles_made * tablets_per_bottle
                        submission_dict['total_tablets'] = bottles_made * tablets_per_bottle
            
            return jsonify({
                'success': True,
                'submission': submission_dict,
                'bag_deductions': bag_deductions
            })
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        current_app.logger.error(f"GET SUBMISSION ERROR: {str(e)}")
        current_app.logger.error(error_trace)
        return jsonify({'error': str(e)}), 500



@bp.route('/api/submission/<int:submission_id>/edit', methods=['POST'])
@admin_required
def edit_submission(submission_id):
    """Edit a submission and recalculate PO counts (Admin and Manager only)"""
    # Allow managers to edit submissions (especially admin notes)
    if not (session.get('admin_authenticated') or 
            (session.get('employee_authenticated') and session.get('employee_role') in ['admin', 'manager'])):
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    try:
        data = request.get_json()
        with db_transaction() as conn:
            # Get the submission's current PO assignment
            submission = conn.execute('''
                SELECT assigned_po_id, product_name, displays_made, packs_remaining, 
                       loose_tablets, damaged_tablets, tablets_pressed_into_cards, inventory_item_id,
                       COALESCE(submission_type, 'packaged') as submission_type
                FROM warehouse_submissions
                WHERE id = ?
            ''', (submission_id,)).fetchone()
            
            if not submission:
                return jsonify({'success': False, 'error': 'Submission not found'}), 404
            
            # Convert Row to dict for safe access
            submission = dict(submission)
            
            old_po_id = submission['assigned_po_id']
            inventory_item_id = submission['inventory_item_id']
            
            # Check if product_name is being changed
            new_product_name = data.get('product_name')
            product_name_to_use = new_product_name if new_product_name else submission['product_name']
            
            # If product is being changed, update inventory_item_id
            if new_product_name and new_product_name != submission['product_name']:
                # Get the new inventory_item_id for the new product
                # Try product_name first (from product_details)
                new_product_info = conn.execute('''
                    SELECT tt.inventory_item_id, pd.product_name
                    FROM tablet_types tt
                    JOIN product_details pd ON tt.id = pd.tablet_type_id
                    WHERE pd.product_name = ?
                    LIMIT 1
                ''', (new_product_name,)).fetchone()
                
                # If not found by product_name, try tablet_type_name
                if not new_product_info:
                    new_product_info = conn.execute('''
                        SELECT tt.inventory_item_id, pd.product_name
                        FROM tablet_types tt
                        LEFT JOIN product_details pd ON tt.id = pd.tablet_type_id
                        WHERE tt.tablet_type_name = ?
                        LIMIT 1
                    ''', (new_product_name,)).fetchone()
                
                if new_product_info:
                    inventory_item_id = new_product_info['inventory_item_id']
                    # Use the actual product_name from product_details if available
                    if new_product_info.get('product_name'):
                        new_product_name = new_product_info['product_name']
            
            # Get product details for calculations
            # Make this more resilient - try multiple approaches
            product = conn.execute('''
                SELECT pd.packages_per_display, pd.tablets_per_package
                FROM product_details pd
                JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                WHERE pd.product_name = ?
            ''', (product_name_to_use,)).fetchone()
            
            if not product:
                # Fallback: try to get product details without the JOIN
                product = conn.execute('''
                    SELECT packages_per_display, tablets_per_package
                    FROM product_details
                    WHERE product_name = ?
                ''', (product_name_to_use,)).fetchone()
            
            if not product:
                # Last resort: get from existing submission or use defaults
                existing_config = conn.execute('''
                    SELECT pd.packages_per_display, pd.tablets_per_package
                    FROM warehouse_submissions ws
                    LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                    WHERE ws.id = ?
                ''', (submission_id,)).fetchone()
                
                if existing_config and (existing_config.get('packages_per_display') or existing_config.get('tablets_per_package')):
                    product = existing_config
                else:
                    # Use defaults to allow edit (admin can fix product config later)
                    current_app.logger.warning(f"Product configuration not found for {product_name_to_use}, using defaults")
                    product = {'packages_per_display': 1, 'tablets_per_package': 1}
            
            # Convert Row to dict for safe access
            if not isinstance(product, dict):
                product = dict(product)
            
            # Validate product configuration values
            packages_per_display = product.get('packages_per_display')
            tablets_per_package = product.get('tablets_per_package')
            
            if packages_per_display is None or tablets_per_package is None or packages_per_display == 0 or tablets_per_package == 0:
                return jsonify({'success': False, 'error': 'Product configuration incomplete: packages_per_display and tablets_per_package are required and must be greater than 0'}), 400
            
            # Convert to int after validation
            try:
                packages_per_display = int(packages_per_display)
                tablets_per_package = int(tablets_per_package)
            except (ValueError, TypeError):
                return jsonify({'success': False, 'error': 'Invalid numeric values for product configuration'}), 400
            
            # Calculate old totals to subtract based on submission type
            submission_type = submission.get('submission_type', 'packaged')
            if submission_type == 'machine':
                old_good = submission.get('tablets_pressed_into_cards', 0) or 0
            else:
                old_good = (submission['displays_made'] * packages_per_display * tablets_per_package +
                           submission['packs_remaining'] * tablets_per_package +
                           submission['loose_tablets'])
            old_damaged = submission['damaged_tablets']
            
            # Validate and convert input data
            try:
                displays_made = int(data.get('displays_made', 0) or 0)
                packs_remaining = int(data.get('packs_remaining', 0) or 0)
                loose_tablets = int(data.get('loose_tablets', 0) or 0)
                damaged_tablets = int(data.get('damaged_tablets', 0) or 0)
                tablets_pressed_into_cards = int(data.get('tablets_pressed_into_cards', 0) or 0) if submission_type == 'machine' else 0
            except (ValueError, TypeError):
                return jsonify({'success': False, 'error': 'Invalid numeric values for counts'}), 400
            
            # Calculate new totals based on submission type
            if submission_type == 'machine':
                new_good = tablets_pressed_into_cards
            else:
                new_good = (displays_made * packages_per_display * tablets_per_package +
                           packs_remaining * tablets_per_package +
                           loose_tablets)
            new_damaged = damaged_tablets
            
            # Get receipt_number from form data
            receipt_number = (data.get('receipt_number') or '').strip() or None
            
            # Find the correct bag_id if box_number and bag_number are provided
            new_box_number = data.get('box_number')
            new_bag_number = data.get('bag_number')
            new_bag_id = None
            
            if new_box_number is not None and new_bag_number is not None and old_po_id:
                # Try to find the bag that matches the new box_number and bag_number for this PO
                bag_row = conn.execute('''
                    SELECT b.id
                    FROM bags b
                    JOIN small_boxes sb ON b.small_box_id = sb.id
                    JOIN receiving r ON sb.receiving_id = r.id
                    WHERE r.po_id = ?
                    AND sb.box_number = ?
                    AND b.bag_number = ?
                    LIMIT 1
                ''', (old_po_id, new_box_number, new_bag_number)).fetchone()
                
                if bag_row:
                    new_bag_id = dict(bag_row).get('id')
                # If no bag found, set bag_id to NULL (submission will be unassigned)
            
            # Update the submission
            submission_date = data.get('submission_date', datetime.now().date().isoformat())
            if submission_type == 'machine':
                conn.execute('''
                    UPDATE warehouse_submissions
                    SET displays_made = ?, packs_remaining = ?, tablets_pressed_into_cards = ?, 
                        damaged_tablets = ?, box_number = ?, bag_number = ?, bag_id = ?, bag_label_count = ?,
                        submission_date = ?, admin_notes = ?, receipt_number = ?, product_name = ?, inventory_item_id = ?
                    WHERE id = ?
                ''', (displays_made, packs_remaining, tablets_pressed_into_cards,
                      damaged_tablets, new_box_number, new_bag_number, new_bag_id,
                      data.get('bag_label_count'), submission_date, data.get('admin_notes'), receipt_number, 
                      product_name_to_use, inventory_item_id, submission_id))
            else:
                conn.execute('''
                    UPDATE warehouse_submissions
                    SET displays_made = ?, packs_remaining = ?, loose_tablets = ?, 
                            damaged_tablets = ?, box_number = ?, bag_number = ?, bag_id = ?, bag_label_count = ?,
                            submission_date = ?, admin_notes = ?, receipt_number = ?, product_name = ?, inventory_item_id = ?
                    WHERE id = ?
                ''', (displays_made, packs_remaining, loose_tablets,
                          damaged_tablets, new_box_number, new_bag_number, new_bag_id,
                          data.get('bag_label_count'), submission_date, data.get('admin_notes'), receipt_number,
                          product_name_to_use, inventory_item_id, submission_id))
            
            # Update PO line counts if assigned to a PO
            if old_po_id and inventory_item_id:
                # Find the PO line
                po_line = conn.execute('''
                    SELECT id FROM po_lines
                    WHERE po_id = ? AND inventory_item_id = ?
                    LIMIT 1
                ''', (old_po_id, inventory_item_id)).fetchone()
                
                if po_line:
                    # Convert Row to dict for safe access
                    po_line = dict(po_line)
                    
                    # Calculate the difference and update
                    good_diff = new_good - old_good
                    damaged_diff = new_damaged - old_damaged
                    
                    conn.execute('''
                        UPDATE po_lines
                        SET good_count = good_count + ?, damaged_count = damaged_count + ?
                        WHERE id = ?
                    ''', (good_diff, damaged_diff, po_line['id']))
                    
                    # Update PO header totals
                    totals = conn.execute('''
                        SELECT 
                            COALESCE(SUM(quantity_ordered), 0) as total_ordered,
                            COALESCE(SUM(good_count), 0) as total_good,
                            COALESCE(SUM(damaged_count), 0) as total_damaged
                        FROM po_lines 
                        WHERE po_id = ?
                    ''', (old_po_id,)).fetchone()
                    
                    # Convert Row to dict for safe access
                    totals = dict(totals)
                    
                    remaining = totals['total_ordered'] - totals['total_good'] - totals['total_damaged']
                    conn.execute('''
                        UPDATE purchase_orders 
                        SET ordered_quantity = ?, current_good_count = ?, 
                            current_damaged_count = ?, remaining_quantity = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    ''', (totals['total_ordered'], totals['total_good'], 
                          totals['total_damaged'], remaining, old_po_id))
            
            return jsonify({
                'success': True,
                'message': 'Submission updated successfully'
            })
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        current_app.logger.error(f"EDIT SUBMISSION ERROR: {str(e)}")
        current_app.logger.error(error_trace)
        return jsonify({'error': str(e)}), 500



@bp.route('/api/submission/<int:submission_id>/delete', methods=['POST'])
@admin_required
def delete_submission(submission_id):
    """Delete a submission and remove its counts from PO (Admin only)"""
    try:
        with db_transaction() as conn:
            # Get the submission details
            submission = conn.execute('''
                SELECT assigned_po_id, product_name, displays_made, packs_remaining, 
                       loose_tablets, damaged_tablets, tablets_pressed_into_cards, inventory_item_id,
                       bottles_made,
                       COALESCE(submission_type, 'packaged') as submission_type
                FROM warehouse_submissions
                WHERE id = ?
            ''', (submission_id,)).fetchone()
            
            if not submission:
                return jsonify({'success': False, 'error': 'Submission not found'}), 404
            
            # Convert Row to dict for safe access
            submission = dict(submission)
            
            old_po_id = submission['assigned_po_id']
            inventory_item_id = submission['inventory_item_id']
            
            # Get product details for calculations
            product = conn.execute('''
                SELECT pd.packages_per_display, pd.tablets_per_package,
                       pd.tablets_per_bottle, pd.bottles_per_display,
                       pd.is_bottle_product, pd.is_variety_pack
                FROM product_details pd
                LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                WHERE pd.product_name = ?
            ''', (submission['product_name'],)).fetchone()
            
            # Calculate counts to remove based on submission type
            submission_type = submission.get('submission_type', 'packaged')
            
            if submission_type == 'bottle':
                # For bottle submissions, delete junction table entries first
                conn.execute('''
                    DELETE FROM submission_bag_deductions WHERE submission_id = ?
                ''', (submission_id,))
                
                # Calculate tablets for bottle submissions
                if product:
                    product = dict(product)
                    tablets_per_bottle = product.get('tablets_per_bottle') or 0
                    bottles_made = submission.get('bottles_made', 0) or 0
                    good_tablets = bottles_made * tablets_per_bottle
                else:
                    # If no product config, just use 0 (can't calculate)
                    good_tablets = 0
            elif submission_type == 'machine':
                good_tablets = submission.get('tablets_pressed_into_cards', 0) or 0
            else:
                # Packaged submissions require product config
                if not product:
                    return jsonify({'success': False, 'error': 'Product configuration not found'}), 400
                product = dict(product)
                good_tablets = (submission['displays_made'] * (product.get('packages_per_display') or 0) * (product.get('tablets_per_package') or 0) +
                               submission['packs_remaining'] * (product.get('tablets_per_package') or 0) +
                               submission['loose_tablets'])
            
            damaged_tablets = submission.get('damaged_tablets', 0) or 0
            
            # Remove counts from PO line if assigned
            if old_po_id and inventory_item_id:
                # Find the PO line
                po_line = conn.execute('''
                    SELECT id FROM po_lines
                    WHERE po_id = ? AND inventory_item_id = ?
                    LIMIT 1
                ''', (old_po_id, inventory_item_id)).fetchone()
                
                if po_line:
                    # Get current counts first to calculate new values
                    current_line = conn.execute('''
                        SELECT good_count, damaged_count FROM po_lines WHERE id = ?
                    ''', (po_line['id'],)).fetchone()
                    
                    new_good = max(0, (current_line['good_count'] or 0) - good_tablets)
                    new_damaged = max(0, (current_line['damaged_count'] or 0) - damaged_tablets)
                    
                    # Remove counts from PO line
                    conn.execute('''
                        UPDATE po_lines
                        SET good_count = ?, 
                            damaged_count = ?
                        WHERE id = ?
                    ''', (new_good, new_damaged, po_line['id']))
                    
                    # Update PO header totals
                    totals = conn.execute('''
                        SELECT 
                            COALESCE(SUM(quantity_ordered), 0) as total_ordered,
                            COALESCE(SUM(good_count), 0) as total_good,
                            COALESCE(SUM(damaged_count), 0) as total_damaged
                        FROM po_lines 
                        WHERE po_id = ?
                    ''', (old_po_id,)).fetchone()
                    
                    remaining = totals['total_ordered'] - totals['total_good'] - totals['total_damaged']
                    conn.execute('''
                        UPDATE purchase_orders 
                        SET ordered_quantity = ?, current_good_count = ?, 
                            current_damaged_count = ?, remaining_quantity = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    ''', (totals['total_ordered'], totals['total_good'], 
                          totals['total_damaged'], remaining, old_po_id))
            
            # Delete the submission
            conn.execute('DELETE FROM warehouse_submissions WHERE id = ?', (submission_id,))
            
            return jsonify({
                'success': True,
                'message': 'Submission deleted successfully'
            })
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        current_app.logger.error(f"DELETE SUBMISSION ERROR: {str(e)}")
        current_app.logger.error(error_trace)
        return jsonify({'success': False, 'error': str(e)}), 500



@bp.route('/api/po/<int:po_id>/delete', methods=['POST'])
@admin_required
def delete_po(po_id):
    """Delete a PO and all its related data (Admin only)"""
    try:
        with db_transaction() as conn:
            # Get PO details first
            po = conn.execute('SELECT po_number FROM purchase_orders WHERE id = ?', (po_id,)).fetchone()
            
            if not po:
                return jsonify({'success': False, 'error': 'PO not found'}), 404
            
            # Delete related data
            # 1. Unassign all submissions (don't delete submissions, just unassign them)
            conn.execute('UPDATE warehouse_submissions SET assigned_po_id = NULL WHERE assigned_po_id = ?', (po_id,))
            
            # 2. Delete shipments
            conn.execute('DELETE FROM shipments WHERE po_id = ?', (po_id,))
            
            # 3. Delete PO lines
            conn.execute('DELETE FROM po_lines WHERE po_id = ?', (po_id,))
            
            # 4. Delete the PO itself
            conn.execute('DELETE FROM purchase_orders WHERE id = ?', (po_id,))
            
            return jsonify({
                'success': True,
                'message': f'Successfully deleted {po["po_number"]} and all related data'
            })
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        current_app.logger.error(f"DELETE PO ERROR: {str(e)}")
        current_app.logger.error(error_trace)
        return jsonify({'error': str(e)}), 500



@bp.route('/api/resync_unassigned_submissions', methods=['POST'])
@admin_required
def resync_unassigned_submissions():
    """Resync unassigned submissions to try matching them with POs based on updated item IDs"""
    try:
        with db_transaction() as conn:
            # Get all unassigned submissions - convert to dicts immediately
            # Note: Use 'id' instead of 'rowid' for better compatibility
            unassigned_rows = conn.execute('''
                SELECT ws.id, ws.product_name, ws.displays_made, 
                       ws.packs_remaining, ws.loose_tablets, ws.damaged_tablets, ws.tablets_pressed_into_cards,
                       COALESCE(ws.submission_type, 'packaged') as submission_type
                FROM warehouse_submissions ws
                WHERE ws.assigned_po_id IS NULL
                ORDER BY ws.created_at DESC
            ''').fetchall()
            
            # Convert Row objects to dicts to avoid key access issues
            unassigned = [dict(row) for row in unassigned_rows]
            
            if not unassigned:
                return jsonify({'success': True, 'message': 'No unassigned submissions found'})
        
            matched_count = 0
            updated_pos = set()
            
            for submission in unassigned:
                try:
                    # Get the product's details including inventory_item_id
                    # submission['product_name'] matches product_details.product_name
                    # then join to tablet_types to get inventory_item_id
                    product_row = conn.execute('''
                        SELECT tt.inventory_item_id, pd.packages_per_display, pd.tablets_per_package
                        FROM product_details pd
                        JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                        WHERE pd.product_name = ?
                    ''', (submission['product_name'],)).fetchone()
                    
                    if not product_row:
                        # Try direct tablet_type match if no product_details entry
                        product_row = conn.execute('''
                            SELECT inventory_item_id, 0 as packages_per_display, 0 as tablets_per_package
                            FROM tablet_types
                            WHERE tablet_type_name = ?
                        ''', (submission['product_name'],)).fetchone()
                    
                    if not product_row:
                        current_app.logger.warning(f"⚠️  No product config found for: {submission['product_name']}")
                        continue
                    
                    # Convert to dict for safe access
                    product = dict(product_row)
                    inventory_item_id = product.get('inventory_item_id')
                    
                    if not inventory_item_id:
                        current_app.logger.warning(f"⚠️  No inventory_item_id for: {submission['product_name']}")
                        continue
                except Exception as e:
                    current_app.logger.error(f"❌ Error processing submission {submission.get('id', 'unknown')}: {e}")
                    continue
                
                # Find open PO lines for this inventory item
                # Order by PO number (oldest PO numbers first) since they represent issue order
                # Exclude Draft POs - only assign to Issued/Active POs
                # Note: We do NOT filter by available quantity - POs can receive more than ordered
                po_lines_rows = conn.execute('''
                    SELECT pl.*, po.closed
                    FROM po_lines pl
                    JOIN purchase_orders po ON pl.po_id = po.id
                    WHERE pl.inventory_item_id = ? AND po.closed = FALSE
                    AND COALESCE(po.internal_status, '') != 'Draft'
                    ORDER BY po.po_number ASC
                ''', (inventory_item_id,)).fetchall()
                
                # Convert to dicts
                po_lines = [dict(row) for row in po_lines_rows]
                
                if not po_lines:
                    continue
                
                # Calculate good and damaged counts based on submission type
                submission_type = submission.get('submission_type', 'packaged')
                if submission_type == 'machine':
                    good_tablets = submission.get('tablets_pressed_into_cards', 0) or 0
                else:
                    packages_per_display = product.get('packages_per_display') or 0
                    tablets_per_package = product.get('tablets_per_package') or 0
                    good_tablets = (submission.get('displays_made', 0) * packages_per_display * tablets_per_package + 
                                  submission.get('packs_remaining', 0) * tablets_per_package + 
                                  submission.get('loose_tablets', 0))
                    damaged_tablets = submission.get('damaged_tablets', 0)
                
                # Assign to first available PO
                assigned_po_id = po_lines[0]['po_id']
                conn.execute('''
                    UPDATE warehouse_submissions 
                    SET assigned_po_id = ?
                    WHERE id = ?
                ''', (assigned_po_id, submission['id']))
                
                # Allocate counts to PO lines
                # Note: We do NOT cap at ordered quantity - actual production may exceed the PO
                line = po_lines[0]
                
                # Apply all counts to the first line
                conn.execute('''
                    UPDATE po_lines 
                    SET good_count = good_count + ?, damaged_count = damaged_count + ?
                    WHERE id = ?
                ''', (good_tablets, damaged_tablets, line['id']))
                
                updated_pos.add(line['po_id'])
                
                matched_count += 1
            
            # Update PO header totals for all affected POs
            for po_id in updated_pos:
                totals_row = conn.execute('''
                    SELECT 
                        COALESCE(SUM(quantity_ordered), 0) as total_ordered,
                        COALESCE(SUM(good_count), 0) as total_good,
                        COALESCE(SUM(damaged_count), 0) as total_damaged
                    FROM po_lines 
                    WHERE po_id = ?
                ''', (po_id,)).fetchone()
                
                # Convert to dict
                totals = dict(totals_row)
                remaining = totals.get('total_ordered', 0) - totals.get('total_good', 0) - totals.get('total_damaged', 0)
                
                conn.execute('''
                    UPDATE purchase_orders 
                    SET ordered_quantity = ?, current_good_count = ?, 
                        current_damaged_count = ?, remaining_quantity = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (totals.get('total_ordered', 0), totals.get('total_good', 0), 
                      totals.get('total_damaged', 0), remaining, po_id))
            
            return jsonify({
                'success': True, 
                'message': f'Successfully matched {matched_count} of {len(unassigned)} unassigned submissions to POs',
                'matched': matched_count,
                'total_unassigned': len(unassigned)
            })
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        current_app.logger.error(f"RESYNC ERROR: {str(e)}")
        current_app.logger.error(error_trace)
        return jsonify({'error': str(e), 'trace': error_trace}), 500



@bp.route('/api/po/<int:po_id>/submissions', methods=['GET'])
@role_required('dashboard')
def get_po_submissions(po_id):
    """Get all submissions assigned to a specific PO"""
    try:
        with db_read_only() as conn:
            # Get PO details including machine counts
            po_row = conn.execute('''
                SELECT po_number, tablet_type, ordered_quantity, 
                       current_good_count, current_damaged_count, remaining_quantity,
                       machine_good_count, machine_damaged_count,
                       parent_po_number
                FROM purchase_orders
                WHERE id = ?
            ''', (po_id,)).fetchone()
            
            if not po_row:
                return jsonify({'error': 'PO not found'}), 404
        
            po = dict(po_row)
            
            # Check if submission_date and submission_type columns exist
            has_submission_date = False
            has_submission_type = False
            try:
                conn.execute('SELECT submission_date FROM warehouse_submissions LIMIT 1')
                has_submission_date = True
            except:
                pass
            try:
                conn.execute('SELECT submission_type FROM warehouse_submissions LIMIT 1')
                has_submission_type = True
            except:
                pass
            
            # For PO-specific views, show ALL submissions for auditing purposes
            
            # Determine which PO IDs to query:
            # 1. If this is a parent PO, also include submissions from related OVERS POs
            # 2. If this is an OVERS PO, also include submissions from the parent PO
            po_ids_to_query = [po_id]
            po_number = po.get('po_number')
            
            # Check if this is a parent PO - find related OVERS POs
            overs_pos = conn.execute('''
                SELECT id FROM purchase_orders 
                WHERE parent_po_number = ?
            ''', (po_number,)).fetchall()
            for overs_po_row in overs_pos:
                overs_po = dict(overs_po_row)
                po_ids_to_query.append(overs_po.get('id'))
            
            # Check if this is an OVERS PO - find parent PO
            if po.get('parent_po_number'):
                parent_po_row = conn.execute('''
                    SELECT id FROM purchase_orders 
                    WHERE po_number = ?
                ''', (po.get('parent_po_number'),)).fetchone()
                if parent_po_row:
                    parent_po = dict(parent_po_row)
                    parent_po_id = parent_po.get('id')
                    if parent_po_id and parent_po_id not in po_ids_to_query:
                        po_ids_to_query.append(parent_po_id)
            
            # Build WHERE clause for multiple PO IDs
            po_ids_placeholders = ','.join(['?'] * len(po_ids_to_query))
            
            # Get all submissions for this PO (and related OVERS/parent POs) with product details
            # Include inventory_item_id for matching with PO line items
            # PO is source of truth - only include submissions where assigned_po_id matches
            submission_type_select = ', ws.submission_type' if has_submission_type else ", 'packaged' as submission_type"
            po_verified_select = ', COALESCE(ws.po_assignment_verified, 0) as po_verified' if has_submission_type else ", 0 as po_verified"
            if has_submission_date:
                submissions_query = f'''
                    SELECT DISTINCT
                        ws.id,
                        ws.product_name,
                        ws.employee_name,
                        ws.displays_made,
                        ws.packs_remaining,
                        ws.loose_tablets,
                        ws.damaged_tablets,
                        ws.created_at,
                        ws.submission_date,
                        ws.box_number,
                        ws.bag_number,
                        ws.bag_id,
                        COALESCE(b.bag_label_count, ws.bag_label_count, 0) as bag_label_count,
                        ws.admin_notes,
                        pd.packages_per_display,
                        COALESCE(pd.tablets_per_package, pd_fallback.tablets_per_package) as tablets_per_package,
                        tt.inventory_item_id,
                        ws.assigned_po_id,
                        po.po_number,
                        po.closed as po_closed
                        {submission_type_select}
                        {po_verified_select}
                    FROM warehouse_submissions ws
                    LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                    LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                    LEFT JOIN tablet_types tt_fallback ON ws.inventory_item_id = tt_fallback.inventory_item_id
                    LEFT JOIN product_details pd_fallback ON tt_fallback.id = pd_fallback.tablet_type_id
                    LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
                    LEFT JOIN bags b ON ws.bag_id = b.id
                    WHERE ws.assigned_po_id IN ({po_ids_placeholders})
                    ORDER BY ws.created_at ASC
                '''
            else:
                submissions_query = f'''
                    SELECT DISTINCT
                        ws.id,
                        ws.product_name,
                        ws.employee_name,
                        ws.displays_made,
                        ws.packs_remaining,
                        ws.loose_tablets,
                        ws.damaged_tablets,
                        ws.created_at,
                        ws.created_at as submission_date,
                        ws.box_number,
                        ws.bag_number,
                        ws.bag_id,
                        COALESCE(b.bag_label_count, ws.bag_label_count, 0) as bag_label_count,
                        ws.admin_notes,
                        pd.packages_per_display,
                        COALESCE(pd.tablets_per_package, pd_fallback.tablets_per_package) as tablets_per_package,
                        tt.inventory_item_id,
                        ws.assigned_po_id,
                        po.po_number,
                        po.closed as po_closed
                        {submission_type_select}
                        {po_verified_select}
                    FROM warehouse_submissions ws
                    LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                    LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                    LEFT JOIN tablet_types tt_fallback ON ws.inventory_item_id = tt_fallback.inventory_item_id
                    LEFT JOIN product_details pd_fallback ON tt_fallback.id = pd_fallback.tablet_type_id
                    LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
                    LEFT JOIN bags b ON ws.bag_id = b.id
                    WHERE ws.assigned_po_id IN ({po_ids_placeholders})
                    ORDER BY ws.created_at ASC
                '''
            
            # Execute query with PO IDs
            submissions_raw = conn.execute(submissions_query, tuple(po_ids_to_query)).fetchall()
            current_app.logger.debug(f"🔍 get_po_submissions: Found {len(submissions_raw)} submissions for PO {po_id} ({po_number}) including related POs: {po_ids_to_query}")
            
            # Calculate total tablets and running bag totals for each submission
            # Also calculate separate totals for machine vs packaged+bag counts
            bag_running_totals = {}
            submissions = []
            machine_total = 0
            packaged_total = 0
            bag_total = 0
            
            for sub in submissions_raw:
                sub_dict = dict(sub)
                submission_type = sub_dict.get('submission_type', 'packaged')
                
                # Calculate total tablets for this submission
                if submission_type == 'machine':
                    # For machine submissions: use tablets_pressed_into_cards (fallback to loose_tablets, then calculate from cards_made)
                    total_tablets = (sub_dict.get('tablets_pressed_into_cards') or 
                                   sub_dict.get('loose_tablets') or
                                   ((sub_dict.get('packs_remaining', 0) or 0) * (sub_dict.get('tablets_per_package', 0) or 0)) or
                                   0)
                else:
                    # For other submissions: calculate from displays, packs, loose, and damaged
                    displays_tablets = (sub_dict.get('displays_made', 0) or 0) * (sub_dict.get('packages_per_display', 0) or 0) * (sub_dict.get('tablets_per_package', 0) or 0)
                    package_tablets = (sub_dict.get('packs_remaining', 0) or 0) * (sub_dict.get('tablets_per_package', 0) or 0)
                    loose_tablets = sub_dict.get('loose_tablets', 0) or 0
                    damaged_tablets = sub_dict.get('damaged_tablets', 0) or 0
                    total_tablets = displays_tablets + package_tablets + loose_tablets + damaged_tablets
                
                sub_dict['total_tablets'] = total_tablets
                
                # Track totals separately by submission type
                if submission_type == 'machine':
                    machine_total += total_tablets
                elif submission_type == 'packaged':
                    packaged_total += total_tablets
                elif submission_type == 'bag':
                    bag_total += total_tablets
                # Bag counts are separate from packaged counts - they're just inventory counts, not production
                
                # Calculate running total by bag PER PO (only for packaged submissions, NOT bag counts)
                if submission_type == 'packaged':
                    bag_identifier = f"{sub_dict.get('box_number', '')}/{sub_dict.get('bag_number', '')}"
                    # Key includes PO ID so each PO tracks its own bag totals independently
                    bag_key = (po_id, sub_dict.get('product_name', ''), bag_identifier)
                    if bag_key not in bag_running_totals:
                        bag_running_totals[bag_key] = 0
                    bag_running_totals[bag_key] += total_tablets
                    sub_dict['running_total'] = bag_running_totals[bag_key]
                    
                    # Determine count status (only for packaged submissions)
                    # Check if bag_id is NULL, not just bag_label_count
                    # A bag can exist with label_count=0, but if bag_id is NULL, there's no bag assigned
                    if not sub_dict.get('bag_id'):
                        sub_dict['count_status'] = 'no_bag'
                    else:
                        bag_count = sub_dict.get('bag_label_count', 0) or 0
                        if abs(bag_running_totals[bag_key] - bag_count) <= 5:
                            sub_dict['count_status'] = 'match'
                        elif bag_running_totals[bag_key] < bag_count:
                            sub_dict['count_status'] = 'under'
                        else:
                            sub_dict['count_status'] = 'over'
                elif submission_type == 'bag':
                    # Bag counts don't have running totals - they're just inventory counts
                    sub_dict['running_total'] = total_tablets
                    sub_dict['count_status'] = None
                else:
                    # Machine counts don't have bag running totals
                    sub_dict['running_total'] = total_tablets
                    sub_dict['count_status'] = None
                
                submissions.append(sub_dict)
            
            # Reverse to show newest first in modal
            submissions.reverse()
            
            return jsonify({
                'success': True,
                'po': dict(po),
                'submissions': submissions,
                'count': len(submissions),
                'totals': {
                    'machine': machine_total,
                    'packaged': packaged_total,
                    'bag': bag_total,
                    'total': machine_total + packaged_total + bag_total
                }
            })
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        current_app.logger.error(f"Error fetching PO submissions: {str(e)}")
        current_app.logger.error(error_trace)
        return jsonify({'error': str(e)}), 500

# ===== TEMPLATE CONTEXT PROCESSORS =====

@bp.app_template_filter('to_est')
def to_est_filter(dt_string):
    """Convert UTC datetime string to Eastern Time (EST/EDT)"""
    if not dt_string:
        return 'N/A'
    try:
        # Parse the datetime string (assumes UTC)
        if isinstance(dt_string, str):
            # Handle date-only strings (YYYY-MM-DD)
            if re.match(r'^\d{4}-\d{2}-\d{2}$', dt_string):
                return dt_string  # Return date-only as-is
            
            # Handle different datetime formats
            if '.' in dt_string:
                dt = datetime.strptime(dt_string.split('.')[0], '%Y-%m-%d %H:%M:%S')
            else:
                dt = datetime.strptime(dt_string, '%Y-%m-%d %H:%M:%S')
            # Assume UTC if no timezone info in string
            utc_dt = dt.replace(tzinfo=ZoneInfo('UTC'))
        else:
            # Already a datetime object
            dt = dt_string
            if dt.tzinfo is None:
                # Naive datetime - assume UTC (from database)
                utc_dt = dt.replace(tzinfo=ZoneInfo('UTC'))
            else:
                # Already has timezone - convert to UTC first if needed
                utc_dt = dt.astimezone(ZoneInfo('UTC'))
        
        # Convert from UTC to Eastern
        est_dt = utc_dt.astimezone(ZoneInfo('America/New_York'))
        
        # Format as YYYY-MM-DD HH:MM:SS
        return est_dt.strftime('%Y-%m-%d %H:%M:%S')
    except Exception as e:
        current_app.logger.error(f"Error converting datetime to EST: {e}")
        return dt_string if isinstance(dt_string, str) else 'N/A'

@bp.app_template_filter('to_est_time')
def to_est_time_filter(dt_string):
    """Convert UTC datetime string to Eastern Time, showing only time portion"""
    if not dt_string:
        return 'N/A'
    try:
        # Parse the datetime string (assumes UTC)
        if isinstance(dt_string, str):
            # Handle date-only strings (YYYY-MM-DD) - return N/A for time-only display
            if re.match(r'^\d{4}-\d{2}-\d{2}$', dt_string):
                return 'N/A'  # No time component for date-only strings
            
            # Handle different datetime formats
            if '.' in dt_string:
                dt = datetime.strptime(dt_string.split('.')[0], '%Y-%m-%d %H:%M:%S')
            else:
                dt = datetime.strptime(dt_string, '%Y-%m-%d %H:%M:%S')
            # Assume UTC if no timezone info in string
            utc_dt = dt.replace(tzinfo=ZoneInfo('UTC'))
        else:
            # Already a datetime object
            dt = dt_string
            if dt.tzinfo is None:
                # Naive datetime - assume UTC (from database)
                utc_dt = dt.replace(tzinfo=ZoneInfo('UTC'))
            else:
                # Already has timezone - convert to UTC first if needed
                utc_dt = dt.astimezone(ZoneInfo('UTC'))
        
        # Convert from UTC to Eastern
        est_dt = utc_dt.astimezone(ZoneInfo('America/New_York'))
        
        # Format as HH:MM:SS
        return est_dt.strftime('%H:%M:%S')
    except Exception as e:
        current_app.logger.error(f"Error converting datetime to EST: {e}")
        if isinstance(dt_string, str):
            # Fallback: try to extract time portion
            parts = dt_string.split(' ')
            if len(parts) > 1:
                return parts[1].split('.')[0] if '.' in parts[1] else parts[1]
        return 'N/A'

@bp.app_context_processor
def inject_version():
    """Make version information available to all templates"""
    locale = get_locale()
    # Convert Locale object to string if needed
    current_lang = str(locale) if hasattr(locale, 'language') else locale
    return {
        'version': lambda: __version__,
        'app_title': __title__,
        'app_description': __description__,
        'current_language': current_lang,
        'languages': current_app.config['LANGUAGES'],
        'gettext': gettext,
        'ngettext': ngettext
    }

@bp.route('/api/submission/<int:submission_id>', methods=['DELETE'])
@role_required('dashboard')
def delete_submission_alt(submission_id):
    """Delete a submission (for removing duplicates) - DELETE method"""
    try:
        with db_transaction() as conn:
            # Check if submission exists
            submission = conn.execute('''
                SELECT id FROM warehouse_submissions WHERE id = ?
            ''', (submission_id,)).fetchone()
            
            if not submission:
                return jsonify({'success': False, 'error': 'Submission not found'}), 404
            
            # Delete the submission
            conn.execute('DELETE FROM warehouse_submissions WHERE id = ?', (submission_id,))
            
            return jsonify({
                'success': True,
                'message': 'Submission deleted successfully'
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

