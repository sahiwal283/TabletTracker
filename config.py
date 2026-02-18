import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Flask settings
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        ENV = os.environ.get('FLASK_ENV', 'development')
        if ENV == 'production':
            raise ValueError("SECRET_KEY environment variable must be set in production")
        SECRET_KEY = 'dev-secret-change-in-production'  # Only allow in development
    
    # Admin authentication
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD')
    if not ADMIN_PASSWORD:
        ENV = os.environ.get('FLASK_ENV', 'development')
        if ENV == 'production':
            raise ValueError("ADMIN_PASSWORD environment variable must be set in production")
        ADMIN_PASSWORD = 'admin'  # Only allow in development
    
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
    DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'database', 'tablet_counter.db')
    DATABASE_URL = os.environ.get('DATABASE_URL') or f'sqlite:///{DATABASE_PATH}'
    
    # Security settings
    SESSION_COOKIE_SECURE = os.environ.get('FLASK_ENV') == 'production'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = 28800  # 8 hours in seconds
    
    # CSRF settings - match session lifetime to prevent token expiration during long work sessions
    WTF_CSRF_TIME_LIMIT = 28800  # 8 hours in seconds (same as session)
    
    # App settings
    ITEMS_PER_PAGE = 50
    DEBUG = os.environ.get('FLASK_ENV') == 'development'
    
    # Production settings
    ENV = os.environ.get('FLASK_ENV', 'development')
    TESTING = False

    # Performance baseline logging (request/query timing). Default: same as DEBUG.
    PERF_LOGGING = os.environ.get('PERF_LOGGING', '').lower() in ('1', 'true', 'yes') or os.environ.get('FLASK_ENV') == 'development'
    
    # Rate limiting (for future implementation)
    RATELIMIT_STORAGE_URL = "memory://"
    RATELIMIT_DEFAULT = "100 per hour"
