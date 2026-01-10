#!/usr/bin/env python3
"""
Add receipt_number column to warehouse_submissions table

This migration adds the receipt_number column for tracking receipt numbers
on submissions (packaged and machine count forms).
"""

import sqlite3
import sys
import os

# Add parent directory to path to import config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config import Config
    DB_PATH = Config.DATABASE_PATH
except ImportError:
    # Fallback if config not available
    if os.path.exists('database/tablet_counter.db'):
        DB_PATH = 'database/tablet_counter.db'
    elif os.path.exists('tablet_counter.db'):
        DB_PATH = 'tablet_counter.db'
    else:
        print("❌ Error: Could not find database file")
        sys.exit(1)

def add_receipt_number_column():
    """Add receipt_number column to warehouse_submissions"""
    
    print("=" * 80)
    print("ADDING receipt_number COLUMN")
    print("=" * 80)
    print(f"Database: {DB_PATH}")
    print()
    
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found at: {DB_PATH}")
        return False
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    try:
        # Check if column already exists
        c.execute("PRAGMA table_info(warehouse_submissions)")
        existing_cols = [row[1] for row in c.fetchall()]
        
        if 'receipt_number' in existing_cols:
            print("✓ Column 'receipt_number' already exists")
            conn.close()
            return True
        else:
            print("➕ Adding column 'receipt_number'...")
            c.execute('ALTER TABLE warehouse_submissions ADD COLUMN receipt_number TEXT')
            conn.commit()
            print("✓ Column added successfully")
        
        # Verify
        print()
        print("=" * 80)
        print("VERIFICATION")
        print("=" * 80)
        c.execute("PRAGMA table_info(warehouse_submissions)")
        cols = [row[1] for row in c.fetchall()]
        if 'receipt_number' in cols:
            print("✅ receipt_number column exists in warehouse_submissions")
            # Get column type
            c.execute("PRAGMA table_info(warehouse_submissions)")
            for col in c.fetchall():
                if col[1] == 'receipt_number':
                    print(f"   Type: {col[2]}")
        else:
            print("❌ Column not found after adding")
            conn.close()
            return False
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        conn.close()
        return False

if __name__ == '__main__':
    success = add_receipt_number_column()
    if success:
        print()
        print("=" * 80)
        print("✅ MIGRATION COMPLETE")
        print("=" * 80)
    else:
        print()
        print("=" * 80)
        print("❌ MIGRATION FAILED")
        print("=" * 80)
        exit(1)










