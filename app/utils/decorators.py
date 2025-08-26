"""
Custom decorators for authentication and authorization
"""

from functools import wraps
from flask import session, redirect, url_for, flash, render_template, current_app
from ..models.database import get_db

def admin_required(f):
    """Decorator to require admin authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_authenticated'):
            return redirect(url_for('auth.admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def employee_required(f):
    """Decorator to require employee authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('employee_authenticated') or not session.get('employee_id'):
            return redirect(url_for('auth.index'))
        return f(*args, **kwargs)
    return decorated_function

# Role-based access control system
ROLE_PERMISSIONS = {
    'warehouse_staff': ['warehouse', 'count'],
    'manager': ['warehouse', 'count', 'dashboard', 'shipping', 'reports'],
    'admin': ['all']  # Special case - admin has access to everything
}

def get_employee_role(username):
    """Get the role of an employee"""
    conn = get_db()
    try:
        result = conn.execute(
            'SELECT role FROM employees WHERE username = ? AND is_active = 1',
            (username,)
        ).fetchone()
        conn.close()
        return result['role'] if result else None
    except:
        conn.close()
        return None

def has_permission(username, required_permission):
    """Check if user has the required permission"""
    if session.get('admin_authenticated'):
        return True  # Admin has all permissions
    
    role = get_employee_role(username)
    if not role:
        return False
    
    permissions = ROLE_PERMISSIONS.get(role, [])
    return required_permission in permissions or 'all' in permissions

def role_required(required_permission):
    """Decorator to require specific role permissions"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get('employee_authenticated') and not session.get('admin_authenticated'):
                return redirect(url_for('auth.index'))
            
            # Admin always has access
            if session.get('admin_authenticated'):
                return f(*args, **kwargs)
            
            # Check employee permissions
            username = session.get('employee_username')
            if not username or not has_permission(username, required_permission):
                flash('You do not have permission to access this page.', 'error')
                return redirect(url_for('auth.index'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def setup_error_handlers(app):
    """Setup application-wide error handlers"""
    
    @app.errorhandler(404)
    def not_found_error(error):
        if app.config['ENV'] == 'production':
            return render_template('base.html'), 404
        return str(error), 404

    @app.errorhandler(500)
    def internal_error(error):
        if app.config['ENV'] == 'production':
            return render_template('base.html'), 500
        return str(error), 500

    @app.after_request
    def after_request(response):
        if app.config['ENV'] == 'production':
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['X-Frame-Options'] = 'DENY'
            response.headers['X-XSS-Protection'] = '1; mode=block'
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response
