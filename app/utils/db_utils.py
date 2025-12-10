"""
Database utility functions for blueprints to import
"""
import sqlite3
from config import Config


def get_db():
    """Get a database connection with Row factory"""
    conn = sqlite3.connect(Config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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

