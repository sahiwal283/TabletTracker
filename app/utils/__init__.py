"""
Utility functions and helpers
"""
from app.utils.db_utils import (
    get_db,
    db_connection,
    db_query,
    db_execute,
    db_execute_many,
    safe_db_operation
)
from app.utils.response_utils import (
    success_response,
    error_response,
    handle_db_error,
    flash_success,
    flash_error,
    flash_info
)
from app.utils.auth_utils import (
    admin_required,
    role_required,
    get_employee_role,
    has_permission,
    verify_password,
    hash_password
)
from app.utils.calculations import (
    calculate_tablet_totals,
    calculate_machine_tablets
)

__all__ = [
    'get_db',
    'db_connection',
    'db_query',
    'db_execute',
    'db_execute_many',
    'safe_db_operation',
    'success_response',
    'error_response',
    'handle_db_error',
    'flash_success',
    'flash_error',
    'flash_info',
    'admin_required',
    'role_required',
    'get_employee_role',
    'has_permission',
    'verify_password',
    'hash_password',
    'calculate_tablet_totals',
    'calculate_machine_tablets',
]

