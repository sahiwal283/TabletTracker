"""
Permission checking utilities for role-based access control.

This module consolidates permission logic used by auth_utils decorators
and provides helper functions for checking permissions.
"""
from flask import session
from typing import List, Optional


def has_role(required_role: str) -> bool:
    """
    Check if current user has the specified role.
    
    Args:
        required_role: Role to check for ('admin', 'manager', 'warehouse', 'shipping')
    
    Returns:
        True if user has the role, False otherwise
    """
    if session.get('admin_authenticated'):
        return True  # Admin has all roles
    
    employee_role = session.get('employee_role')
    if not employee_role:
        return False
    
    # Role hierarchy: admin > manager > warehouse/shipping
    role_hierarchy = {
        'admin': ['admin', 'manager', 'warehouse', 'shipping'],
        'manager': ['manager', 'warehouse', 'shipping'],
        'warehouse': ['warehouse'],
        'shipping': ['shipping']
    }
    
    return required_role in role_hierarchy.get(employee_role, [])


def has_any_role(required_roles: List[str]) -> bool:
    """
    Check if current user has any of the specified roles.
    
    Args:
        required_roles: List of roles to check
    
    Returns:
        True if user has any of the roles, False otherwise
    """
    return any(has_role(role) for role in required_roles)


def is_admin() -> bool:
    """Check if current user is admin."""
    return session.get('admin_authenticated', False) or session.get('employee_role') == 'admin'


def is_manager() -> bool:
    """Check if current user is manager or admin."""
    return is_admin() or session.get('employee_role') == 'manager'


def is_authenticated() -> bool:
    """Check if user is authenticated (admin or employee)."""
    return session.get('admin_authenticated', False) or session.get('employee_authenticated', False)


def get_current_user_role() -> Optional[str]:
    """
    Get the current user's role.
    
    Returns:
        Role string ('admin', 'manager', 'warehouse', 'shipping') or None
    """
    if session.get('admin_authenticated'):
        return 'admin'
    return session.get('employee_role')


def can_edit_submission(submission_data: dict) -> bool:
    """
    Check if current user can edit a submission.
    
    Args:
        submission_data: Submission data dictionary
    
    Returns:
        True if user can edit, False otherwise
    """
    # Admins and managers can edit any submission
    if is_manager():
        return True
    
    # Regular employees can only edit their own unverified submissions
    if session.get('employee_id') == submission_data.get('employee_id'):
        return not submission_data.get('verified', False)
    
    return False


def can_delete_submission(submission_data: dict) -> bool:
    """
    Check if current user can delete a submission.
    
    Args:
        submission_data: Submission data dictionary
    
    Returns:
        True if user can delete, False otherwise
    """
    # Only admins and managers can delete
    return is_manager()


def can_manage_purchase_orders() -> bool:
    """Check if user can manage purchase orders."""
    return is_manager()


def can_manage_employees() -> bool:
    """Check if user can manage employees."""
    return is_admin()


def can_view_dashboard() -> bool:
    """Check if user can view dashboard."""
    return is_manager()


def can_sync_zoho() -> bool:
    """Check if user can sync with Zoho."""
    return is_manager()

