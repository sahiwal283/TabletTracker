"""
Validation utilities for form and API input validation.
"""
from typing import Optional, Dict, Any, List, Union
import re
from datetime import datetime


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


def validate_username(username: str) -> Optional[str]:
    """
    Validate username format.
    
    Args:
        username: Username to validate
    
    Returns:
        Error message if invalid, None if valid
    """
    if not username:
        return "Username is required"
    
    username = username.strip()
    
    if len(username) < 3:
        return "Username must be at least 3 characters"
    
    if len(username) > 50:
        return "Username must be at most 50 characters"
    
    # Allow alphanumeric, underscore, hyphen, and dot
    pattern = r'^[a-zA-Z0-9._-]+$'
    if not re.match(pattern, username):
        return "Username can only contain letters, numbers, dots, underscores, and hyphens"
    
    return None


def validate_password_strength(password: str) -> Optional[str]:
    """
    Validate password strength.
    
    Args:
        password: Password to validate
    
    Returns:
        Error message if weak, None if strong enough
    """
    if not password:
        return "Password is required"
    
    if len(password) < 8:
        return "Password must be at least 8 characters long"
    
    # Check for at least one uppercase, one lowercase, and one digit
    if not re.search(r'[A-Z]', password):
        return "Password must contain at least one uppercase letter"
    
    if not re.search(r'[a-z]', password):
        return "Password must contain at least one lowercase letter"
    
    if not re.search(r'\d', password):
        return "Password must contain at least one digit"
    
    return None


def validate_file_extension(filename: str, allowed_extensions: List[str]) -> Optional[str]:
    """
    Validate file extension.
    
    Args:
        filename: Filename to validate
        allowed_extensions: List of allowed extensions (without dot)
    
    Returns:
        Error message if invalid, None if valid
    """
    if not filename:
        return "Filename is required"
    
    if '.' not in filename:
        return "File must have an extension"
    
    ext = filename.rsplit('.', 1)[1].lower()
    if ext not in [e.lower() for e in allowed_extensions]:
        return f"File extension must be one of: {', '.join(allowed_extensions)}"
    
    return None


def validate_tracking_number(tracking_number: str, carrier: Optional[str] = None) -> Optional[str]:
    """
    Validate tracking number format based on carrier.
    
    Args:
        tracking_number: Tracking number to validate
        carrier: Optional carrier name for specific validation
    
    Returns:
        Error message if invalid, None if valid
    """
    if not tracking_number:
        return "Tracking number is required"
    
    tracking_number = tracking_number.strip().upper()
    
    # Basic validation - alphanumeric and spaces/hyphens
    if not re.match(r'^[A-Z0-9\s-]+$', tracking_number):
        return "Tracking number can only contain letters, numbers, spaces, and hyphens"
    
    # Remove spaces and hyphens for length check
    clean_tracking = tracking_number.replace(' ', '').replace('-', '')
    
    if len(clean_tracking) < 10:
        return "Tracking number must be at least 10 characters"
    
    if len(clean_tracking) > 40:
        return "Tracking number must be at most 40 characters"
    
    # Carrier-specific validation
    if carrier:
        carrier_lower = carrier.lower()
        
        if carrier_lower == 'usps':
            # USPS tracking numbers are typically 20-22 digits
            if not (20 <= len(clean_tracking) <= 22):
                return "USPS tracking number should be 20-22 characters"
        
        elif carrier_lower == 'fedex':
            # FedEx tracking numbers are typically 12 digits
            if len(clean_tracking) != 12:
                return "FedEx tracking number should be 12 digits"
        
        elif carrier_lower == 'ups':
            # UPS tracking numbers are typically 18 characters starting with "1Z"
            if not (clean_tracking.startswith('1Z') and len(clean_tracking) == 18):
                return "UPS tracking number should start with '1Z' and be 18 characters"
    
    return None


def validate_phone_number(phone: str) -> Optional[str]:
    """
    Validate phone number format (flexible US format).
    
    Args:
        phone: Phone number to validate
    
    Returns:
        Error message if invalid, None if valid
    """
    if not phone:
        return None  # Phone is optional in most cases
    
    # Remove common formatting characters
    cleaned = re.sub(r'[\s\-\(\)\.]', '', phone)
    
    # Check if it's 10 or 11 digits (with optional country code)
    if not re.match(r'^1?\d{10}$', cleaned):
        return "Phone number must be 10 digits (or 11 with country code)"
    
    return None


def validate_po_number(po_number: str) -> Optional[str]:
    """
    Validate purchase order number format.
    
    Args:
        po_number: PO number to validate
    
    Returns:
        Error message if invalid, None if valid
    """
    if not po_number:
        return "PO number is required"
    
    po_number = po_number.strip()
    
    if len(po_number) < 3:
        return "PO number must be at least 3 characters"
    
    if len(po_number) > 50:
        return "PO number must be at most 50 characters"
    
    # Allow alphanumeric and common separators
    if not re.match(r'^[A-Z0-9\-_/]+$', po_number.upper()):
        return "PO number can only contain letters, numbers, hyphens, underscores, and slashes"
    
    return None


def safe_int(value: Any, default: int = 0) -> int:
    """
    Safely convert value to integer with default fallback.
    
    Args:
        value: Value to convert
        default: Default value if conversion fails
    
    Returns:
        Integer value or default
    """
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    """
    Safely convert value to float with default fallback.
    
    Args:
        value: Value to convert
        default: Default value if conversion fails
    
    Returns:
        Float value or default
    """
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_bool(value: Any, default: bool = False) -> bool:
    """
    Safely convert value to boolean.
    
    Args:
        value: Value to convert
        default: Default value if conversion unclear
    
    Returns:
        Boolean value
    """
    if isinstance(value, bool):
        return value
    
    if isinstance(value, str):
        value_lower = value.lower().strip()
        if value_lower in ('true', '1', 'yes', 'on', 't', 'y'):
            return True
        if value_lower in ('false', '0', 'no', 'off', 'f', 'n', ''):
            return False
    
    if isinstance(value, (int, float)):
        return bool(value)
    
    return default

