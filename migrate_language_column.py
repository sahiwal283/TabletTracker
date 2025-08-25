#!/usr/bin/env python3
"""
Add preferred_language column to employees table
Run this script to ensure the column exists
"""

import sqlite3
import sys

def add_language_column():
    """Add preferred_language column if it doesn't exist"""
    try:
        conn = sqlite3.connect('tablet_counter.db')
        conn.row_factory = sqlite3.Row
        
        # Check if column exists
        try:
            conn.execute('SELECT preferred_language FROM employees LIMIT 1').fetchone()
            print("✅ preferred_language column already exists!")
        except sqlite3.OperationalError:
            print("🔧 Adding preferred_language column...")
            conn.execute('ALTER TABLE employees ADD COLUMN preferred_language TEXT DEFAULT "en"')
            conn.commit()
            print("✅ preferred_language column added successfully!")
        
        # Show current employees with language settings
        employees = conn.execute('''
            SELECT id, username, full_name, preferred_language 
            FROM employees 
            ORDER BY username
        ''').fetchall()
        
        print(f"\n📊 Current employees ({len(employees)} total):")
        for emp in employees:
            lang = emp['preferred_language'] or 'en'
            lang_name = 'English' if lang == 'en' else 'Español'
            print(f"  - {emp['username']} ({emp['full_name']}): {lang_name}")
        
        conn.close()
        print("\n🎉 Migration complete!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    add_language_column()
