import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Flask settings
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-change-in-production'
    
    # Zoho API settings
    ZOHO_CLIENT_ID = os.environ.get('ZOHO_CLIENT_ID')
    ZOHO_CLIENT_SECRET = os.environ.get('ZOHO_CLIENT_SECRET') 
    ZOHO_REFRESH_TOKEN = os.environ.get('ZOHO_REFRESH_TOKEN')
    ZOHO_ORGANIZATION_ID = os.environ.get('ZOHO_ORGANIZATION_ID', '856048585')  # Your org ID
    
    # Database
    DATABASE_URL = os.environ.get('DATABASE_URL') or 'sqlite:///tablet_counter.db'
    
    # App settings
    ITEMS_PER_PAGE = 50
    DEBUG = os.environ.get('FLASK_ENV') == 'development'
