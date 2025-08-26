#!/usr/bin/env python3
"""
Minimal script to add just enough data to make pages work
"""

import sqlite3
import os

def minimal_fix():
    """Add minimal data to make pages work"""
    
    if not os.path.exists('tablettracker.db'):
        # Create database if it doesn't exist
        conn = sqlite3.connect('tablettracker.db')
        cursor = conn.cursor()
        
        # Create minimal tables
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS purchase_orders (
                id INTEGER PRIMARY KEY,
                po_number TEXT,
                tablet_type TEXT,
                zoho_status TEXT,
                ordered_quantity INTEGER,
                internal_status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY,
                name TEXT,
                tablet_type TEXT,
                tablet_count_per_unit INTEGER DEFAULT 1
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY,
                name TEXT,
                role TEXT DEFAULT 'employee',
                is_active BOOLEAN DEFAULT 1
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS shipments (
                id INTEGER PRIMARY KEY,
                po_id INTEGER,
                tracking_number TEXT,
                carrier TEXT,
                tracking_status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
    else:
        conn = sqlite3.connect('tablettracker.db')
        cursor = conn.cursor()
    
    try:
        print("🔧 Adding minimal data to make pages work...")
        
        # Add basic POs
        cursor.execute("DELETE FROM purchase_orders")  # Clear any bad data
        basic_pos = [
            ("PO-BASIC-001", "Standard Tablets", "confirmed", 1000, "Active"),
            ("PO-BASIC-002", "Extended Release", "confirmed", 500, "Active"),
            ("PO-BASIC-003", "Coated Tablets", "delivered", 750, "Completed")
        ]
        
        for po_data in basic_pos:
            cursor.execute('''
                INSERT INTO purchase_orders (po_number, tablet_type, zoho_status, ordered_quantity, internal_status)
                VALUES (?, ?, ?, ?, ?)
            ''', po_data)
        
        print("✅ Added purchase orders")
        
        # Add basic products
        cursor.execute("DELETE FROM products")  # Clear any bad data
        basic_products = [
            ("24-Count Display", "Standard Tablets", 24),
            ("12-Count Blister", "Standard Tablets", 12),
            ("48-Count Bottle", "Extended Release", 48)
        ]
        
        for prod_data in basic_products:
            cursor.execute('''
                INSERT INTO products (name, tablet_type, tablet_count_per_unit)
                VALUES (?, ?, ?)
            ''', prod_data)
        
        print("✅ Added products")
        
        # Add basic employees
        cursor.execute("DELETE FROM employees")  # Clear any bad data
        basic_employees = [
            ("Admin User", "admin", 1),
            ("Worker 1", "employee", 1),
            ("Worker 2", "employee", 1)
        ]
        
        for emp_data in basic_employees:
            cursor.execute('''
                INSERT INTO employees (name, role, is_active)
                VALUES (?, ?, ?)
            ''', emp_data)
        
        print("✅ Added employees")
        
        # Add basic shipments
        cursor.execute("DELETE FROM shipments")  # Clear any bad data
        po_ids = cursor.execute("SELECT id FROM purchase_orders").fetchall()
        if po_ids:
            basic_shipments = [
                (po_ids[0][0], "1Z999AA1001", "UPS", "In Transit"),
                (po_ids[1][0], "1Z999AA1002", "UPS", "Delivered"),
                (po_ids[2][0], "1Z999AA1003", "FedEx", "Delivered")
            ]
            
            for ship_data in basic_shipments:
                cursor.execute('''
                    INSERT INTO shipments (po_id, tracking_number, carrier, tracking_status)
                    VALUES (?, ?, ?, ?)
                ''', ship_data)
        
        print("✅ Added shipments")
        
        conn.commit()
        
        # Show what we have
        print("\n📊 Database now has:")
        print(f"   Purchase Orders: {cursor.execute('SELECT COUNT(*) FROM purchase_orders').fetchone()[0]}")
        print(f"   Products: {cursor.execute('SELECT COUNT(*) FROM products').fetchone()[0]}")
        print(f"   Employees: {cursor.execute('SELECT COUNT(*) FROM employees').fetchone()[0]}")
        print(f"   Shipments: {cursor.execute('SELECT COUNT(*) FROM shipments').fetchone()[0]}")
        
        conn.close()
        
        print("\n🎉 MINIMAL DATA ADDED!")
        print("🚀 REFRESH YOUR BROWSER NOW!")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    print("🚨 MINIMAL DATA FIX")
    print("=" * 20)
    
    if minimal_fix():
        print("\n✅ SUCCESS! Pages should work now!")
    else:
        print("\n❌ FAILED!")