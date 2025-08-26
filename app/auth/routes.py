"""
Authentication routes
"""

from flask import render_template, request, session, redirect, url_for, flash, current_app
from datetime import timedelta
from . import bp
from ..models.database import get_db
from ..utils.auth import verify_password
from ..config import Config

@bp.route('/', methods=['GET', 'POST'])
def index():
    """Unified login homepage"""
    # If already logged in, redirect appropriately
    if session.get('employee_authenticated'):
        # Role-based redirect for returning users
        role = session.get('employee_role')
        if not role:  # Session missing role - fix it
            conn = get_db()
            try:
                user = conn.execute('''
                    SELECT role, preferred_language FROM employees WHERE id = ?
                ''', (session.get('employee_id'),)).fetchone()
                if user and user['role']:
                    role = user['role'].strip()
                    # Also set preferred language if not already set
                    if not session.get('language') and user.get('preferred_language'):
                        preferred_lang = user['preferred_language']
                        if preferred_lang in current_app.config['LANGUAGES']:
                            session['language'] = preferred_lang
                else:
                    role = 'warehouse_staff'
                session['employee_role'] = role
                conn.close()
            except:
                role = 'warehouse_staff'
                session['employee_role'] = role
        
        if role in ['manager', 'admin']:
            return redirect(url_for('dashboard.admin_dashboard'))
        else:  # warehouse_staff
            return redirect(url_for('warehouse.warehouse_form'))
    
    if session.get('admin_authenticated'):
        return redirect(url_for('admin.admin_panel'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        login_type = request.form.get('login_type', 'employee')
        
        if not username or not password:
            flash('Username and password are required', 'error')
            return render_template('unified_login.html')
        
        if login_type == 'admin':
            # Admin login
            if password == Config.ADMIN_PASSWORD:
                session['admin_authenticated'] = True
                session.permanent = True
                current_app.permanent_session_lifetime = timedelta(hours=8)
                return redirect(url_for('admin.admin_panel'))
            else:
                flash('Invalid admin credentials', 'error')
                return render_template('unified_login.html')
        
        else:
            # Employee login
            conn = get_db()
            
            # Try to get employee with role migration fallback
            try:
                employee = conn.execute('''
                    SELECT id, username, full_name, password_hash, role, preferred_language 
                    FROM employees WHERE username = ? AND is_active = 1
                ''', (username,)).fetchone()
            except Exception as e:
                if "no column named" in str(e).lower():
                    # Handle missing columns with auto-migration
                    try:
                        conn.execute('ALTER TABLE employees ADD COLUMN role TEXT DEFAULT "warehouse_staff"')
                        conn.execute('ALTER TABLE employees ADD COLUMN preferred_language TEXT DEFAULT "en"')
                        conn.commit()
                        employee = conn.execute('''
                            SELECT id, username, full_name, password_hash, role, preferred_language 
                            FROM employees WHERE username = ? AND is_active = 1
                        ''', (username,)).fetchone()
                    except:
                        raise e
                else:
                    raise e
            
            conn.close()
            
            if employee and verify_password(password, employee['password_hash']):
                session['employee_authenticated'] = True
                session['employee_id'] = employee['id']
                session['employee_name'] = employee['full_name']
                session['employee_username'] = employee['username']
                
                # SIMPLE & DIRECT role assignment
                role = employee['role']  # Direct access, not .get()
                
                # Handle empty/null roles with proper defaults
                if not role or str(role).strip() == '':
                    role = 'warehouse_staff'
                    # Update database with default
                    try:
                        conn = get_db()
                        conn.execute('''
                            UPDATE employees SET role = ? WHERE id = ?
                        ''', (role, employee['id']))
                        conn.commit()
                        conn.close()
                    except Exception as e:
                        current_app.logger.error(f"Failed to update default role: {e}")
                else:
                    # Use existing role, ensure it's a clean string
                    role = str(role).strip()
                
                # DIRECT session assignment - no complex logic
                session['employee_role'] = role
                
                # Set preferred language from employee profile
                preferred_lang = employee.get('preferred_language', 'en')
                if preferred_lang and preferred_lang in current_app.config['LANGUAGES']:
                    session['language'] = preferred_lang
                
                session.permanent = True
                current_app.permanent_session_lifetime = timedelta(hours=8)
                
                # Role-based redirect
                if role in ['manager', 'admin']:
                    return redirect(url_for('dashboard.admin_dashboard'))
                else:  # warehouse_staff
                    return redirect(url_for('warehouse.warehouse_form'))
            else:
                flash('Invalid employee credentials', 'error')
                return render_template('unified_login.html')
    
    # Show unified login page
    return render_template('unified_login.html')

@bp.route('/admin-login')
def admin_login():
    """Redirect to unified login"""
    return redirect(url_for('auth.index'))

@bp.route('/logout')
def logout():
    """Unified logout for all user types"""
    session.clear()
    flash('You have been logged out successfully', 'success')
    return redirect(url_for('auth.index'))

@bp.route('/admin/logout')
def admin_logout():
    """Admin logout redirect"""
    return redirect(url_for('auth.logout'))
