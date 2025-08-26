#!/usr/bin/env python3
"""
Rebuild database with proper schema for real production use
NO sample data - just the correct tables and structure
"""

import sqlite3
import os
from datetime import datetime

def rebuild_production_database():
    """Rebuild database with correct production schema"""
    
    # Backup existing database
    if os.path.exists('tablettracker.db'):
        backup_name = f'tablettracker_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
        os.rename('tablettracker.db', backup_name)
        print(f"🔄 Backed up existing database to: {backup_name}")
    
    # Create fresh production database
    conn = sqlite3.connect('tablettracker.db')
    cursor = conn.cursor()
    
    try:
        print("🔧 Creating production database with correct schema...")
        
        # 1. Purchase Orders - Core table for POs from Zoho
        cursor.execute('''
            CREATE TABLE purchase_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                po_number TEXT UNIQUE NOT NULL,
                tablet_type TEXT,
                zoho_status TEXT,
                ordered_quantity INTEGER,
                internal_status TEXT DEFAULT 'Active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        print("✅ purchase_orders table created")
        
        # 2. Products - For warehouse and count forms
        cursor.execute('''
            CREATE TABLE products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                tablet_type TEXT,
                tablet_count_per_unit INTEGER DEFAULT 1,
                zoho_item_id TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        print("✅ products table created")
        
        # 3. Employees - For user management and production tracking
        cursor.execute('''
            CREATE TABLE employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                role TEXT DEFAULT 'employee',
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        print("✅ employees table created")
        
        # 4. Tablet Types - For product configuration
        cursor.execute('''
            CREATE TABLE tablet_types (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                status TEXT DEFAULT 'Active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        print("✅ tablet_types table created")
        
        # 5. Shipments - For tracking vendor shipments
        cursor.execute('''
            CREATE TABLE shipments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                po_id INTEGER,
                tracking_number TEXT UNIQUE,
                carrier TEXT,
                tracking_status TEXT,
                estimated_delivery DATE,
                actual_delivery TIMESTAMP,
                last_checkpoint TEXT,
                delivered_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_checked_at TIMESTAMP,
                FOREIGN KEY (po_id) REFERENCES purchase_orders (id)
            )
        ''')
        print("✅ shipments table created")
        
        # 6. Production Counts - For warehouse form submissions
        cursor.execute('''
            CREATE TABLE production_counts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                po_id INTEGER,
                product_id INTEGER,
                employee_id INTEGER,
                count INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (po_id) REFERENCES purchase_orders (id),
                FOREIGN KEY (product_id) REFERENCES products (id),
                FOREIGN KEY (employee_id) REFERENCES employees (id)
            )
        ''')
        print("✅ production_counts table created")
        
        # 7. Receiving tables - For receiving workflow
        cursor.execute('''
            CREATE TABLE receiving (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                po_id INTEGER,
                shipment_id INTEGER,
                received_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                delivery_photo_path TEXT,
                delivery_photo_zoho_id TEXT,
                total_small_boxes INTEGER DEFAULT 0,
                received_by TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (po_id) REFERENCES purchase_orders (id),
                FOREIGN KEY (shipment_id) REFERENCES shipments (id)
            )
        ''')
        print("✅ receiving table created")
        
        cursor.execute('''
            CREATE TABLE small_boxes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                receiving_id INTEGER,
                box_number INTEGER,
                total_bags INTEGER DEFAULT 0,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (receiving_id) REFERENCES receiving (id)
            )
        ''')
        print("✅ small_boxes table created")
        
        cursor.execute('''
            CREATE TABLE bags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                small_box_id INTEGER,
                bag_number INTEGER,
                bag_label_count INTEGER,
                pill_count INTEGER,
                status TEXT DEFAULT 'Available',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (small_box_id) REFERENCES small_boxes (id)
            )
        ''')
        print("✅ bags table created")
        
        # Create indexes for performance
        cursor.execute('CREATE INDEX idx_purchase_orders_po_number ON purchase_orders(po_number)')
        cursor.execute('CREATE INDEX idx_shipments_tracking ON shipments(tracking_number)')
        cursor.execute('CREATE INDEX idx_production_counts_po_id ON production_counts(po_id)')
        cursor.execute('CREATE INDEX idx_receiving_po_id ON receiving(po_id)')
        print("✅ Database indexes created")
        
        conn.commit()
        conn.close()
        
        print("\n🎉 PRODUCTION DATABASE REBUILT SUCCESSFULLY!")
        print("\n📋 Ready for real production use:")
        print("   ✅ Purchase Orders - Ready for Zoho sync")
        print("   ✅ Products - Ready for warehouse/count forms")
        print("   ✅ Employees - Ready for user management")
        print("   ✅ Shipments - Ready for vendor tracking")
        print("   ✅ Production Counts - Ready for warehouse submissions")
        print("   ✅ Receiving Workflow - Ready for shipment receiving")
        
        print("\n🚀 Your website is now ready for REAL production data!")
        print("   - Dashboard will show real PO statistics")
        print("   - Warehouse forms will work with real POs/products")
        print("   - Count forms will work with real products")
        print("   - Shipments will track real vendor shipments")
        print("   - Admin can manage real employees and products")
        print("   - Receiving workflow ready for real shipments")
        
        return True
        
    except Exception as e:
        print(f"❌ Error rebuilding database: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚨 REBUILDING PRODUCTION DATABASE")
    print("=" * 40)
    print("This will create a clean database ready for REAL data")
    print()
    
    if rebuild_production_database():
        print("\n✅ SUCCESS! Your website is ready for production!")
        print("🚀 REFRESH YOUR BROWSER AND START ENTERING REAL DATA!")
    else:
        print("\n❌ REBUILD FAILED!")