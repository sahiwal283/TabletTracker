"""
Sanitization utilities for preventing XSS attacks
"""
import bleach
import html
from typing import Optional, Union


# Allowed HTML tags and attributes for rich text (very restrictive)
ALLOWED_TAGS = [
    'p', 'br', 'strong', 'em', 'u', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li', 'a', 'span', 'div', 'blockquote', 'code', 'pre'
]

ALLOWED_ATTRIBUTES = {
    'a': ['href', 'title'],
    'span': ['class'],
    'div': ['class']
}

# Allowed protocols for links
ALLOWED_PROTOCOLS = ['http', 'https', 'mailto']


def sanitize_html(input_html: Optional[str], strip_tags: bool = False) -> str:
    """
    Sanitize HTML content to prevent XSS attacks.
    
    Args:
        input_html: The HTML string to sanitize
        strip_tags: If True, remove all HTML tags. If False, allow safe tags.
    
    Returns:
        Sanitized HTML string
    """
    if not input_html:
        return ''
    
    if strip_tags:
        # Strip all HTML tags, leaving only text
        return bleach.clean(input_html, tags=[], strip=True)
    
    # Allow only safe HTML tags and attributes
    return bleach.clean(
        input_html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True
    )


def escape_html(text: Optional[str]) -> str:
    """
    Escape HTML special characters to prevent XSS.
    Use this for plain text that should be displayed as-is.
    
    Args:
        text: The text to escape
    
    Returns:
        HTML-escaped string
    """
    if not text:
        return ''
    
    return html.escape(str(text), quote=True)


def sanitize_for_js(text: Optional[str]) -> str:
    """
    Sanitize text for safe inclusion in JavaScript strings.
    Escapes quotes, backslashes, and control characters.
    
    Args:
        text: The text to sanitize
    
    Returns:
        JavaScript-safe string
    """
    if not text:
        return ''
    
    # First escape HTML entities
    text = escape_html(str(text))
    
    # Then escape JavaScript special characters
    replacements = {
        '\\': '\\\\',
        '"': '\\"',
        "'": "\\'",
        '\n': '\\n',
        '\r': '\\r',
        '\t': '\\t',
        '\b': '\\b',
        '\f': '\\f'
    }
    
    for old, new in replacements.items():
        text = text.replace(old, new)
    
    return text


def sanitize_filename(filename: Optional[str]) -> str:
    """
    Sanitize filename to prevent directory traversal and other attacks.
    
    Args:
        filename: The filename to sanitize
    
    Returns:
        Safe filename
    """
    if not filename:
        return 'unnamed'
    
    # Remove path components
    import os
    filename = os.path.basename(filename)
    
    # Remove dangerous characters
    dangerous_chars = ['..', '/', '\\', '\0', '<', '>', ':', '"', '|', '?', '*']
    for char in dangerous_chars:
        filename = filename.replace(char, '_')
    
    # Remove leading/trailing dots and spaces
    filename = filename.strip('. ')
    
    # Ensure filename is not empty
    if not filename:
        return 'unnamed'
    
    # Limit length
    max_length = 255
    if len(filename) > max_length:
        name, ext = os.path.splitext(filename)
        filename = name[:max_length - len(ext)] + ext
    
    return filename


def sanitize_url(url: Optional[str], allowed_schemes: Optional[list] = None) -> Optional[str]:
    """
    Sanitize URL to prevent javascript: and data: URL attacks.
    
    Args:
        url: The URL to sanitize
        allowed_schemes: List of allowed URL schemes (default: ['http', 'https'])
    
    Returns:
        Sanitized URL or None if invalid
    """
    if not url:
        return None
    
    if allowed_schemes is None:
        allowed_schemes = ['http', 'https']
    
    url = url.strip()
    
    # Reject javascript: and data: URLs
    url_lower = url.lower()
    if url_lower.startswith('javascript:') or url_lower.startswith('data:') or url_lower.startswith('vbscript:'):
        return None
    
    # Check if URL has a valid scheme
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        if parsed.scheme and parsed.scheme.lower() not in allowed_schemes:
            return None
    except Exception:
        return None
    
    return url


def sanitize_sql_like_pattern(pattern: Optional[str]) -> str:
    """
    Escape SQL LIKE pattern special characters.
    Use this when building LIKE queries with user input.
    
    Args:
        pattern: The pattern to escape
    
    Returns:
        Escaped pattern safe for SQL LIKE
    """
    if not pattern:
        return ''
    
    # Escape LIKE special characters
    pattern = str(pattern)
    pattern = pattern.replace('\\', '\\\\')  # Escape backslash first
    pattern = pattern.replace('%', '\\%')    # Escape %
    pattern = pattern.replace('_', '\\_')    # Escape _
    
    return pattern


def sanitize_json_string(data: Union[str, dict, list, None]) -> str:
    """
    Safely convert data to JSON string for embedding in HTML.
    
    Args:
        data: Data to convert to JSON
    
    Returns:
        JSON string safe for HTML embedding
    """
    import json
    
    if data is None:
        return 'null'
    
    # Convert to JSON
    json_str = json.dumps(data)
    
    # Make safe for HTML by escaping dangerous characters
    json_str = json_str.replace('</', '<\\/')  # Prevent </script> injection
    json_str = json_str.replace('<', '\\u003c')
    json_str = json_str.replace('>', '\\u003e')
    json_str = json_str.replace('&', '\\u0026')
    
    return json_str


def validate_integer(value: any, min_val: Optional[int] = None, max_val: Optional[int] = None) -> Optional[int]:
    """
    Safely validate and convert value to integer.
    
    Args:
        value: Value to convert
        min_val: Minimum allowed value
        max_val: Maximum allowed value
    
    Returns:
        Integer value or None if invalid
    """
    try:
        int_val = int(value)
        
        if min_val is not None and int_val < min_val:
            return None
        
        if max_val is not None and int_val > max_val:
            return None
        
        return int_val
    except (ValueError, TypeError):
        return None


def validate_float(value: any, min_val: Optional[float] = None, max_val: Optional[float] = None) -> Optional[float]:
    """
    Safely validate and convert value to float.
    
    Args:
        value: Value to convert
        min_val: Minimum allowed value
        max_val: Maximum allowed value
    
    Returns:
        Float value or None if invalid
    """
    try:
        float_val = float(value)
        
        if min_val is not None and float_val < min_val:
            return None
        
        if max_val is not None and float_val > max_val:
            return None
        
        return float_val
    except (ValueError, TypeError):
        return None


