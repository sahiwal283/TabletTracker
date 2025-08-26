#!/usr/bin/env python3
"""
Check actual schema and fix it properly
"""

import sqlite3

def check_and_fix():
    """Check what exists and fix accordingly"""
    
    conn = sqlite3.connect('tablettracker.db')
    cursor = conn.cursor()
    
    try:
        print("🔍 CHECKING ACTUAL SCHEMA...")
        
        # Check products table
        cursor.execute("PRAGMA table_info(products)")
        prod_columns = [row[1] for row in cursor.fetchall()]
        print(f"📦 Products columns: {prod_columns}")
        
        # Check employees table  
        cursor.execute("PRAGMA table_info(employees)")
        emp_columns = [row[1] for row in cursor.fetchall()]
        print(f"👥 Employees columns: {emp_columns}")
        
        # Check tablet_types table
        cursor.execute("PRAGMA table_info(tablet_types)")
        tt_columns = [row[1] for row in cursor.fetchall()]
        print(f"💊 Tablet_types columns: {tt_columns}")
        
        print("\n🔧 CREATING DATA BASED ON ACTUAL SCHEMA...")
        
        # Create employee
        if 'name' in emp_columns:
            cursor.execute('INSERT OR IGNORE INTO employees (name) VALUES (?)', ('Admin',))
            print("✅ Created employee")
        
        # Create tablet type
        if 'name' in tt_columns:
            cursor.execute('INSERT OR IGNORE INTO tablet_types (name) VALUES (?)', ('Standard',))
            print("✅ Created tablet type")
        
        # Create product with only columns that exist
        if 'name' in prod_columns:
            if 'bottles_per_display' in prod_columns:
                cursor.execute('INSERT OR IGNORE INTO products (name, bottles_per_display) VALUES (?, ?)', ('Basic Product', 24))
            else:
                cursor.execute('INSERT OR IGNORE INTO products (name) VALUES (?)', ('Basic Product',))
            print("✅ Created product")
        
        conn.commit()
        conn.close()
        
        print("\n🎉 DONE! Check your website now!")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    check_and_fix()