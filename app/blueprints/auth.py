"""
Authentication and login routes
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from datetime import timedelta
from app.utils.auth_utils import verify_password
from app.utils.db_utils import db_query
from app import babel

bp = Blueprint('auth', __name__)


@bp.route('/', methods=['GET', 'POST'])
def index():
    """Unified login system for both employees and admin"""
    # Check if already authenticated
    if session.get('admin_authenticated'):
        return redirect(url_for('admin.panel'))
    
    if session.get('employee_authenticated'):
        # Smart redirect based on role
        role = session.get('employee_role', 'warehouse_staff')
        if role in ['manager', 'admin']:
            return redirect(url_for('dashboard.admin_dashboard'))
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
            # Admin login
            from config import Config
            if username == Config.ADMIN_USERNAME and password == Config.ADMIN_PASSWORD:
                session['admin_authenticated'] = True
                session.permanent = True
                flash('Admin login successful', 'success')
                return redirect(url_for('admin.panel'))
            else:
                flash('Invalid admin credentials', 'error')
                return render_template('unified_login.html')
        else:
            # Employee login
            try:
                employee = db_query(
                    'SELECT id, username, full_name, password_hash, role, is_active FROM employees WHERE username = ? AND is_active = TRUE',
                    (username,),
                    fetch_one=True
                )
                
                if employee and verify_password(password, employee['password_hash']):
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
                        return redirect(url_for('dashboard.admin_dashboard'))
                    else:
                        flash(f'Welcome back, {employee["full_name"]}!', 'success')
                        return redirect(url_for('production.warehouse_form'))
                else:
                    flash('Invalid employee credentials', 'error')
                    return render_template('unified_login.html')
            except Exception as e:
                print(f"Login error in index(): {str(e)}")
                flash('An error occurred during login', 'error')
                return render_template('unified_login.html')
    
    # Show unified login page
    return render_template('unified_login.html')


@bp.route('/logout')
def logout():
    """Logout and clear session"""
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('auth.index'))

