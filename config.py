import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Flask settings
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-change-in-production'
    
    # Admin authentication
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD') or 'TabletTracker2024!'  # Change in production!
    
    # Zoho API settings
    ZOHO_CLIENT_ID = os.environ.get('ZOHO_CLIENT_ID')
    ZOHO_CLIENT_SECRET = os.environ.get('ZOHO_CLIENT_SECRET') 
    ZOHO_REFRESH_TOKEN = os.environ.get('ZOHO_REFRESH_TOKEN')
    ZOHO_ORGANIZATION_ID = os.environ.get('ZOHO_ORGANIZATION_ID', '856048585')  # Your org ID
    
    # UPS Tracking API (free; client credentials)
    UPS_CLIENT_ID = os.environ.get('UPS_CLIENT_ID')
    UPS_CLIENT_SECRET = os.environ.get('UPS_CLIENT_SECRET')
    # Base URL: 'https://apis.ups.com' (prod) or 'https://wwwcie.ups.com' (test)
    UPS_API_BASE = os.environ.get('UPS_API_BASE', 'https://apis.ups.com')
    UPS_TRANSACTION_SRC = os.environ.get('UPS_TRANSACTION_SRC', 'TabletTracker')

    # FedEx Tracking API (free with dev account)
    FEDEX_API_KEY = os.environ.get('FEDEX_API_KEY')
    FEDEX_API_SECRET = os.environ.get('FEDEX_API_SECRET')
    FEDEX_ACCOUNT_NUMBER = os.environ.get('FEDEX_ACCOUNT_NUMBER')
    FEDEX_BASE = os.environ.get('FEDEX_BASE', 'https://apis.fedex.com')
    
    # Database
    DATABASE_URL = os.environ.get('DATABASE_URL') or 'sqlite:///tablet_counter.db'
    
    # Security settings
    SESSION_COOKIE_SECURE = os.environ.get('FLASK_ENV') == 'production'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = 28800  # 8 hours in seconds
    
    # App settings
    ITEMS_PER_PAGE = 50
    DEBUG = os.environ.get('FLASK_ENV') == 'development'
    
    # Production settings
    ENV = os.environ.get('FLASK_ENV', 'development')
    TESTING = False
    
    # Rate limiting (for future implementation)
    RATELIMIT_STORAGE_URL = "memory://"
    RATELIMIT_DEFAULT = "100 per hour"
