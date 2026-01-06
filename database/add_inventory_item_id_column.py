#!/usr/bin/env python3
"""
Add inventory_item_id column to warehouse_submissions table if missing.
Run this on PythonAnywhere if you're getting "syntax error near 'inventory_item_id'"
"""

import sqlite3
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config

def add_inventory_item_id_column():
    """Add inventory_item_id column to warehouse_submissions"""
    
    db_path = Config.DATABASE_PATH
    print(f"📊 Connecting to database: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if column exists
        cursor.execute("PRAGMA table_info(warehouse_submissions)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'inventory_item_id' in columns:
            print("✅ Column inventory_item_id already exists - nothing to do!")
            return True
        
        print("🔄 Adding inventory_item_id column...")
        
        # Add the column
        cursor.execute('ALTER TABLE warehouse_submissions ADD COLUMN inventory_item_id TEXT')
        
        print("✅ Column added successfully")
        
        # Backfill existing submissions
        print("🔄 Backfilling existing submissions...")
        
        cursor.execute('''
            UPDATE warehouse_submissions 
            SET inventory_item_id = (
                SELECT tt.inventory_item_id 
                FROM product_details pd
                JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                WHERE pd.product_name = warehouse_submissions.product_name
            )
            WHERE inventory_item_id IS NULL
        ''')
        
        rows_updated = cursor.rowcount
        conn.commit()
        
        print(f"✅ Backfilled {rows_updated} existing submissions")
        print("\n✅ Migration complete!")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

if __name__ == '__main__':
    add_inventory_item_id_column()

