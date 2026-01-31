"""
Add status column to receiving table for draft/published workflow

This migration adds a status field to receiving table to support:
- Draft receives: Work in progress, not available for production
- Published receives: Live and available for production submissions
"""
import sqlite3
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config

def add_receive_status_column():
    """Add status column to receiving table"""
    db_path = Config.DATABASE_PATH
    
    print(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        # Check if column already exists
        cursor.execute("PRAGMA table_info(receiving)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'status' in columns:
            print("✓ Status column already exists in receiving table")
            return
        
        # Add status column (default 'published' for backward compatibility)
        print("Adding status column to receiving table...")
        cursor.execute('''
            ALTER TABLE receiving 
            ADD COLUMN status TEXT DEFAULT 'published'
        ''')
        
        conn.commit()
        print("✓ Successfully added status column to receiving table")
        
        # Show table structure
        cursor.execute("PRAGMA table_info(receiving)")
        print("\nReceiving table structure:")
        for col in cursor.fetchall():
            print(f"  - {col[1]} ({col[2]})")
        
    except Exception as e:
        print(f"✗ Error: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == '__main__':
    add_receive_status_column()
