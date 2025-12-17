"""
Database utility functions for blueprints to import
"""
import sqlite3
from contextlib import contextmanager
from typing import Optional
from config import Config


def get_db():
    """Get a database connection with Row factory"""
    conn = sqlite3.connect(Config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_connection():
    """
    Context manager for database connections.
    Ensures proper connection cleanup even on errors.
    
    Usage:
        with db_connection() as conn:
            result = conn.execute('SELECT * FROM table')
            # Connection automatically closed when exiting context
    """
    conn = None
    try:
        conn = get_db()
        yield conn
        conn.commit()  # Auto-commit on success
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        raise  # Re-raise the exception
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


@contextmanager
def db_transaction():
    """
    Context manager for database transactions.
    Automatically commits on success, rolls back on failure.
    
    Usage:
        with db_transaction() as conn:
            conn.execute('INSERT INTO table VALUES (?)', (value,))
            # Auto-commit on success, auto-rollback on exception
    """
    conn = None
    try:
        conn = get_db()
        yield conn
        conn.commit()
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        raise
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


def db_query(query, params=None, fetch_one=False):
    """Execute a database query and return results
    
    Args:
        query: SQL query string
        params: Query parameters tuple/list
        fetch_one: If True, return fetchone(), else fetchall()
    
    Returns:
        Query results or None
    """
    conn = None
    try:
        conn = get_db()
        if params:
            result = conn.execute(query, params)
        else:
            result = conn.execute(query)
        
        if fetch_one:
            return result.fetchone()
        return result.fetchall()
    except Exception as e:
        print(f"Database query error: {e}")
        raise
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

