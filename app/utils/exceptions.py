"""
Custom exception classes for the application.

These exceptions provide consistent error handling across the application.
"""


class ValidationError(Exception):
    """Raised when input validation fails."""
    pass


class NotFoundError(Exception):
    """Raised when a requested resource is not found."""
    pass


class DatabaseError(Exception):
    """Raised when a database operation fails."""
    pass


class ServiceError(Exception):
    """Raised when a service operation fails."""
    pass


class AuthenticationError(Exception):
    """Raised when authentication fails."""
    pass


class AuthorizationError(Exception):
    """Raised when authorization fails (user lacks required permissions)."""
    pass

