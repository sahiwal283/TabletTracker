"""
Helper functions for routes that need database schema checks
These functions ensure tables/columns exist before use
"""
from app.models.database import init_db
from app.utils.db_utils import db_query


def get_setting(setting_key, default_value=None):
    """Get a setting value from app_settings table"""
    try:
        init_db()  # Ensure all tables exist
        result = db_query(
            'SELECT setting_value FROM app_settings WHERE setting_key = ?',
            (setting_key,),
            fetch_one=True
        )
        if result:
            return result['setting_value']
        return default_value
    except Exception as e:
        print(f"Error getting setting {setting_key}: {e}")
        return default_value


def ensure_app_settings_table():
    """Ensure app_settings table exists"""
    init_db()  # This handles all table creation and migrations


def ensure_submission_type_column():
    """Ensure submission_type column exists"""
    init_db()  # Migrations handle this


def ensure_machine_counts_table():
    """Ensure machine_counts table exists"""
    init_db()  # Migrations handle this


def ensure_machine_count_columns():
    """Ensure machine count columns exist"""
    init_db()  # Migrations handle this






