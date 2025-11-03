#!/usr/bin/env python3
"""
Quick database schema fix for missing po_assignment_verified column
Run this on PythonAnywhere to fix the schema mismatch
"""
import sqlite3
import sys

def fix_schema():
    """Add missing po_assignment_verified column if it doesn't exist"""
    try:
        conn = sqlite3.connect('tablet_counter.db')
        cursor = conn.cursor()
        
        # Check if column exists
        cursor.execute("PRAGMA table_info(warehouse_submissions)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'po_assignment_verified' not in columns:
            print("Adding missing po_assignment_verified column...")
            cursor.execute('''
                ALTER TABLE warehouse_submissions 
                ADD COLUMN po_assignment_verified INTEGER DEFAULT 0
            ''')
            conn.commit()
            print("✓ Column added successfully!")
        else:
            print("✓ Column already exists, no changes needed")
        
        # Verify the fix
        cursor.execute("SELECT COUNT(*) FROM warehouse_submissions")
        count = cursor.fetchone()[0]
        print(f"✓ Database verified: {count} submissions found")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"✗ Error: {e}")
        return False

if __name__ == '__main__':
    success = fix_schema()
    sys.exit(0 if success else 1)

