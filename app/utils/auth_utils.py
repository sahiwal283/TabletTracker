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


def role_required(*required_roles):
    """Decorator to require specific role(s)"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get('employee_authenticated'):
                if request.path.startswith('/api/'):
                    return jsonify({'success': False, 'error': 'Authentication required'}), 401
                return redirect(url_for('auth.index'))
            
            user_role = session.get('employee_role', 'warehouse_staff')
            
            # Admin has access to everything
            if user_role == 'admin':
                return f(*args, **kwargs)
            
            # Check if user has required role
            if user_role not in required_roles:
                if request.path.startswith('/api/'):
                    return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
                flash('You do not have permission to access this page.', 'error')
                return redirect(url_for('dashboard.admin_dashboard'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


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

