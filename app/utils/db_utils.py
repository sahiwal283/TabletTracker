"""
Database utility functions for blueprints to import.

This module provides:
- Context managers for safe database connections
- Query execution helpers
- Repository pattern classes for common entities
"""
import sqlite3
import traceback
from contextlib import contextmanager
from typing import Optional, Callable, Any, List, Dict, Tuple, Iterator
from functools import wraps
from config import Config


def get_db() -> sqlite3.Connection:
    """Get a database connection with Row factory"""
    conn = sqlite3.connect(Config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_connection(read_only: bool = False) -> Iterator[sqlite3.Connection]:
    """
    Context manager for database connections.
    Ensures proper connection cleanup even on errors.
    
    Args:
        read_only: If True, don't auto-commit (for read-only operations)
    
    Usage:
        with db_connection() as conn:
            result = conn.execute('SELECT * FROM table')
            # Connection automatically closed when exiting context
    """
    conn = None
    try:
        conn = get_db()
        yield conn
        if not read_only:
            conn.commit()  # Auto-commit on success for write operations
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
def db_transaction() -> Iterator[sqlite3.Connection]:
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


@contextmanager
def db_read_only() -> Iterator[sqlite3.Connection]:
    """
    Context manager for read-only database operations.
    No commit is performed, connection is automatically closed.
    
    Usage:
        with db_read_only() as conn:
            result = conn.execute('SELECT * FROM table')
    """
    conn = None
    try:
        conn = get_db()
        yield conn
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


def db_query(query: str, params: Optional[Tuple] = None, fetch_one: bool = False) -> Any:
    """
    Execute a database query and return results.
    
    Args:
        query: SQL query string
        params: Query parameters tuple/list
        fetch_one: If True, return fetchone(), else fetchall()
    
    Returns:
        Query results (Row object, list of Row objects, or None)
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
        import logging
        logging.error(f"Database query error: {e}")
        traceback.print_exc()
        raise
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


def db_execute(query: str, params: Optional[Tuple] = (), commit: bool = True) -> int:
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
        import logging
        logging.error(f"Database execute error: {e}")
        traceback.print_exc()
        raise
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


def db_execute_many(queries: List[Tuple[str, Optional[Tuple]]], commit: bool = True) -> int:
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
            if params:
                cursor = conn.execute(query, params)
            else:
                cursor = conn.execute(query)
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
        import logging
        logging.error(f"Database execute_many error: {e}")
        traceback.print_exc()
        raise
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


# Repository Pattern Classes

class PurchaseOrderRepository:
    """Repository for purchase order database operations."""
    
    @staticmethod
    def get_by_id(conn: sqlite3.Connection, po_id: int) -> Optional[Dict[str, Any]]:
        """Get purchase order by ID."""
        row = conn.execute('''
            SELECT * FROM purchase_orders WHERE id = ?
        ''', (po_id,)).fetchone()
        return dict(row) if row else None
    
    @staticmethod
    def get_by_po_number(conn: sqlite3.Connection, po_number: str) -> Optional[Dict[str, Any]]:
        """Get purchase order by PO number."""
        row = conn.execute('''
            SELECT * FROM purchase_orders WHERE po_number = ?
        ''', (po_number,)).fetchone()
        return dict(row) if row else None
    
    @staticmethod
    def get_open_pos(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
        """Get all open purchase orders."""
        rows = conn.execute('''
            SELECT * FROM purchase_orders 
            WHERE closed = FALSE 
            AND COALESCE(internal_status, '') != 'Cancelled'
            ORDER BY po_number DESC
        ''').fetchall()
        return [dict(row) for row in rows]


class SubmissionRepository:
    """Repository for submission database operations."""
    
    @staticmethod
    def get_by_id(conn: sqlite3.Connection, submission_id: int) -> Optional[Dict[str, Any]]:
        """Get submission by ID."""
        row = conn.execute('''
            SELECT * FROM warehouse_submissions WHERE id = ?
        ''', (submission_id,)).fetchone()
        return dict(row) if row else None
    
    @staticmethod
    def get_by_bag_id(conn: sqlite3.Connection, bag_id: int) -> List[Dict[str, Any]]:
        """Get all submissions for a bag."""
        rows = conn.execute('''
            SELECT * FROM warehouse_submissions 
            WHERE bag_id = ? 
            ORDER BY created_at DESC
        ''', (bag_id,)).fetchall()
        return [dict(row) for row in rows]
    
    @staticmethod
    def get_by_po_id(conn: sqlite3.Connection, po_id: int) -> List[Dict[str, Any]]:
        """Get all submissions for a purchase order."""
        rows = conn.execute('''
            SELECT * FROM warehouse_submissions 
            WHERE assigned_po_id = ? 
            ORDER BY created_at DESC
        ''', (po_id,)).fetchall()
        return [dict(row) for row in rows]


class BagRepository:
    """Repository for bag database operations."""
    
    @staticmethod
    def get_by_id(conn: sqlite3.Connection, bag_id: int) -> Optional[Dict[str, Any]]:
        """Get bag by ID."""
        row = conn.execute('''
            SELECT b.*, sb.box_number, r.po_id
            FROM bags b
            JOIN small_boxes sb ON b.small_box_id = sb.id
            JOIN receiving r ON sb.receiving_id = r.id
            WHERE b.id = ?
        ''', (bag_id,)).fetchone()
        return dict(row) if row else None
    
    @staticmethod
    def get_by_receiving_id(conn: sqlite3.Connection, receiving_id: int) -> List[Dict[str, Any]]:
        """Get all bags for a receiving."""
        rows = conn.execute('''
            SELECT b.*, sb.box_number, tt.tablet_type_name, tt.inventory_item_id
            FROM bags b
            JOIN small_boxes sb ON b.small_box_id = sb.id
            JOIN tablet_types tt ON b.tablet_type_id = tt.id
            WHERE sb.receiving_id = ?
            ORDER BY sb.box_number, b.bag_number
        ''', (receiving_id,)).fetchall()
        return [dict(row) for row in rows]


class ReceivingRepository:
    """Repository for receiving database operations."""
    
    @staticmethod
    def get_by_id(conn: sqlite3.Connection, receiving_id: int) -> Optional[Dict[str, Any]]:
        """Get receiving by ID."""
        row = conn.execute('''
            SELECT r.*, po.po_number, po.id as po_id
            FROM receiving r
            LEFT JOIN purchase_orders po ON r.po_id = po.id
            WHERE r.id = ?
        ''', (receiving_id,)).fetchone()
        return dict(row) if row else None
    
    @staticmethod
    def get_by_po_id(conn: sqlite3.Connection, po_id: int) -> List[Dict[str, Any]]:
        """Get all receivings for a purchase order."""
        rows = conn.execute('''
            SELECT r.*, po.po_number
            FROM receiving r
            LEFT JOIN purchase_orders po ON r.po_id = po.id
            WHERE r.po_id = ?
            ORDER BY r.received_date DESC
        ''', (po_id,)).fetchall()
        return [dict(row) for row in rows]

