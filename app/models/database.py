"""
Database connection and initialization utilities
"""
import sqlite3
from contextlib import contextmanager
from app.utils.db_utils import get_db as _get_db, db_connection as _db_connection


def get_db():
    """Get a database connection with Row factory."""
    return _get_db()


@contextmanager
def db_connection():
    """Context manager for database connections with automatic cleanup."""
    with _db_connection() as conn:
        yield conn


def init_db():
    """
    Initialize database schema and tables.
    This function handles all table creation and migrations.
    """
    from app.models.schema import SchemaManager
    schema_manager = SchemaManager()
    schema_manager.initialize_all_tables()

