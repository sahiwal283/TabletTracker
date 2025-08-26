"""
Configuration management for TabletTracker
"""

import os
from dotenv import load_dotenv

# Load environment variables
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '../.env'))

class Config:
    """Base configuration class"""
    
    # Flask settings
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    ENV = os.environ.get('FLASK_ENV', 'development')
    DEBUG = ENV == 'development'
    
    # Database settings
    DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///tablet_counter.db')
    
    # Session settings
    PERMANENT_SESSION_LIFETIME = int(os.environ.get('SESSION_TIMEOUT', '28800'))  # 8 hours
    
    # Zoho API configuration
    ZOHO_CLIENT_ID = os.environ.get('ZOHO_CLIENT_ID', '')
    ZOHO_CLIENT_SECRET = os.environ.get('ZOHO_CLIENT_SECRET', '')
    ZOHO_REFRESH_TOKEN = os.environ.get('ZOHO_REFRESH_TOKEN', '')
    ZOHO_ORGANIZATION_ID = os.environ.get('ZOHO_ORGANIZATION_ID', '')
    
    # Admin configuration
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin')
    
    # Rate limiting (if needed)
    RATELIMIT_DEFAULT = "100 per hour"

class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    ENV = 'development'

class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    ENV = 'production'
    
    # Enhanced security for production
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    DATABASE_URL = 'sqlite:///:memory:'  # In-memory database for tests
