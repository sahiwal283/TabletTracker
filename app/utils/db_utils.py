"""
Database utility functions for consistent connection management and common queries.
"""
import sqlite3
import traceback
from functools import wraps
from typing import Optional, Callable, Any, Dict, List
from contextlib import contextmanager


def get_db():
    """Get a database connection with Row factory."""
    conn = sqlite3.connect('tablet_counter.db')
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_connection():
    """
    Context manager for database connections with automatic cleanup.
    
    Usage:
        with db_connection() as conn:
            result = conn.execute('SELECT * FROM table').fetchall()
    """
    conn = None
    try:
        conn = get_db()
        yield conn
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


def db_query(query: str, params: tuple = (), fetch_one: bool = False, fetch_all: bool = True):
    """
    Execute a database query with automatic connection management.
    
    Args:
        query: SQL query string
        params: Query parameters tuple
        fetch_one: If True, return single row
        fetch_all: If True, return all rows (default)
    
    Returns:
        Single row dict, list of row dicts, or None
    """
    conn = None
    try:
        conn = get_db()
        cursor = conn.execute(query, params)
        
        if fetch_one:
            row = cursor.fetchone()
            return dict(row) if row else None
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows] if rows else []
    except Exception as e:
        print(f"Database query error: {str(e)}")
        traceback.print_exc()
        raise
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


def db_execute(query: str, params: tuple = (), commit: bool = True):
    """
    Execute a database write operation with automatic connection management.
    
    Args:
        query: SQL query string
        params: Query parameters tuple
        commit: Whether to commit the transaction (default: True)
    
    Returns:
        Number of affected rows
    """
    conn = None
    try:
        conn = get_db()
        cursor = conn.execute(query, params)
        if commit:
            conn.commit()
        return cursor.rowcount
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        print(f"Database execute error: {str(e)}")
        traceback.print_exc()
        raise
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


def db_execute_many(queries: List[tuple], commit: bool = True):
    """
    Execute multiple database operations in a transaction.
    
    Args:
        queries: List of (query, params) tuples
        commit: Whether to commit the transaction (default: True)
    
    Returns:
        Total number of affected rows
    """
    conn = None
    try:
        conn = get_db()
        total_rows = 0
        for query, params in queries:
            cursor = conn.execute(query, params)
            total_rows += cursor.rowcount
        
        if commit:
            conn.commit()
        return total_rows
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
        print(f"Database execute_many error: {str(e)}")
        traceback.print_exc()
        raise
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


def safe_db_operation(operation: Callable, default_return: Any = None, error_message: str = None):
    """
    Safely execute a database operation with error handling.
    
    Args:
        operation: Function that performs database operation
        default_return: Value to return on error
        error_message: Custom error message
    
    Returns:
        Result of operation or default_return on error
    """
    try:
        return operation()
    except Exception as e:
        print(f"{error_message or 'Database operation error'}: {str(e)}")
        traceback.print_exc()
        return default_return

