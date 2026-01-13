"""
Database initialization and schema management

As of v2.0, database schema is managed by Alembic migrations.
As of v2.24, MigrationRunner also runs on init_db() for column additions.
"""
import sqlite3
import logging
from config import Config

logger = logging.getLogger(__name__)

# Track if migrations have run this session to avoid running repeatedly
_migrations_run = False


def init_db():
    """
    Initialize database and run migrations.
    
    Runs MigrationRunner to ensure all columns exist.
    Safe to call multiple times - migrations only run once per session.
    """
    global _migrations_run
    
    if _migrations_run:
        return  # Already ran migrations this session
    
    # Check if database file exists
    import os
    if not os.path.exists(Config.DATABASE_PATH):
        logger.warning(f"Database file not found at {Config.DATABASE_PATH}")
        return
    
    # Run migrations to ensure columns exist
    try:
        from app.models.migrations import MigrationRunner
        conn = sqlite3.connect(Config.DATABASE_PATH)
        cursor = conn.cursor()
        
        runner = MigrationRunner(cursor)
        runner.run_all()
        
        conn.commit()
        conn.close()
        _migrations_run = True
        logger.info("Database migrations completed successfully")
    except Exception as e:
        logger.warning(f"Could not run migrations: {e}")


def check_db_initialized():
    """Check if database is properly initialized"""
    try:
        conn = sqlite3.connect(Config.DATABASE_PATH)
        cursor = conn.cursor()
        
        # Check if alembic_version table exists (indicates Alembic is set up)
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='alembic_version'
        """)
        alembic_table = cursor.fetchone()
        
        conn.close()
        return alembic_table is not None
    except Exception as e:
        logger.error(f"Error checking database: {e}")
        return False

