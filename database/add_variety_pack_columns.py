#!/usr/bin/env python3
"""
Add variety pack columns to tablet_types table
Run this on PythonAnywhere if the migration hasn't run automatically
"""
import sys
import os
import sqlite3

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config

def add_variety_pack_columns():
    """Add variety pack columns to tablet_types table"""
    db_path = Config.DATABASE_PATH
    
    print("=" * 80)
    print("ADDING VARIETY PACK COLUMNS TO tablet_types TABLE")
    print("=" * 80)
    print()
    
    if not os.path.exists(db_path):
        print(f"❌ Database not found at: {db_path}")
        return False
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check which columns exist
        cursor.execute("PRAGMA table_info(tablet_types)")
        existing_cols = [row[1] for row in cursor.fetchall()]
        print(f"Existing columns: {', '.join(existing_cols)}")
        print()
        
        # Add columns if they don't exist
        columns_to_add = [
            ('is_variety_pack', 'BOOLEAN DEFAULT 0'),
            ('tablets_per_bottle', 'INTEGER'),
            ('bottles_per_pack', 'INTEGER'),
            ('variety_pack_contents', 'TEXT')
        ]
        
        added_count = 0
        for col_name, col_def in columns_to_add:
            if col_name not in existing_cols:
                try:
                    cursor.execute(f'ALTER TABLE tablet_types ADD COLUMN {col_name} {col_def}')
                    print(f"✅ Added column: {col_name}")
                    added_count += 1
                except Exception as e:
                    print(f"❌ Failed to add {col_name}: {e}")
            else:
                print(f"⏭️  Column {col_name} already exists, skipping")
        
        conn.commit()
        print()
        print("=" * 80)
        if added_count > 0:
            print(f"✅ SUCCESS: Added {added_count} column(s)")
        else:
            print("✅ All columns already exist")
        print("=" * 80)
        print()
        print("Next steps:")
        print("1. Clear Python cache: find . -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true")
        print("2. Reload web app")
        print("=" * 80)
        
        return True
        
    except Exception as e:
        print()
        print("=" * 80)
        print("❌ ERROR")
        print("=" * 80)
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        return False
    finally:
        conn.close()

if __name__ == '__main__':
    add_variety_pack_columns()

