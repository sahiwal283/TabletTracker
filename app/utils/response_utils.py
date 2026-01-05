"""
Utility functions for consistent API responses and error handling.
"""
from flask import jsonify, flash, Response
from typing import Optional, Dict, Any, Tuple
import traceback
import logging

logger = logging.getLogger(__name__)


def success_response(message: str = "Success", data: Optional[Dict[str, Any]] = None, status_code: int = 200) -> Tuple[Response, int]:
    """
    Create a standardized success JSON response.
    
    Args:
        message: Success message
        data: Optional data to include
        status_code: HTTP status code
    
    Returns:
        Flask JSON response
    """
    response = {'success': True, 'message': message}
    if data:
        response.update(data)
    return jsonify(response), status_code


def error_response(error: str, status_code: int = 400, include_trace: bool = False) -> Tuple[Response, int]:
    """
    Create a standardized error JSON response.
    
    Args:
        error: Error message
        status_code: HTTP status code
        include_trace: Whether to include traceback (for debugging)
    
    Returns:
        Flask JSON response
    """
    response = {'success': False, 'error': error}
    if include_trace:
        response['traceback'] = traceback.format_exc()
    return jsonify(response), status_code


def handle_db_error(e: Exception, operation: str = "Database operation", include_trace: bool = True) -> Tuple[Response, int]:
    """
    Handle database errors consistently.
    
    Args:
        e: Exception object
        operation: Description of the operation
        include_trace: Whether to log traceback
    
    Returns:
        Error JSON response
    """
    error_msg = f"{operation} failed: {str(e)}"
    if include_trace:
        logger.error(f"{operation.upper()} ERROR: {str(e)}", exc_info=True)
    else:
        logger.error(f"{operation.upper()} ERROR: {str(e)}")
    return error_response(error_msg, status_code=500, include_trace=False)


def flash_success(message: str) -> None:
    """Flash a success message."""
    flash(message, 'success')


def flash_error(message: str) -> None:
    """Flash an error message."""
    flash(message, 'error')


def flash_info(message: str) -> None:
    """Flash an info message."""
    flash(message, 'info')

