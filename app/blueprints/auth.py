"""
Authentication and login routes
"""
import hmac
from datetime import datetime

from config import Config
from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for

from app.utils.auth_utils import verify_password
from app.utils.db_utils import db_read_only
from app.utils.version_display import read_version_constants

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

        if not username or not password:
            flash('Username and password are required', 'error')
            return render_template('unified_login.html')

        # Single form: reserved username `admin` (case-insensitive) uses the deployment
        # ADMIN_PASSWORD; everyone else authenticates against the employees table.
        if username.lower() == 'admin':
            admin_password = Config.ADMIN_PASSWORD
            if hmac.compare_digest(password, admin_password):
                session.clear()
                session['admin_authenticated'] = True
                session['employee_role'] = 'admin'
                session['login_time'] = datetime.now().isoformat()
                session.permanent = True
                flash('Welcome back, Admin!', 'success')
                return redirect(url_for('admin.admin_panel'))
            flash('Invalid username or password', 'error')
            return render_template('unified_login.html')

        try:
            with db_read_only() as conn:
                employee = conn.execute(
                    '''
                    SELECT id, username, full_name, password_hash, role, is_active
                    FROM employees
                    WHERE username = ? AND is_active = TRUE
                    ''',
                    (username,),
                ).fetchone()

                if employee and verify_password(password, employee['password_hash']):
                    session.clear()
                    session['employee_authenticated'] = True
                    session['employee_id'] = employee['id']
                    session['employee_name'] = employee['full_name']
                    session['employee_username'] = employee['username']
                    session['employee_role'] = employee['role'] if employee['role'] else 'warehouse_staff'
                    session.permanent = True

                    role = employee['role'] if employee['role'] else 'warehouse_staff'
                    if role in ['manager', 'admin']:
                        flash(f'Welcome back, {employee["full_name"]}!', 'success')
                        return redirect(url_for('dashboard.dashboard_view'))
                    flash(f'Welcome back, {employee["full_name"]}!', 'success')
                    return redirect(url_for('production.warehouse_form'))
                current_app.logger.warning(f"Failed login attempt for username: {username}")
                flash('Invalid username or password', 'error')
                return render_template('unified_login.html')
        except Exception as e:
            current_app.logger.error(f"Login error in index(): {str(e)}")
            flash('An error occurred during login', 'error')
            return render_template('unified_login.html')

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


@bp.route('/api/csrf-token', methods=['GET'])
def get_csrf_token():
    """Get a fresh CSRF token - useful for long-running forms to prevent token expiration"""
    from flask_wtf.csrf import generate_csrf
    token = generate_csrf()
    return jsonify({'csrf_token': token})


@bp.route('/version')
def version():
    """Get application version information"""
    meta = read_version_constants()
    return jsonify({
        'version': meta['__version__'],
        'title': meta['__title__'],
        'description': meta['__description__'],
    })


@bp.route('/health')
def health():
    """Liveness for reverse proxies and orchestration (no auth)."""
    return jsonify({'status': 'ok'}), 200

