"""
Error handling utilities for secure error responses
"""
from flask import jsonify, current_app
from typing import Tuple, Optional, Dict, Any
from config import Config
import traceback


def safe_error_response(error: Exception, 
                        user_message: str = "An error occurred", 
                        status_code: int = 500,
                        include_details: bool = False) -> Tuple[Any, int]:
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
    error_details = {
        'success': False,
        'error': user_message
    }
    
    # Log the actual error for debugging
    current_app.logger.error(f"Error occurred: {str(error)}")
    current_app.logger.error(traceback.format_exc())
    
    # In development or if explicitly requested, include detailed error information
    if (Config.ENV != 'production' or include_details) and current_app.debug:
        error_details['error_type'] = type(error).__name__
        error_details['error_message'] = str(error)
        error_details['traceback'] = traceback.format_exc()
    
    return jsonify(error_details), status_code


def validation_error_response(validation_errors: Dict[str, str], 
                              status_code: int = 400) -> Tuple[Any, int]:
    """
    Create a validation error response.
    
    Args:
        validation_errors: Dictionary of field names to error messages
        status_code: HTTP status code (default 400)
    
    Returns:
        Tuple of (response, status_code)
    """
    return jsonify({
        'success': False,
        'error': 'Validation failed',
        'validation_errors': validation_errors
    }), status_code


def not_found_response(resource: str = "Resource") -> Tuple[Any, int]:
    """
    Create a not found error response.
    
    Args:
        resource: Name of the resource that was not found
    
    Returns:
        Tuple of (response, status_code)
    """
    return jsonify({
        'success': False,
        'error': f'{resource} not found'
    }), 404


def unauthorized_response(message: str = "Access denied") -> Tuple[Any, int]:
    """
    Create an unauthorized error response.
    
    Args:
        message: Error message
    
    Returns:
        Tuple of (response, status_code)
    """
    return jsonify({
        'success': False,
        'error': message
    }), 403


def forbidden_response(message: str = "Forbidden") -> Tuple[Any, int]:
    """
    Create a forbidden error response.
    
    Args:
        message: Error message
    
    Returns:
        Tuple of (response, status_code)
    """
    return jsonify({
        'success': False,
        'error': message
    }), 403


def bad_request_response(message: str = "Bad request") -> Tuple[Any, int]:
    """
    Create a bad request error response.
    
    Args:
        message: Error message
    
    Returns:
        Tuple of (response, status_code)
    """
    return jsonify({
        'success': False,
        'error': message
    }), 400


def success_response(data: Optional[Dict[str, Any]] = None, 
                    message: Optional[str] = None) -> Dict[str, Any]:
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


class DatabaseError(Exception):
    """Custom exception for database errors"""
    pass


class ValidationError(Exception):
    """Custom exception for validation errors"""
    pass


class AuthenticationError(Exception):
    """Custom exception for authentication errors"""
    pass


class AuthorizationError(Exception):
    """Custom exception for authorization errors"""
    pass


def handle_database_error(error: Exception, operation: str = "database operation") -> Tuple[Any, int]:
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
        return jsonify({
            'success': False,
            'error': 'A database error occurred. Please try again later.'
        }), 500
    else:
        return jsonify({
            'success': False,
            'error': f'Database error during {operation}',
            'details': str(error)
        }), 500
