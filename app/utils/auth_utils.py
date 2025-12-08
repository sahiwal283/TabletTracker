"""
Authentication and authorization utilities
"""
from functools import wraps
from flask import session, request, jsonify, redirect, url_for
import hashlib


# Role-based access control system
ROLE_PERMISSIONS = {
    'warehouse_staff': ['warehouse', 'count'],
    'manager': ['warehouse', 'count', 'dashboard', 'shipping', 'reports'],
    'admin': ['all']  # Special case - admin has access to everything
}


def admin_required(f):
    """Decorator to require admin authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Allow if admin authenticated OR if employee authenticated with admin role
        if not (session.get('admin_authenticated') or 
                (session.get('employee_authenticated') and session.get('employee_role') == 'admin')):
            # Check if this is an API request (starts with /api/)
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': 'Access denied. Admin authentication required.'}), 403
            return redirect(url_for('auth.index'))  # Redirect to unified login
        return f(*args, **kwargs)
    return decorated_function


def role_required(required_permission):
    """Decorator that requires a specific permission/role"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Allow admin users to access any role-based route
            if session.get('admin_authenticated'):
                return f(*args, **kwargs)
                
            # Check employee authentication and permissions
            if not session.get('employee_authenticated') or not session.get('employee_id'):
                return redirect(url_for('auth.index'))  # Redirect to unified login
            
            username = session.get('employee_username')
            if not username or not has_permission(username, required_permission):
                from flask import flash
                flash(f'Access denied. You need {required_permission} permission to access this page.', 'error')
                return redirect(url_for('production.warehouse_form'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def employee_required(f):
    """Helper function to require employee login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Allow if employee authenticated OR if admin authenticated
        if not (session.get('employee_authenticated') or session.get('admin_authenticated')):
            return redirect(url_for('auth.index'))  # Redirect to unified login
        return f(*args, **kwargs)
    return decorated_function


def get_employee_role(username):
    """Get the role of an employee"""
    from app.utils.db_utils import db_query
    result = db_query(
        'SELECT role FROM employees WHERE username = ? AND is_active = 1',
        (username,),
        fetch_one=True
    )
    return result['role'] if result else None


def has_permission(username, required_permission):
    """Check if an employee has a specific permission"""
    role = get_employee_role(username)
    if not role:
        return False
    
    permissions = ROLE_PERMISSIONS.get(role, [])
    return 'all' in permissions or required_permission in permissions


def hash_password(password):
    """Hash a password using SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password, hash):
    """Verify a password against its hash"""
    return hashlib.sha256(password.encode()).hexdigest() == hash

