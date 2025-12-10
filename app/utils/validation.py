"""
Validation utilities for form and API input validation.
"""
from typing import Optional, Dict, Any, List
import re


def validate_required_fields(data: Dict[str, Any], required_fields: List[str]) -> Optional[str]:
    """
    Validate that all required fields are present and not empty.
    
    Args:
        data: Dictionary of data to validate
        required_fields: List of required field names
    
    Returns:
        Error message if validation fails, None if valid
    """
    missing_fields = []
    for field in required_fields:
        if field not in data or data[field] is None or str(data[field]).strip() == '':
            missing_fields.append(field)
    
    if missing_fields:
        return f"Missing required fields: {', '.join(missing_fields)}"
    return None


def validate_email(email: str) -> bool:
    """
    Validate email format.
    
    Args:
        email: Email address to validate
    
    Returns:
        True if valid email format, False otherwise
    """
    if not email:
        return False
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def validate_positive_integer(value: Any, field_name: str = "value") -> Optional[str]:
    """
    Validate that a value is a positive integer.
    
    Args:
        value: Value to validate
        field_name: Name of field for error message
    
    Returns:
        Error message if invalid, None if valid
    """
    try:
        num = int(value)
        if num < 0:
            return f"{field_name} must be a positive integer"
        return None
    except (ValueError, TypeError):
        return f"{field_name} must be a valid integer"


def validate_date_format(date_str: str, field_name: str = "date") -> Optional[str]:
    """
    Validate date string format (YYYY-MM-DD).
    
    Args:
        date_str: Date string to validate
        field_name: Name of field for error message
    
    Returns:
        Error message if invalid, None if valid
    """
    if not date_str:
        return f"{field_name} is required"
    
    pattern = r'^\d{4}-\d{2}-\d{2}$'
    if not re.match(pattern, date_str):
        return f"{field_name} must be in YYYY-MM-DD format"
    
    return None


def sanitize_string(value: str, max_length: Optional[int] = None) -> str:
    """
    Sanitize string input by trimming whitespace and optionally limiting length.
    
    Args:
        value: String to sanitize
        max_length: Optional maximum length
    
    Returns:
        Sanitized string
    """
    if not isinstance(value, str):
        value = str(value)
    
    sanitized = value.strip()
    if max_length and len(sanitized) > max_length:
        sanitized = sanitized[:max_length]
    
    return sanitized


def validate_integer_range(value: Any, min_val: Optional[int] = None, 
                          max_val: Optional[int] = None, 
                          field_name: str = "value") -> Optional[str]:
    """
    Validate that a value is an integer within a specified range.
    
    Args:
        value: Value to validate
        min_val: Minimum allowed value (inclusive)
        max_val: Maximum allowed value (inclusive)
        field_name: Name of field for error message
    
    Returns:
        Error message if invalid, None if valid
    """
    try:
        num = int(value)
        if min_val is not None and num < min_val:
            return f"{field_name} must be at least {min_val}"
        if max_val is not None and num > max_val:
            return f"{field_name} must be at most {max_val}"
        return None
    except (ValueError, TypeError):
        return f"{field_name} must be a valid integer"

