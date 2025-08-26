#!/usr/bin/env python3
"""
Fix PythonAnywhere setup by checking actual schema and adapting
"""

import sqlite3
import hashlib
from datetime import datetime

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_table_columns(cursor, table_name):
    """Get column names for a table"""
    cursor.execute(f"PRAGMA table_info({table_name})")
    return [row[1] for row in cursor.fetchall()]

def fix_pythonanywhere_setup():
    """Setup essential data by adapting to actual database schema"""
    
    conn = sqlite3.connect('tablettracker.db')
    cursor = conn.cursor()
    
    try:
        print("🔧 Checking actual database schema on PythonAnywhere...")
        
        # Check what tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        print(f"📋 Found tables: {tables}")
        
        # Check employees table structure
        if 'employees' in tables:
            emp_columns = get_table_columns(cursor, 'employees')
            print(f"👥 Employees table columns: {emp_columns}")
            
            # Create admin user based on actual schema
            admin_password_hash = hash_password('admin123')
            
            if 'username' in emp_columns and 'full_name' in emp_columns:
                # New schema
                cursor.execute('''
                    INSERT OR IGNORE INTO employees (username, full_name, password_hash) 
                    VALUES (?, ?, ?)
                ''', ('admin', 'Administrator', admin_password_hash))
                print("✅ Created admin user (new schema)")
            elif 'name' in emp_columns:
                # Old schema
                cursor.execute('''
                    INSERT OR IGNORE INTO employees (name, password_hash, role) 
                    VALUES (?, ?, ?)
                ''', ('Administrator', admin_password_hash, 'admin'))
                print("✅ Created admin user (old schema)")
            else:
                # Very basic schema
                cursor.execute('''
                    INSERT OR IGNORE INTO employees (name) 
                    VALUES (?)
                ''', ('Administrator',))
                print("✅ Created basic admin user")
        
        # Check tablet_types table
        if 'tablet_types' in tables:
            tt_columns = get_table_columns(cursor, 'tablet_types')
            print(f"💊 Tablet_types columns: {tt_columns}")
            
            if 'tablet_type_name' in tt_columns:
                cursor.execute('''
                    INSERT OR IGNORE INTO tablet_types (tablet_type_name, inventory_item_id) 
                    VALUES (?, ?)
                ''', ('Standard Tablet', 'STANDARD_001'))
                print("✅ Created tablet type (tablet_type_name)")
            elif 'name' in tt_columns:
                cursor.execute('''
                    INSERT OR IGNORE INTO tablet_types (name) 
                    VALUES (?)
                ''', ('Standard Tablet',))
                print("✅ Created tablet type (name)")
        
        # Check products/product_details table
        products_table = None
        if 'product_details' in tables:
            products_table = 'product_details'
        elif 'products' in tables:
            products_table = 'products'
            
        if products_table:
            prod_columns = get_table_columns(cursor, products_table)
            print(f"📦 {products_table} columns: {prod_columns}")
            
            # Get tablet type ID
            tablet_type_id = 1  # Default
            try:
                if 'tablet_types' in tables:
                    result = cursor.execute('SELECT id FROM tablet_types LIMIT 1').fetchone()
                    if result:
                        tablet_type_id = result[0]
            except:
                pass
            
            if 'product_name' in prod_columns:
                cursor.execute(f'''
                    INSERT OR IGNORE INTO {products_table} 
                    (product_name, tablet_type_id, packages_per_display, tablets_per_package) 
                    VALUES (?, ?, ?, ?)
                ''', ('Basic Display', tablet_type_id, 24, 1))
                print("✅ Created product (product_name)")
            elif 'name' in prod_columns:
                cursor.execute(f'''
                    INSERT OR IGNORE INTO {products_table} (name, tablet_type_id) 
                    VALUES (?, ?)
                ''', ('Basic Display', tablet_type_id))
                print("✅ Created product (name)")
        
        conn.commit()
        conn.close()
        
        print("\n🎉 SETUP COMPLETE!")
        print("\n🚀 Your website should now work:")
        print("   ✅ Login with admin/admin123 (if password auth exists)")
        print("   ✅ Dashboard will load")
        print("   ✅ Forms will work")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚨 FIXING PYTHONANYWHERE SETUP")
    print("=" * 40)
    
    if fix_pythonanywhere_setup():
        print("\n✅ SUCCESS! Website should work now!")
    else:
        print("\n❌ FAILED!")