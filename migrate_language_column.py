#!/usr/bin/env python3
"""
Add preferred_language column to employees table
This migration enables per-employee language preferences
"""

import sqlite3
import os

def migrate_language_column():
    """Add preferred_language column to employees table"""
    db_path = 'tablet_counter.db'
    
    if not os.path.exists(db_path):
        print(f"❌ Database file {db_path} not found!")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if preferred_language column exists
        cursor.execute("PRAGMA table_info(employees)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'preferred_language' not in columns:
            print("🔧 Adding preferred_language column to employees table...")
            cursor.execute('ALTER TABLE employees ADD COLUMN preferred_language TEXT DEFAULT "en"')
            print("✅ Added preferred_language column")
        else:
            print("✅ preferred_language column already exists")
        
        conn.commit()
        conn.close()
        print("✅ Language column migration completed!")
        return True
        
    except sqlite3.Error as e:
        print(f"❌ Database error: {e}")
        return False
    except Exception as e:
        print(f"❌ An unexpected error occurred: {e}")
        return False

if __name__ == "__main__":
    migrate_language_column()
