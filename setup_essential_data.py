#!/usr/bin/env python3
"""
Setup essential data for TabletTracker to work properly
Creates admin user and basic structure - NO fake data
"""

import sqlite3
import hashlib
from datetime import datetime

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def setup_essential_data():
    """Setup only essential data needed for website to function"""
    
    conn = sqlite3.connect('tablettracker.db')
    cursor = conn.cursor()
    
    try:
        print("🔧 Setting up essential data for TabletTracker...")
        
        # 1. Create admin user so you can log in
        admin_password_hash = hash_password('admin123')  # Change this password!
        
        cursor.execute('''
            INSERT OR IGNORE INTO employees (username, full_name, password_hash) 
            VALUES (?, ?, ?)
        ''', ('admin', 'Administrator', admin_password_hash))
        
        print("✅ Created admin user (username: admin, password: admin123)")
        print("⚠️  CHANGE THE ADMIN PASSWORD IMMEDIATELY!")
        
        # 2. Create a basic tablet type so forms don't crash
        cursor.execute('''
            INSERT OR IGNORE INTO tablet_types (tablet_type_name, inventory_item_id) 
            VALUES (?, ?)
        ''', ('Standard Tablet', 'STANDARD_001'))
        
        print("✅ Created basic tablet type")
        
        # 3. Create a basic product so warehouse forms work
        tablet_type_id = cursor.execute(
            'SELECT id FROM tablet_types WHERE tablet_type_name = ?', 
            ('Standard Tablet',)
        ).fetchone()[0]
        
        cursor.execute('''
            INSERT OR IGNORE INTO product_details 
            (product_name, tablet_type_id, packages_per_display, tablets_per_package) 
            VALUES (?, ?, ?, ?)
        ''', ('Basic Display', tablet_type_id, 24, 1))
        
        print("✅ Created basic product")
        
        conn.commit()
        conn.close()
        
        print("\n🎉 ESSENTIAL SETUP COMPLETE!")
        print("\n🚀 Your website is now functional:")
        print("   ✅ Admin Login: username 'admin', password 'admin123'")
        print("   ✅ Dashboard will load (empty but functional)")
        print("   ✅ Warehouse forms will work")
        print("   ✅ Count forms will work")
        print("   ✅ Admin panel will work")
        
        print("\n📋 NEXT STEPS:")
        print("   1. Log in as admin and CHANGE THE PASSWORD")
        print("   2. Add your real employees in Admin panel")
        print("   3. Add your real tablet types and products")
        print("   4. Start entering real data")
        
        print("\n⚠️  SECURITY: Change admin password immediately!")
        
        return True
        
    except Exception as e:
        print(f"❌ Error setting up essential data: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚨 SETTING UP ESSENTIAL DATA")
    print("=" * 40)
    print("This creates the minimum data needed for the website to work")
    print()
    
    if setup_essential_data():
        print("\n✅ SUCCESS! Your website is now ready to use!")
        print("🔐 Login with admin/admin123 and start setting up your real data!")
    else:
        print("\n❌ SETUP FAILED!")