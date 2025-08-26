#!/usr/bin/env python3
"""
Copy the exact working database from local to replace the broken one
"""

import sqlite3
import os
from datetime import datetime

def copy_working_database():
    """Copy working database structure and create minimal working data"""
    
    # First, let's create a working database with the exact structure we know works
    source_db = 'tablet_counter.db'  # This one works locally
    target_db = 'tablettracker.db'   # This is what the app needs
    
    if not os.path.exists(source_db):
        print(f"❌ Source database {source_db} not found")
        return False
    
    try:
        # Backup existing broken database
        if os.path.exists(target_db):
            backup_name = f'broken_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
            os.rename(target_db, backup_name)
            print(f"🔄 Backed up broken database to {backup_name}")
        
        # Copy working database
        import shutil
        shutil.copy2(source_db, target_db)
        print(f"✅ Copied working database from {source_db} to {target_db}")
        
        # Now add minimal data to make it work
        conn = sqlite3.connect(target_db)
        cursor = conn.cursor()
        
        # Add admin employee
        cursor.execute('''
            INSERT OR IGNORE INTO employees (username, full_name, password_hash, is_active) 
            VALUES (?, ?, ?, ?)
        ''', ('admin', 'Administrator', 'admin123_hash', True))
        
        # Add basic tablet type
        cursor.execute('''
            INSERT OR IGNORE INTO tablet_types (tablet_type_name, inventory_item_id) 
            VALUES (?, ?)
        ''', ('Standard Tablet', 'STD001'))
        
        # Get tablet type ID
        tablet_type_id = cursor.execute('SELECT id FROM tablet_types LIMIT 1').fetchone()[0]
        
        # Add basic product
        cursor.execute('''
            INSERT OR IGNORE INTO product_details 
            (product_name, tablet_type_id, packages_per_display, tablets_per_package) 
            VALUES (?, ?, ?, ?)
        ''', ('Basic Display', tablet_type_id, 24, 1))
        
        conn.commit()
        conn.close()
        
        print("✅ Added minimal working data")
        print("\n🎉 DATABASE READY!")
        print("Your website should now work with proper structure and data")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚨 COPYING WORKING DATABASE")
    print("=" * 40)
    
    if copy_working_database():
        print("\n✅ SUCCESS! Website should work now!")
    else:
        print("\n❌ FAILED!")