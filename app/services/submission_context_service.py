"""Shared context helpers for production submissions."""

from typing import Any


def normalize_optional_text(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    if value:
        cleaned = str(value).strip()
        return cleaned or None
    return None


def resolve_submission_employee_name(
    conn,
    submitted_employee_name: Any,
    employee_id: int | None,
    admin_authenticated: bool,
) -> dict[str, Any]:
    provided_name = normalize_optional_text(submitted_employee_name)
    if provided_name:
        return {'success': True, 'employee_name': provided_name}

    if admin_authenticated:
        return {'success': True, 'employee_name': 'Admin'}

    employee = conn.execute(
        'SELECT full_name FROM employees WHERE id = ?',
        (employee_id,),
    ).fetchone()
    if not employee:
        return {'success': False, 'status_code': 400, 'error': 'Employee not found'}

    employee_name = normalize_optional_text(employee['full_name'])
    if not employee_name:
        return {'success': False, 'status_code': 400, 'error': 'Employee name is required'}

    return {'success': True, 'employee_name': employee_name}
