"""
Helper functions for routes that need database schema checks
These functions ensure tables/columns exist before use
"""
from typing import Optional, Any
import logging
from app.models.database import init_db
from app.utils.db_utils import db_query

logger = logging.getLogger(__name__)


def get_setting(setting_key: str, default_value: Optional[Any] = None) -> Optional[Any]:
    """
    Get a setting value from app_settings table.
    
    Args:
        setting_key: The setting key to retrieve
        default_value: Default value to return if setting not found
    
    Returns:
        Setting value or default_value if not found
    """
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
        logger.error(f"Error getting setting {setting_key}: {e}")
        return default_value


def ensure_app_settings_table() -> None:
    """Ensure app_settings table exists"""
    init_db()  # This handles all table creation and migrations


def ensure_submission_type_column() -> None:
    """Ensure submission_type column exists"""
    init_db()  # Migrations handle this


def ensure_machine_counts_table() -> None:
    """Ensure machine_counts table exists"""
    init_db()  # Migrations handle this


def ensure_machine_count_columns() -> None:
    """Ensure machine count columns exist"""
    init_db()  # Migrations handle this













