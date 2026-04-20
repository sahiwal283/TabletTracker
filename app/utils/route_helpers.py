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
    ensure_warehouse_submission_edit_password_default()


def ensure_warehouse_submission_edit_password_default() -> None:
    """
    Seed bcrypt hash for default warehouse submission-edit password if missing.
    Default plain password matches initial rollout (admin should rotate in admin panel).
    """
    from app.utils.auth_utils import hash_password
    from app.utils.db_utils import db_read_only, db_transaction

    key = 'warehouse_submission_edit_password_hash'
    try:
        init_db()
        with db_read_only() as conn:
            row = conn.execute(
                'SELECT 1 FROM app_settings WHERE setting_key = ?',
                (key,),
            ).fetchone()
        if row:
            return
        with db_transaction() as conn:
            conn.execute(
                '''
                INSERT INTO app_settings (setting_key, setting_value, description)
                VALUES (?, ?, ?)
                ''',
                (
                    key,
                    hash_password('1714'),
                    'Bcrypt hash for warehouse submission edit unlock (set/rotated via admin API)',
                ),
            )
    except Exception as e:
        logger.error(f"Error ensuring warehouse submission edit password default: {e}")


def ensure_submission_type_column() -> None:
    """Ensure submission_type column exists"""
    init_db()  # Migrations handle this


def ensure_machine_counts_table() -> None:
    """Ensure machine_counts table exists"""
    init_db()  # Migrations handle this


def ensure_machine_count_columns() -> None:
    """Ensure machine count columns exist"""
    init_db()  # Migrations handle this













