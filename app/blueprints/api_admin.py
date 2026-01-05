"""
Admin API routes for admin panel, employee management, and diagnostic tools.
"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session, current_app
from datetime import datetime, timedelta
import traceback
import json
from app.utils.db_utils import db_read_only, db_transaction
from app.utils.auth_utils import admin_required, role_required, hash_password, verify_password
from app.utils.route_helpers import ensure_app_settings_table

bp = Blueprint('api_admin', __name__)


@bp.route('/admin')
def admin_panel():
    """Admin panel with quick actions and product management"""
    if not session.get('admin_authenticated'):
        return render_template('admin_login.html')
    
    try:
        ensure_app_settings_table()
        with db_read_only() as conn:
            cards_per_turn = conn.execute(
                'SELECT setting_value FROM app_settings WHERE setting_key = ?',
                ('cards_per_turn',)
            ).fetchone()
            cards_per_turn_value = int(cards_per_turn['setting_value']) if cards_per_turn else 1
            return render_template('admin_panel.html', cards_per_turn=cards_per_turn_value)
    except Exception as e:
        current_app.logger.error(f"Error in admin_panel: {str(e)}")
        traceback.print_exc()
        return render_template('admin_panel.html', cards_per_turn=1)


@bp.route('/admin/login', methods=['POST'])
def admin_login():
    """Handle admin login with enhanced security"""
    from config import Config
    
    password = request.form.get('password') or request.json.get('password')
    admin_password = Config.ADMIN_PASSWORD
    
    if password == admin_password:
        session['admin_authenticated'] = True
        session['employee_role'] = 'admin'
        session['login_time'] = datetime.now().isoformat()
        session.permanent = True
        current_app.permanent_session_lifetime = timedelta(hours=8)
        
        return redirect('/admin') if request.form else jsonify({'success': True})
    else:
        current_app.logger.warning(f"Failed admin login attempt from {request.remote_addr} at {datetime.now()}")
        
        if request.form:
            flash('Invalid password', 'error')
            return render_template('admin_login.html')
        else:
            return jsonify({'success': False, 'error': 'Invalid password'})


@bp.route('/admin/logout')
def admin_logout():
    """Logout admin - redirect to unified logout"""
    return redirect(url_for('auth.logout'))


@bp.route('/admin/products')
@admin_required
def product_mapping():
    """Show product → tablet mapping and calculation examples"""
    try:
        with db_transaction() as conn:
            products = conn.execute('''
            SELECT pd.*, tt.tablet_type_name, tt.inventory_item_id, tt.category
            FROM product_details pd
            LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            ORDER BY COALESCE(tt.tablet_type_name, ''), pd.product_name
        ''').fetchall()
        
            table_info = conn.execute("PRAGMA table_info(tablet_types)").fetchall()
            has_category_column = any(col[1] == 'category' for col in table_info)
            
            if not has_category_column:
                try:
                    conn.execute('ALTER TABLE tablet_types ADD COLUMN category TEXT')
                    conn.commit()
                    has_category_column = True
                except Exception as e:
                    if conn:
                        try:
                            conn.rollback()
                        except:
                            pass
                    current_app.logger.warning(f"Could not add category column: {e}")
            
            if has_category_column:
                tablet_types = conn.execute('SELECT * FROM tablet_types ORDER BY tablet_type_name').fetchall()
                categories = conn.execute('SELECT DISTINCT category FROM tablet_types WHERE category IS NOT NULL AND category != "" ORDER BY category').fetchall()
                category_list = [cat['category'] for cat in categories] if categories else []
            else:
                tablet_types_raw = conn.execute('SELECT id, tablet_type_name, inventory_item_id FROM tablet_types ORDER BY tablet_type_name').fetchall()
                tablet_types = [dict(row) for row in tablet_types_raw]
                for tt in tablet_types:
                    tt['category'] = None
                category_list = []
            
            deleted_categories_set = set()
            try:
                deleted_categories_json = conn.execute('''
                    SELECT setting_value FROM app_settings WHERE setting_key = 'deleted_categories'
                ''').fetchone()
                if deleted_categories_json and deleted_categories_json['setting_value']:
                    try:
                        deleted_categories_set = set(json.loads(deleted_categories_json['setting_value']))
                    except (json.JSONDecodeError, ValueError, TypeError):
                        deleted_categories_set = set()
            except Exception as e:
                current_app.logger.warning(f"Could not load deleted categories: {e}")
            
            try:
                category_order_json = conn.execute('''
                    SELECT setting_value FROM app_settings WHERE setting_key = 'category_order'
                ''').fetchone()
                if category_order_json and category_order_json['setting_value']:
                    try:
                        preferred_order = json.loads(category_order_json['setting_value'])
                    except (json.JSONDecodeError, ValueError, TypeError):
                        preferred_order = sorted(category_list)
                else:
                    preferred_order = sorted(category_list)
            except Exception as e:
                current_app.logger.warning(f"Could not load category order: {e}")
                preferred_order = sorted(category_list)
            
            all_categories = [cat for cat in category_list if cat not in deleted_categories_set]
            all_categories.sort(key=lambda x: (preferred_order.index(x) if x in preferred_order else len(preferred_order) + 1, x))
            
            product_tablet_type_ids = set(p['tablet_type_id'] for p in products if p['tablet_type_id'])
            tablet_types_without_products = [tt for tt in tablet_types if tt['id'] not in product_tablet_type_ids]
            
            return render_template('product_mapping.html', products=products, tablet_types=tablet_types, 
                                 categories=all_categories, tablet_types_without_products=tablet_types_without_products)
    except Exception as e:
        current_app.logger.error(f"Error loading product mapping: {str(e)}")
        flash(f'Error loading product mapping: {str(e)}', 'error')
        return render_template('product_mapping.html', products=[], tablet_types=[])


@bp.route('/admin/tablet_types')
@admin_required
def tablet_types_config():
    """Configuration page for tablet types and their inventory item IDs"""
    try:
        with db_read_only() as conn:
            tablet_types = conn.execute('''
                SELECT * FROM tablet_types 
                ORDER BY tablet_type_name
            ''').fetchall()
            
            return render_template('tablet_types_config.html', tablet_types=tablet_types)
    except Exception as e:
        current_app.logger.error(f"Error loading tablet types: {str(e)}")
        flash(f'Error loading tablet types: {str(e)}', 'error')
        return render_template('tablet_types_config.html', tablet_types=[])


@bp.route('/api/settings/cards_per_turn', methods=['GET', 'POST'])
@admin_required
def manage_cards_per_turn():
    """Get or update cards per turn setting"""
    try:
        ensure_app_settings_table()
        with db_transaction() as conn:
            if request.method == 'GET':
                setting = conn.execute(
                    'SELECT setting_value, description FROM app_settings WHERE setting_key = ?',
                    ('cards_per_turn',)
                ).fetchone()
                if setting:
                    return jsonify({
                        'success': True,
                        'value': int(setting['setting_value']),
                        'description': setting['description']
                    })
                else:
                    return jsonify({'success': False, 'error': 'Setting not found'}), 404
            
            elif request.method == 'POST':
                data = request.get_json()
                if not data:
                    return jsonify({'success': False, 'error': 'No data provided'}), 400
                
                cards_per_turn = data.get('cards_per_turn')
                
                if cards_per_turn is None:
                    return jsonify({'success': False, 'error': 'cards_per_turn is required'}), 400
                
                try:
                    cards_per_turn = int(cards_per_turn)
                    if cards_per_turn < 1:
                        return jsonify({'success': False, 'error': 'cards_per_turn must be at least 1'}), 400
                except (ValueError, TypeError):
                    return jsonify({'success': False, 'error': 'Invalid cards_per_turn value'}), 400
                
                existing = conn.execute(
                    'SELECT id FROM app_settings WHERE setting_key = ?',
                    ('cards_per_turn',)
                ).fetchone()
                
                if existing:
                    conn.execute('''
                        UPDATE app_settings 
                        SET setting_value = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE setting_key = ?
                    ''', (str(cards_per_turn), 'cards_per_turn'))
                else:
                    conn.execute('''
                        INSERT INTO app_settings (setting_key, setting_value, description)
                        VALUES (?, ?, ?)
                    ''', ('cards_per_turn', str(cards_per_turn), 'Number of cards produced in one turn of the machine'))
                
                return jsonify({
                    'success': True,
                    'message': f'Cards per turn updated to {cards_per_turn}'
                })
    except Exception as e:
        current_app.logger.error(f"Error managing cards_per_turn: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/add_employee', methods=['POST'])
@admin_required
def add_employee():
    """Add a new employee"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        full_name = data.get('full_name', '').strip()
        password = data.get('password', '').strip()
        role = data.get('role', 'warehouse_staff').strip()
        
        if not username or not full_name or not password:
            return jsonify({'success': False, 'error': 'Username, full name, and password required'}), 400
            
        valid_roles = ['warehouse_staff', 'manager', 'admin']
        if role not in valid_roles:
            return jsonify({'success': False, 'error': 'Invalid role specified'}), 400
            
        with db_transaction() as conn:
            existing = conn.execute(
                'SELECT id FROM employees WHERE username = ?', 
                (username,)
            ).fetchone()
            
            if existing:
                return jsonify({'success': False, 'error': 'Username already exists'}), 400
            
            password_hash = hash_password(password)
            conn.execute('''
                INSERT INTO employees (username, full_name, password_hash, role)
                VALUES (?, ?, ?, ?)
            ''', (username, full_name, password_hash, role))
            
            return jsonify({'success': True, 'message': f'Added employee: {full_name}'})
    except Exception as e:
        current_app.logger.error(f"Error adding employee: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/update_employee_role/<int:employee_id>', methods=['POST'])
@admin_required
def update_employee_role(employee_id):
    """Update an employee's role"""
    try:
        data = request.get_json()
        new_role = data.get('role', '').strip()
        
        valid_roles = ['warehouse_staff', 'manager', 'admin']
        if new_role not in valid_roles:
            return jsonify({'success': False, 'error': 'Invalid role specified'}), 400
            
        with db_transaction() as conn:
            employee = conn.execute(
                'SELECT id, username, full_name FROM employees WHERE id = ?', 
                (employee_id,)
            ).fetchone()
            
            if not employee:
                return jsonify({'success': False, 'error': 'Employee not found'}), 404
                
            conn.execute('''
                UPDATE employees 
                SET role = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (new_role, employee_id))
            
            return jsonify({
                'success': True, 
                'message': f'Updated {employee["full_name"]} role to {new_role.replace("_", " ").title()}'
            })
    except Exception as e:
        current_app.logger.error(f"Error updating employee role: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/toggle_employee/<int:employee_id>', methods=['POST'])
@admin_required
def toggle_employee(employee_id):
    """Toggle employee active status"""
    try:
        with db_transaction() as conn:
            employee = conn.execute(
                'SELECT full_name, is_active FROM employees WHERE id = ?', 
                (employee_id,)
            ).fetchone()
            
            if not employee:
                return jsonify({'success': False, 'error': 'Employee not found'}), 404
            
            new_status = not employee['is_active']
            conn.execute('''
                UPDATE employees 
                SET is_active = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (new_status, employee_id))
            
            status_text = 'activated' if new_status else 'deactivated'
            return jsonify({'success': True, 'message': f'{employee["full_name"]} {status_text}'})
    except Exception as e:
        current_app.logger.error(f"Error toggling employee: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/delete_employee/<int:employee_id>', methods=['DELETE'])
@admin_required
def delete_employee(employee_id):
    """Delete an employee"""
    try:
        with db_transaction() as conn:
            employee = conn.execute(
                'SELECT full_name FROM employees WHERE id = ?', 
                (employee_id,)
            ).fetchone()
            
            if not employee:
                return jsonify({'success': False, 'error': 'Employee not found'}), 404
            
            conn.execute('DELETE FROM employees WHERE id = ?', (employee_id,))
            
            return jsonify({'success': True, 'message': f'Deleted employee: {employee["full_name"]}'})
    except Exception as e:
        current_app.logger.error(f"Error deleting employee: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/submission/<int:submission_id>/admin_reassign', methods=['POST'])
@admin_required
def admin_reassign_verified_submission(submission_id):
    """Admin-only: Reassign a verified submission to a different PO (bypasses verification lock)"""
    try:
        data = request.get_json()
        new_po_id = data.get('new_po_id')
        confirm_override = data.get('confirm_override', False)
        
        if not new_po_id:
            return jsonify({'error': 'Missing new_po_id'}), 400
        
        if not confirm_override:
            return jsonify({'error': 'Admin override confirmation required'}), 400
        
        with db_transaction() as conn:
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
            
            old_po_id = submission['assigned_po_id']
            inventory_item_id = submission['inventory_item_id']
            
            new_po_check = conn.execute('''
                SELECT COUNT(*) as count
                FROM po_lines pl
                WHERE pl.po_id = ? AND pl.inventory_item_id = ?
            ''', (new_po_id, inventory_item_id)).fetchone()
            
            if new_po_check['count'] == 0:
                return jsonify({'error': 'Selected PO does not have this product'}), 400
            
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
            
            if old_po_id:
                old_line = conn.execute('''
                    SELECT id FROM po_lines 
                    WHERE po_id = ? AND inventory_item_id = ?
                    LIMIT 1
                ''', (old_po_id, inventory_item_id)).fetchone()
                
                if old_line:
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
            
            conn.execute('''
                UPDATE warehouse_submissions 
                SET assigned_po_id = ?
                WHERE id = ?
            ''', (new_po_id, submission_id))
            
            new_po = conn.execute('SELECT po_number FROM purchase_orders WHERE id = ?', (new_po_id,)).fetchone()
            
            return jsonify({
                'success': True,
                'message': f'Submission reassigned to PO-{new_po["po_number"]} (Admin override)'
            })
    except Exception as e:
        current_app.logger.error(f"Error in admin_reassign_verified_submission: {str(e)}")
        return jsonify({'error': str(e)}), 500


@bp.route('/api/admin/diagnose-submissions/<int:receive_id>', methods=['GET'])
@admin_required
def diagnose_submissions(receive_id):
    """Diagnose submission assignments for a specific receive"""
    try:
        with db_read_only() as conn:
            receive = conn.execute('''
                SELECT r.*, po.po_number
                FROM receiving r
                JOIN purchase_orders po ON r.po_id = po.id
                WHERE r.id = ?
            ''', (receive_id,)).fetchone()
            
            if not receive:
                return jsonify({'error': 'Receive not found'}), 404
            
            receive_dict = dict(receive)
            
            bags = conn.execute('''
                SELECT b.id as bag_id, b.bag_number, sb.box_number, b.bag_label_count,
                       tt.tablet_type_name, tt.inventory_item_id
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN tablet_types tt ON b.tablet_type_id = tt.id
                WHERE sb.receiving_id = ?
                ORDER BY sb.box_number, b.bag_number
            ''', (receive_id,)).fetchall()
            
            bag_info = []
            for bag in bags:
                bag_dict = dict(bag)
                
                submissions_by_bag_id = conn.execute('''
                    SELECT id, submission_type, employee_name, product_name, created_at
                    FROM warehouse_submissions
                    WHERE bag_id = ?
                ''', (bag_dict['bag_id'],)).fetchall()
                
                submissions_by_numbers = conn.execute('''
                    SELECT id, submission_type, employee_name, product_name, bag_id, created_at
                    FROM warehouse_submissions
                    WHERE assigned_po_id = ?
                    AND box_number = ?
                    AND bag_number = ?
                    AND (bag_id IS NULL OR bag_id != ?)
                ''', (receive_dict['po_id'], bag_dict['box_number'], bag_dict['bag_number'], bag_dict['bag_id'])).fetchall()
                
                bag_info.append({
                    'bag_id': bag_dict['bag_id'],
                    'box_bag': f"{bag_dict['box_number']}/{bag_dict['bag_number']}",
                    'tablet_type': bag_dict['tablet_type_name'],
                    'submissions_by_bag_id': [dict(s) for s in submissions_by_bag_id],
                    'submissions_with_wrong_bag_id': [dict(s) for s in submissions_by_numbers]
                })
            
            return jsonify({
                'success': True,
                'receive': receive_dict,
                'bags': bag_info
            })
    except Exception as e:
        current_app.logger.error(f"Error diagnosing submissions: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/admin/fix-bag-assignments', methods=['POST'])
@admin_required
def fix_bag_assignments():
    """Admin endpoint to fix bag_id assignments for submissions"""
    try:
        with db_transaction() as conn:
            submissions = conn.execute('''
                SELECT ws.id, ws.box_number, ws.bag_number, ws.assigned_po_id, ws.bag_id as current_bag_id,
                       ws.product_name, ws.employee_name, ws.submission_type
                FROM warehouse_submissions ws
                WHERE ws.assigned_po_id IS NOT NULL
                AND ws.box_number IS NOT NULL
                AND ws.bag_number IS NOT NULL
                ORDER BY ws.assigned_po_id, ws.box_number, ws.bag_number
            ''').fetchall()
            
            updated_count = 0
            skipped_count = 0
            no_bag_found = 0
            multiple_bags_found = 0
            updates = []
            
            for sub in submissions:
                sub_dict = dict(sub)
                
                inventory_item_id = conn.execute('SELECT inventory_item_id FROM warehouse_submissions WHERE id = ?', 
                                  (sub_dict['id'],)).fetchone()
                if not inventory_item_id:
                    continue
                    
                bag_rows = conn.execute('''
                    SELECT b.id as bag_id, r.id as receive_id, r.receive_name, tt.tablet_type_name
                    FROM bags b
                    JOIN small_boxes sb ON b.small_box_id = sb.id
                    JOIN receiving r ON sb.receiving_id = r.id
                    JOIN tablet_types tt ON b.tablet_type_id = tt.id
                    WHERE r.po_id = ?
                    AND sb.box_number = ?
                    AND b.bag_number = ?
                    AND tt.inventory_item_id = ?
                    ORDER BY r.received_date DESC, r.id DESC
                ''', (sub_dict['assigned_po_id'], sub_dict['box_number'], sub_dict['bag_number'], 
                      inventory_item_id[0])).fetchall()
                
                if len(bag_rows) == 1:
                    bag_dict = dict(bag_rows[0])
                    correct_bag_id = bag_dict['bag_id']
                    
                    if sub_dict['current_bag_id'] != correct_bag_id:
                        conn.execute('''
                            UPDATE warehouse_submissions
                            SET bag_id = ?
                            WHERE id = ?
                        ''', (correct_bag_id, sub_dict['id']))
                        
                        updates.append({
                            'submission_id': sub_dict['id'],
                            'type': sub_dict['submission_type'],
                            'product': sub_dict['product_name'],
                            'box_bag': f"{sub_dict['box_number']}/{sub_dict['bag_number']}",
                            'old_bag_id': sub_dict['current_bag_id'],
                            'new_bag_id': correct_bag_id,
                            'receive': bag_dict['receive_name']
                        })
                        updated_count += 1
                    else:
                        skipped_count += 1
                elif len(bag_rows) > 1:
                    multiple_bags_found += 1
                    updates.append({
                        'submission_id': sub_dict['id'],
                        'type': sub_dict['submission_type'],
                        'product': sub_dict['product_name'],
                        'box_bag': f"{sub_dict['box_number']}/{sub_dict['bag_number']}",
                        'old_bag_id': sub_dict['current_bag_id'],
                        'status': 'AMBIGUOUS',
                        'message': f'Found {len(bag_rows)} matching bags - needs manual review',
                        'possible_bags': [{'bag_id': dict(b)['bag_id'], 'receive': dict(b)['receive_name']} for b in bag_rows]
                    })
                else:
                    no_bag_found += 1
            
            return jsonify({
                'success': True,
                'message': f'Fixed {updated_count} bag assignments',
                'updated': updated_count,
                'skipped': skipped_count,
                'no_bag_found': no_bag_found,
                'multiple_bags_found': multiple_bags_found,
                'updates': updates
            })
    except Exception as e:
        current_app.logger.error(f"Error fixing bag assignments: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

