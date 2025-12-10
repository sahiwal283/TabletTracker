#!/usr/bin/env python3
"""
Quick fix: Add needs_review column to warehouse_submissions table
Run this on PythonAnywhere to fix the "no such column: needs_review" error
"""
import sqlite3

def add_needs_review_column():
    conn = None
    try:
        conn = sqlite3.connect('tablet_counter.db')
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # Check if column already exists
        c.execute('PRAGMA table_info(warehouse_submissions)')
        columns = [row[1] for row in c.fetchall()]
        
        if 'needs_review' in columns:
            print("✅ needs_review column already exists!")
            return
        
        # Add the column
        print("Adding needs_review column...")
        c.execute('ALTER TABLE warehouse_submissions ADD COLUMN needs_review BOOLEAN DEFAULT FALSE')
        
        # Flag unassigned submissions for review
        print("Flagging unassigned legacy submissions...")
        c.execute('''
            UPDATE warehouse_submissions 
            SET needs_review = 1 
            WHERE assigned_po_id IS NULL
            AND bag_id IS NULL
        ''')
        
        conn.commit()
        print("✅ Successfully added needs_review column!")
        print("✅ Database migration complete!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    add_needs_review_column()

