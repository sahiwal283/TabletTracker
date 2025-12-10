"""
Database initialization and schema management

As of v2.0, database schema is managed by Alembic migrations.
The init_db() function is kept for backwards compatibility but is now a no-op.
Use `alembic upgrade head` to initialize or migrate the database.
"""
import sqlite3
from config import Config


def init_db():
    """
    Initialize database (no-op in v2.0+)
    
    As of v2.0, database schema is managed by Alembic migrations.
    The database should be initialized using: alembic upgrade head
    
    This function is kept for backwards compatibility with existing code.
    """
    # Check if database file exists
    import os
    if not os.path.exists(Config.DATABASE_PATH):
        print(f"WARNING: Database file not found at {Config.DATABASE_PATH}")
        print("Run 'alembic upgrade head' to initialize the database")
    
    # Database exists - Alembic handles schema
    pass


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
        print(f"Error checking database: {e}")
        return False

