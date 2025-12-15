"""
Admin routes
"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session
from datetime import datetime, timedelta
import json
import traceback
from config import Config
from app.utils.db_utils import get_db
from app.utils.auth_utils import admin_required
from app.utils.route_helpers import ensure_app_settings_table

bp = Blueprint('admin', __name__)

@bp.route('/admin')
def admin_panel():
    """Admin panel with quick actions and product management"""
    # Check for admin session
    if not session.get('admin_authenticated'):
        return render_template('admin_login.html')
    
    conn = None
    try:
        ensure_app_settings_table()  # Ensure table exists
        conn = get_db()
        # Get current settings
        cards_per_turn = conn.execute(
            'SELECT setting_value FROM app_settings WHERE setting_key = ?',
            ('cards_per_turn',)
        ).fetchone()
        cards_per_turn_value = int(cards_per_turn['setting_value']) if cards_per_turn else 1
        return render_template('admin_panel.html', cards_per_turn=cards_per_turn_value)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return render_template('admin_panel.html', cards_per_turn=1)
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/admin/login', methods=['POST'])
def admin_login():
    """Handle admin login with enhanced security"""
    password = request.form.get('password') or request.json.get('password')
    
    # Get admin password from environment variable with secure default
    admin_password = Config.ADMIN_PASSWORD
    
    if password == admin_password:
        session['admin_authenticated'] = True
        session['employee_role'] = 'admin'  # Set admin role for navigation
        session['login_time'] = datetime.now().isoformat()
        session.permanent = True  # Make session permanent
        # Note: session lifetime is set in app factory
        
        return redirect(url_for('admin.admin_panel')) if request.form else jsonify({'success': True})
    else:
        # Log failed login attempt
        print(f"Failed admin login attempt from {request.remote_addr} at {datetime.now()}")
        
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
    conn = None
    try:
        conn = get_db()
        
        # Get all products with their tablet type and calculation details
        # Use LEFT JOIN to include products even if tablet_type_id is NULL or invalid
        products = conn.execute('''
            SELECT pd.*, tt.tablet_type_name, tt.inventory_item_id, tt.category
            FROM product_details pd
            LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            ORDER BY COALESCE(tt.tablet_type_name, ''), pd.product_name
        ''').fetchall()
        
        # Check if category column exists and add it if missing
        table_info = conn.execute("PRAGMA table_info(tablet_types)").fetchall()
        has_category_column = any(col[1] == 'category' for col in table_info)
        
        if not has_category_column:
            try:
                conn.execute('ALTER TABLE tablet_types ADD COLUMN category TEXT')
                conn.commit()
                has_category_column = True
            except Exception as e:
                print(f"Warning: Could not add category column: {e}")
        
        # Get tablet types for dropdown
        if has_category_column:
            tablet_types = conn.execute('SELECT * FROM tablet_types ORDER BY tablet_type_name').fetchall()
            # Get unique categories (including those with tablet types assigned)
            categories = conn.execute('SELECT DISTINCT category FROM tablet_types WHERE category IS NOT NULL AND category != "" ORDER BY category').fetchall()
            category_list = [cat['category'] for cat in categories] if categories else []
        else:
            # Fallback: get tablet types without category column
            tablet_types_raw = conn.execute('SELECT id, tablet_type_name, inventory_item_id FROM tablet_types ORDER BY tablet_type_name').fetchall()
            # Convert to dict format with None category
            tablet_types = [dict(row) for row in tablet_types_raw]
            for tt in tablet_types:
                tt['category'] = None
            category_list = []
        
        # Get deleted categories from app_settings
        deleted_categories_set = set()
        try:
            deleted_categories_json = conn.execute('''
                SELECT setting_value FROM app_settings WHERE setting_key = 'deleted_categories'
            ''').fetchone()
            if deleted_categories_json and deleted_categories_json['setting_value']:
                deleted_categories_set = set(json.loads(deleted_categories_json['setting_value']))
        except Exception as e:
            print(f"Warning: Could not load deleted categories: {e}")
            # Continue without filtering if there's an error
        
        # Get category order from app_settings (or use alphabetical as fallback)
        try:
            category_order_json = conn.execute('''
                SELECT setting_value FROM app_settings WHERE setting_key = 'category_order'
            ''').fetchone()
            if category_order_json and category_order_json['setting_value']:
                preferred_order = json.loads(category_order_json['setting_value'])
            else:
                # No saved order - use alphabetical
                preferred_order = sorted(category_list)
        except Exception as e:
            print(f"Warning: Could not load category order: {e}")
            preferred_order = sorted(category_list)
        
        # Filter out deleted categories from the list
        all_categories = [cat for cat in category_list if cat not in deleted_categories_set]
        
        # Sort by preferred order (categories not in preferred_order go at the end alphabetically)
        all_categories.sort(key=lambda x: (preferred_order.index(x) if x in preferred_order else len(preferred_order) + 1, x))
        
        # Find tablet types that don't have product configurations yet
        product_tablet_type_ids = set(p['tablet_type_id'] for p in products if p.get('tablet_type_id'))
        tablet_types_without_products = [tt for tt in tablet_types if tt['id'] not in product_tablet_type_ids]
        
        return render_template('product_mapping.html', products=products, tablet_types=tablet_types, 
                             categories=all_categories, tablet_types_without_products=tablet_types_without_products)
    except Exception as e:
        flash(f'Error loading product mapping: {str(e)}', 'error')
        return render_template('product_mapping.html', products=[], tablet_types=[])
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/admin/tablet_types')
@admin_required
def tablet_types_config():
    """Configuration page for tablet types and their inventory item IDs"""
    conn = None
    try:
        conn = get_db()
        
        # Get all tablet types with their current inventory item IDs
        tablet_types = conn.execute('''
            SELECT * FROM tablet_types 
            ORDER BY tablet_type_name
        ''').fetchall()
        
        return render_template('tablet_types_config.html', tablet_types=tablet_types)
    except Exception as e:
        flash(f'Error loading tablet types: {str(e)}', 'error')
        return render_template('tablet_types_config.html', tablet_types=[])
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass



@bp.route('/admin/employees')
@admin_required
def manage_employees():
    """Employee management page"""
    conn = None
    try:
        conn = get_db()
        employees = conn.execute('''
            SELECT id, username, full_name, role, is_active, created_at
            FROM employees 
            ORDER BY role, full_name
        ''').fetchall()
        
        return render_template('employee_management.html', employees=employees)
    except Exception as e:
        print(f"Error in manage_employees: {e}")
        traceback.print_exc()
        flash('An error occurred while loading employees', 'error')
        return render_template('employee_management.html', employees=[])
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

