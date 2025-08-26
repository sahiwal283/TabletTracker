#!/usr/bin/env python3
"""
Create sample shipment data for testing
Run this on PythonAnywhere to populate the shipments page
"""

import sqlite3
import sys
import os
from datetime import datetime, timedelta

def create_sample_data():
    """Create sample POs and shipments for testing"""
    
    # Connect to database
    db_path = 'tablettracker.db'
    if not os.path.exists(db_path):
        print("❌ Database file not found. Make sure you're in the TabletTracker directory.")
        return False
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        print("🔍 Creating sample data...")
        
        # Create sample POs
        sample_pos = [
            ("PO-001-TEST", "Standard Tablets", "confirmed", 5000),
            ("PO-002-TEST", "Extended Release", "confirmed", 3000),
            ("PO-003-TEST", "Coated Tablets", "confirmed", 7000),
        ]
        
        po_ids = []
        for po_number, tablet_type, status, quantity in sample_pos:
            # Check if PO already exists
            existing = cursor.execute('SELECT id FROM purchase_orders WHERE po_number = ?', (po_number,)).fetchone()
            if existing:
                po_ids.append(existing[0])
                print(f"✅ PO {po_number} already exists")
            else:
                cursor.execute('''
                    INSERT INTO purchase_orders (po_number, tablet_type, zoho_status, ordered_quantity, internal_status)
                    VALUES (?, ?, ?, ?, ?)
                ''', (po_number, tablet_type, status, quantity, 'Active'))
                po_ids.append(cursor.lastrowid)
                print(f"✅ Created PO {po_number}")
        
        # Create sample shipments
        sample_shipments = [
            (0, "1Z999AA1234567890", "UPS", "In Transit", None),
            (1, "1Z999AA1234567891", "UPS", "Delivered", datetime.now() - timedelta(days=2)),
            (2, "403934084725", "FedEx", "Out for Delivery", None),
        ]
        
        for i, (po_idx, tracking, carrier, status, delivered_at) in enumerate(sample_shipments):
            po_id = po_ids[po_idx]
            
            # Check if shipment already exists
            existing = cursor.execute('SELECT id FROM shipments WHERE tracking_number = ?', (tracking,)).fetchone()
            if existing:
                print(f"✅ Shipment {tracking} already exists")
            else:
                cursor.execute('''
                    INSERT INTO shipments (po_id, tracking_number, carrier, tracking_status, delivered_at, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (po_id, tracking, carrier, status, delivered_at, datetime.now()))
                print(f"✅ Created shipment {tracking} ({carrier}) - {status}")
        
        conn.commit()
        print("\n🎉 Sample data created successfully!")
        print("\nYou should now see:")
        print("- 3 test Purchase Orders")
        print("- 3 test Shipments with different statuses")
        print("\nGo to the Shipments page to see them!")
        
        return True
        
    except Exception as e:
        print(f"❌ Error creating sample data: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        conn.close()

def check_tables():
    """Check what tables exist in the database"""
    try:
        conn = sqlite3.connect('tablettracker.db')
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        
        print(f"📋 Database tables: {', '.join(tables)}")
        
        # Check if required tables exist
        required_tables = ['purchase_orders', 'shipments']
        missing_tables = [t for t in required_tables if t not in tables]
        
        if missing_tables:
            print(f"❌ Missing required tables: {', '.join(missing_tables)}")
            print("Run migrate_db.py first to create missing tables")
            return False
        
        print("✅ All required tables present")
        return True
        
    except Exception as e:
        print(f"❌ Database error: {e}")
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    print("=== Sample Shipment Data Creator ===")
    print(f"Working directory: {os.getcwd()}")
    
    if not check_tables():
        sys.exit(1)
    
    if create_sample_data():
        print("\n✅ Success! Check the Shipments page in your browser.")
    else:
        print("\n❌ Failed to create sample data.")
        sys.exit(1)