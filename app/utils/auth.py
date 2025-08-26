"""
Authentication utilities
"""

import hashlib

def hash_password(password):
    """Hash a password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password, hash):
    """Verify a password against its hash"""
    return hashlib.sha256(password.encode()).hexdigest() == hash
