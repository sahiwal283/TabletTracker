"""
Error handling utilities for secure error responses
"""

import traceback
from typing import Any

from config import Config
from flask import current_app, jsonify


def safe_error_response(
    error: Exception, user_message: str = "An error occurred", status_code: int = 500, include_details: bool = False
) -> tuple[Any, int]:
    """
    Create a safe error response that doesn't leak sensitive information in production.

    Args:
        error: The exception that occurred
        user_message: User-friendly error message
        status_code: HTTP status code
        include_details: Force include details (overrides production check)

    Returns:
        Tuple of (response, status_code)
    """
    error_details = {'success': False, 'error': user_message}

    # Log the actual error for debugging
    current_app.logger.error(f"Error occurred: {str(error)}")
    current_app.logger.error(traceback.format_exc())

    # In development or if explicitly requested, include detailed error information
    if (Config.ENV != 'production' or include_details) and current_app.debug:
        error_details['error_type'] = type(error).__name__
        error_details['error_message'] = str(error)
        error_details['traceback'] = traceback.format_exc()

    return jsonify(error_details), status_code


def validation_error_response(validation_errors: dict[str, str], status_code: int = 400) -> tuple[Any, int]:
    """
    Create a validation error response.

    Args:
        validation_errors: Dictionary of field names to error messages
        status_code: HTTP status code (default 400)

    Returns:
        Tuple of (response, status_code)
    """
    return jsonify(
        {'success': False, 'error': 'Validation failed', 'validation_errors': validation_errors}
    ), status_code


def not_found_response(resource: str = "Resource") -> tuple[Any, int]:
    """
    Create a not found error response.

    Args:
        resource: Name of the resource that was not found

    Returns:
        Tuple of (response, status_code)
    """
    return jsonify({'success': False, 'error': f'{resource} not found'}), 404


def unauthorized_response(message: str = "Access denied") -> tuple[Any, int]:
    """
    Create an unauthorized error response.

    Args:
        message: Error message

    Returns:
        Tuple of (response, status_code)
    """
    return jsonify({'success': False, 'error': message}), 403


def forbidden_response(message: str = "Forbidden") -> tuple[Any, int]:
    """
    Create a forbidden error response.

    Args:
        message: Error message

    Returns:
        Tuple of (response, status_code)
    """
    return jsonify({'success': False, 'error': message}), 403


def bad_request_response(message: str = "Bad request") -> tuple[Any, int]:
    """
    Create a bad request error response.

    Args:
        message: Error message

    Returns:
        Tuple of (response, status_code)
    """
    return jsonify({'success': False, 'error': message}), 400


def success_response(data: dict[str, Any] | None = None, message: str | None = None) -> dict[str, Any]:
    """
    Create a success response.

    Args:
        data: Optional data to include
        message: Optional success message

    Returns:
        Success response dictionary
    """
    response = {'success': True}

    if message:
        response['message'] = message

    if data:
        response.update(data)

    return response


# Import exceptions from centralized exceptions module


def handle_database_error(error: Exception, operation: str = "database operation") -> tuple[Any, int]:
    """
    Handle database errors safely.

    Args:
        error: The database error
        operation: Description of the operation that failed

    Returns:
        Tuple of (response, status_code)
    """
    current_app.logger.error(f"Database error during {operation}: {str(error)}")
    current_app.logger.error(traceback.format_exc())

    if Config.ENV == 'production':
        return jsonify({'success': False, 'error': 'A database error occurred. Please try again later.'}), 500
    else:
        return jsonify({'success': False, 'error': f'Database error during {operation}', 'details': str(error)}), 500
