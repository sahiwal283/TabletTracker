"""
Authentication and login routes
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app
from datetime import datetime, timedelta
import hmac
from config import Config
from app.utils.auth_utils import verify_password
from app.utils.db_utils import db_query, get_db
from __version__ import __version__, __title__, __description__

bp = Blueprint('auth', __name__)

# This will be set when the app is initialized
_limiter = None

def get_limiter():
    """Get the limiter instance from the app"""
    if not current_app:
        return None
    return current_app.extensions.get('limiter')


@bp.route('/', methods=['GET', 'POST'])
def index():
    """Unified login system for both employees and admin"""
    # Check if already authenticated
    if session.get('admin_authenticated'):
        return redirect(url_for('admin.admin_panel'))
    
    if session.get('employee_authenticated'):
        # Smart redirect based on role
        role = session.get('employee_role', 'warehouse_staff')
        if role in ['manager', 'admin']:
            return redirect(url_for('dashboard.dashboard_view'))
        else:
            return redirect(url_for('production.warehouse_form'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        login_type = request.form.get('login_type', 'employee')
        
        if not username or not password:
            flash('Username and password are required', 'error')
            return render_template('unified_login.html')
        
        if login_type == 'admin':
            # Admin login - use constant-time comparison to prevent timing attacks
            admin_password = Config.ADMIN_PASSWORD
            if hmac.compare_digest(password, admin_password) and username.lower() == 'admin':
                # Prevent session fixation by clearing old session and creating new one
                session.clear()
                session['admin_authenticated'] = True
                session['employee_role'] = 'admin'  # Set admin role for navigation
                session['login_time'] = datetime.now().isoformat()
                session.permanent = True
                flash('Welcome back, Admin!', 'success')
                return redirect(url_for('admin.admin_panel'))
            else:
                flash('Invalid admin credentials', 'error')
                return render_template('unified_login.html')
        else:
            # Employee login
            conn = None
            try:
                conn = get_db()
                employee = conn.execute('''
                    SELECT id, username, full_name, password_hash, role, is_active 
                    FROM employees 
                    WHERE username = ? AND is_active = TRUE
                ''', (username,)).fetchone()
                
                if employee and verify_password(password, employee['password_hash']):
                    # Prevent session fixation by clearing old session and creating new one
                    session.clear()
                    session['employee_authenticated'] = True
                    session['employee_id'] = employee['id']
                    session['employee_name'] = employee['full_name']
                    session['employee_username'] = employee['username']
                    session['employee_role'] = employee['role'] if employee['role'] else 'warehouse_staff'
                    session.permanent = True
                    
                    # Smart redirect based on role
                    role = employee['role'] if employee['role'] else 'warehouse_staff'
                    if role in ['manager', 'admin']:
                        flash(f'Welcome back, {employee["full_name"]}!', 'success')
                        return redirect(url_for('dashboard.dashboard_view'))
                    else:
                        flash(f'Welcome back, {employee["full_name"]}!', 'success')
                        return redirect(url_for('production.warehouse_form'))
                else:
                    # Log failed login attempt
                    current_app.logger.warning(f"Failed login attempt for username: {username}")
                    flash('Invalid employee credentials', 'error')
                    return render_template('unified_login.html')
            except Exception as e:
                current_app.logger.error(f"Login error in index(): {str(e)}")
                flash('An error occurred during login', 'error')
                return render_template('unified_login.html')
            finally:
                if conn:
                    try:
                        conn.close()
                    except:
                        pass
    
    # Show unified login page
    return render_template('unified_login.html')


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


@bp.route('/version')
def version():
    """Get application version information"""
    return jsonify({
        'version': __version__,
        'title': __title__,
        'description': __description__
    })

