"""
Authentication and authorization utilities
"""
from functools import wraps
from typing import Callable, Any, Optional
from flask import session, request, jsonify, redirect, url_for, Response
import bcrypt
import hmac


# Role-based access control system
ROLE_PERMISSIONS = {
    'warehouse_staff': ['warehouse', 'count'],
    'manager': ['warehouse', 'count', 'dashboard', 'shipping', 'reports'],
    'admin': ['all']  # Special case - admin has access to everything
}


def admin_required(f: Callable) -> Callable:
    """Decorator to require admin authentication"""
    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        # Allow if admin authenticated OR if employee authenticated with admin role
        if not (session.get('admin_authenticated') or 
                (session.get('employee_authenticated') and session.get('employee_role') == 'admin')):
            # Check if this is an API request (starts with /api/)
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': 'Access denied. Admin authentication required.'}), 403
            return redirect(url_for('auth.index'))  # Redirect to unified login
        return f(*args, **kwargs)
    return decorated_function


def role_required(required_permission: str) -> Callable:
    """Decorator that requires a specific permission/role"""
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def decorated_function(*args: Any, **kwargs: Any) -> Any:
            # Allow admin users to access any role-based route
            if session.get('admin_authenticated'):
                return f(*args, **kwargs)
            
            # Check if this is an API request (starts with /api/)
            is_api_request = request.path.startswith('/api/')
                
            # Check employee authentication and permissions
            if not session.get('employee_authenticated') or not session.get('employee_id'):
                if is_api_request:
                    return jsonify({'success': False, 'error': 'Access denied. Authentication required.'}), 401
                return redirect(url_for('auth.index'))  # Redirect to unified login
            
            username = session.get('employee_username')
            if not username or not has_permission(username, required_permission):
                if is_api_request:
                    return jsonify({'success': False, 'error': f'Access denied. You need {required_permission} permission to access this endpoint.'}), 403
                from flask import flash
                flash(f'Access denied. You need {required_permission} permission to access this page.', 'error')
                return redirect(url_for('production.warehouse_form'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def employee_required(f: Callable) -> Callable:
    """Helper function to require employee login"""
    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        # Allow if employee authenticated OR if admin authenticated
        if not (session.get('employee_authenticated') or session.get('admin_authenticated')):
            # Check if this is an API request (starts with /api/)
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': 'Access denied. Authentication required.'}), 401
            return redirect(url_for('auth.index'))  # Redirect to unified login
        return f(*args, **kwargs)
    return decorated_function


def get_employee_role(username: str) -> Optional[str]:
    """
    Get the role of an employee.
    
    Args:
        username: Employee username
    
    Returns:
        Employee role or None if not found
    """
    from app.utils.db_utils import db_query
    result = db_query(
        'SELECT role FROM employees WHERE username = ? AND is_active = 1',
        (username,),
        fetch_one=True
    )
    return result['role'] if result else None


def has_permission(username: str, required_permission: str) -> bool:
    """
    Check if an employee has a specific permission.
    
    Args:
        username: Employee username
        required_permission: Required permission name
    
    Returns:
        True if employee has permission, False otherwise
    """
    role = get_employee_role(username)
    if not role:
        return False
    
    permissions = ROLE_PERMISSIONS.get(role, [])
    return 'all' in permissions or required_permission in permissions


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt with automatic salt.
    
    Args:
        password: Plain text password
    
    Returns:
        Hashed password string
    """
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    """
    Verify a password against its hash using constant-time comparison.
    
    Args:
        password: Plain text password to verify
        password_hash: Stored password hash
    
    Returns:
        True if password matches, False otherwise
    """
    try:
        # Try bcrypt verification first (new format)
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    except (ValueError, AttributeError):
        # Fallback for old SHA256 hashes (for migration period)
        # This allows existing passwords to work until users log in and passwords are rehashed
        import hashlib
        computed_hash = hashlib.sha256(password.encode()).hexdigest()
        return hmac.compare_digest(computed_hash, password_hash)

