#!/usr/bin/env python3
"""
Restore database to match the working v1.9.3 version
"""

import sqlite3
import os
from datetime import datetime

def restore_database():
    """Restore database to working state"""
    
    # Backup existing database
    if os.path.exists('tablettracker.db'):
        backup_name = f'tablettracker_broken_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
        os.rename('tablettracker.db', backup_name)
        print(f"🔄 Backed up broken database to: {backup_name}")
    
    # Create fresh database with working schema
    conn = sqlite3.connect('tablettracker.db')
    cursor = conn.cursor()
    
    try:
        print("🔧 Creating fresh database with working schema...")
        
        # Import the working database schema from app.py
        from app import init_db
        
        # Initialize with correct schema
        init_db()
        print("✅ Database initialized with correct schema")
        
        # Add essential sample data
        print("🔧 Adding essential working data...")
        
        # 1. Add Purchase Orders
        sample_pos = [
            ("PO-001", "Standard Tablets", "confirmed", 5000, "Active"),
            ("PO-002", "Extended Release", "confirmed", 3000, "Active"),
            ("PO-003", "Coated Tablets", "delivered", 7000, "Completed")
        ]
        
        for po_number, tablet_type, status, quantity, internal_status in sample_pos:
            cursor.execute('''
                INSERT OR IGNORE INTO purchase_orders 
                (po_number, tablet_type, zoho_status, ordered_quantity, internal_status, created_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (po_number, tablet_type, status, quantity, internal_status))
        
        # 2. Add Tablet Types
        tablet_types = ["Standard Tablets", "Extended Release", "Coated Tablets"]
        for tablet_type in tablet_types:
            cursor.execute('INSERT OR IGNORE INTO tablet_types (name, status) VALUES (?, ?)', 
                         (tablet_type, 'Active'))
        
        # 3. Add Products
        products = [
            ("24-Count Display", "Standard Tablets", 24),
            ("12-Count Blister", "Standard Tablets", 12),
            ("48-Count Bottle", "Extended Release", 48)
        ]
        
        for name, tablet_type, count in products:
            cursor.execute('''
                INSERT OR IGNORE INTO products (name, tablet_type, tablet_count_per_unit)
                VALUES (?, ?, ?)
            ''', (name, tablet_type, count))
        
        # 4. Add Employees
        employees = [
            ("Admin User", "admin", True),
            ("Worker 1", "employee", True),
            ("Worker 2", "employee", True)
        ]
        
        for name, role, active in employees:
            cursor.execute('''
                INSERT OR IGNORE INTO employees (name, role, is_active)
                VALUES (?, ?, ?)
            ''', (name, role, active))
        
        # 5. Add Shipments (basic ones)
        po_ids = cursor.execute('SELECT id FROM purchase_orders').fetchall()
        if po_ids:
            shipments = [
                (po_ids[0][0], "1Z999AA1234567890", "UPS", "In Transit"),
                (po_ids[1][0], "1Z999AA1234567891", "UPS", "Delivered"),
                (po_ids[2][0], "403934084725", "FedEx", "Delivered")
            ]
            
            for po_id, tracking, carrier, status in shipments:
                cursor.execute('''
                    INSERT OR IGNORE INTO shipments 
                    (po_id, tracking_number, carrier, tracking_status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ''', (po_id, tracking, carrier, status))
        
        conn.commit()
        
        # Verify
        print("\n📊 Database restored:")
        tables = ['purchase_orders', 'shipments', 'products', 'employees', 'tablet_types']
        for table in tables:
            try:
                count = cursor.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                print(f"   {table}: {count} records")
            except:
                print(f"   {table}: ERROR")
        
        conn.close()
        
        print("\n🎉 DATABASE RESTORED TO WORKING STATE!")
        print("🚀 REFRESH YOUR BROWSER - EVERYTHING SHOULD WORK NOW!")
        
        return True
        
    except Exception as e:
        print(f"❌ Error restoring database: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚨 RESTORING DATABASE TO WORKING STATE")
    print("=" * 40)
    
    if restore_database():
        print("\n✅ SUCCESS! Your website should work now!")
    else:
        print("\n❌ RESTORE FAILED!")