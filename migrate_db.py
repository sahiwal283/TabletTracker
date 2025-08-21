#!/usr/bin/env python3
"""
Database migration script for TabletTracker
Creates missing tables and columns for receiving workflow
"""

import sqlite3
import os
from datetime import datetime

def migrate_database():
    """Run database migrations to add missing tables and columns"""
    
    # Get the database path
    db_path = 'tablettracker.db'
    
    print(f"🔍 Migrating database: {db_path}")
    print(f"⏰ Migration started at: {datetime.now()}")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # First, check what tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing_tables = [row[0] for row in cursor.fetchall()]
        print(f"📋 Existing tables: {existing_tables}")
        
        # Define all required tables with their schemas
        required_tables = {
            'purchase_orders': '''
                CREATE TABLE purchase_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    zoho_po_id TEXT UNIQUE,
                    po_number TEXT NOT NULL,
                    tablet_type TEXT,
                    zoho_status TEXT,
                    ordered_quantity INTEGER,
                    internal_status TEXT DEFAULT 'Active',
                    delivery_date DATE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''',
            'shipments': '''
                CREATE TABLE shipments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    po_id INTEGER,
                    tracking_number TEXT,
                    carrier TEXT,
                    shipped_date DATE,
                    estimated_delivery DATE,
                    actual_delivery DATE,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    carrier_code TEXT,
                    tracking_status TEXT,
                    last_checkpoint TEXT,
                    delivered_at TIMESTAMP,
                    last_checked_at TIMESTAMP,
                    FOREIGN KEY (po_id) REFERENCES purchase_orders (id)
                )
            ''',
            'tablet_types': '''
                CREATE TABLE tablet_types (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''',
            'products': '''
                CREATE TABLE products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    tablet_type_id INTEGER,
                    bottles_per_display INTEGER DEFAULT 6,
                    active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (tablet_type_id) REFERENCES tablet_types (id)
                )
            ''',
            'production_counts': '''
                CREATE TABLE production_counts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    po_id INTEGER,
                    product_id INTEGER,
                    count INTEGER,
                    box_number TEXT,
                    bag_number TEXT,
                    bag_label_count INTEGER,
                    displays_made INTEGER DEFAULT 0,
                    single_packs_remaining INTEGER DEFAULT 0,
                    loose_tablets INTEGER DEFAULT 0,
                    damaged_tablets INTEGER DEFAULT 0,
                    employee_name TEXT,
                    submission_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (po_id) REFERENCES purchase_orders (id),
                    FOREIGN KEY (product_id) REFERENCES products (id)
                )
            ''',
            'employees': '''
                CREATE TABLE employees (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    full_name TEXT,
                    active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''
        }
        
        # Create missing core tables first
        for table_name, schema in required_tables.items():
            if table_name not in existing_tables:
                print(f"📦 Creating {table_name} table...")
                cursor.execute(schema)
                print(f"✅ {table_name} table created")
            else:
                print(f"✅ {table_name} table already exists")
        
        # Now check if receiving table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='receiving'")
        receiving_exists = cursor.fetchone() is not None
        
        if not receiving_exists:
            print("📦 Creating receiving table...")
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
        else:
            print("✅ receiving table already exists")
        
        # Check if small_boxes table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='small_boxes'")
        small_boxes_exists = cursor.fetchone() is not None
        
        if not small_boxes_exists:
            print("📦 Creating small_boxes table...")
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
        else:
            print("✅ small_boxes table already exists")
        
        # Check if bags table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bags'")
        bags_exists = cursor.fetchone() is not None
        
        if not bags_exists:
            print("📦 Creating bags table...")
            cursor.execute('''
                CREATE TABLE bags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    small_box_id INTEGER,
                    bag_number INTEGER,
                    bag_label_count INTEGER,
                    status TEXT DEFAULT 'Available',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (small_box_id) REFERENCES small_boxes (id)
                )
            ''')
            print("✅ bags table created")
        else:
            print("✅ bags table already exists")
        
        # Check if we need to add missing columns to existing shipments table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='shipments'")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(shipments)")
            columns = [column[1] for column in cursor.fetchall()]
            
            missing_columns = []
            required_columns = {
                'carrier_code': 'TEXT',
                'tracking_status': 'TEXT',
                'last_checkpoint': 'TEXT',
                'delivered_at': 'TIMESTAMP',
                'last_checked_at': 'TIMESTAMP'
            }
            
            for col_name, col_type in required_columns.items():
                if col_name not in columns:
                    missing_columns.append((col_name, col_type))
            
            if missing_columns:
                print(f"📦 Adding {len(missing_columns)} missing columns to shipments table...")
                for col_name, col_type in missing_columns:
                    try:
                        cursor.execute(f'ALTER TABLE shipments ADD COLUMN {col_name} {col_type}')
                        print(f"✅ Added column: {col_name}")
                    except sqlite3.OperationalError as e:
                        if "duplicate column name" in str(e):
                            print(f"✅ Column {col_name} already exists")
                        else:
                            raise
            else:
                print("✅ All shipments columns exist")
        
        # Commit all changes
        conn.commit()
        
        # Show table counts
        print("\n📊 Final table counts:")
        all_tables = ['purchase_orders', 'shipments', 'tablet_types', 'products', 'production_counts', 'employees', 'receiving', 'small_boxes', 'bags']
        for table in all_tables:
            try:
                cursor.execute(f'SELECT COUNT(*) FROM {table}')
                count = cursor.fetchone()[0]
                print(f"   {table}: {count} records")
            except sqlite3.OperationalError:
                print(f"   {table}: TABLE NOT FOUND")
        
        conn.close()
        
        print(f"\n🎉 Migration completed successfully at: {datetime.now()}")
        return True
        
    except Exception as e:
        print(f"❌ Migration failed: {str(e)}")
        if 'conn' in locals():
            conn.close()
        return False

if __name__ == "__main__":
    success = migrate_database()
    exit(0 if success else 1)