#!/usr/bin/env python3
"""
FINAL FIX - Work with actual PythonAnywhere schema
"""

import sqlite3

def final_fix():
    """Final fix using actual schema found"""
    
    conn = sqlite3.connect('tablettracker.db')
    cursor = conn.cursor()
    
    try:
        print("🔧 Final fix for actual schema...")
        
        # 1. Add admin employee (no password needed based on schema)
        cursor.execute('''
            INSERT OR IGNORE INTO employees (name, role) 
            VALUES (?, ?)
        ''', ('Administrator', 'admin'))
        print("✅ Created admin employee")
        
        # 2. Add basic tablet type
        cursor.execute('''
            INSERT OR IGNORE INTO tablet_types (name) 
            VALUES (?)
        ''', ('Standard Tablet',))
        print("✅ Created tablet type")
        
        # 3. Get tablet type ID for product
        tablet_type_id = cursor.execute('SELECT id FROM tablet_types LIMIT 1').fetchone()[0]
        
        # 4. Add basic product
        cursor.execute('''
            INSERT OR IGNORE INTO products (name, tablet_type_id, bottles_per_display) 
            VALUES (?, ?, ?)
        ''', ('Basic Display', tablet_type_id, 24))
        print("✅ Created product")
        
        conn.commit()
        conn.close()
        
        print("\n🎉 FINAL FIX COMPLETE!")
        print("✅ Your website pages should now show content!")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚨 RUNNING FINAL FIX")
    print("=" * 30)
    
    if final_fix():
        print("\n✅ SUCCESS! Refresh your browser!")
    else:
        print("\n❌ FAILED!")