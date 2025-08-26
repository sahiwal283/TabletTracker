"""
Core database connection and initialization
"""

import sqlite3
import os
from flask import g, current_app

def get_db():
    """Get database connection, creating one if needed"""
    if 'db' not in g:
        # Handle SQLite path for different configurations
        db_path = current_app.config['DATABASE_URL']
        if db_path.startswith('sqlite:///'):
            db_path = db_path.replace('sqlite:///', '')
            if not os.path.isabs(db_path):
                db_path = os.path.join(current_app.instance_path, db_path)
        
        g.db = sqlite3.connect(db_path)
        g.db.row_factory = sqlite3.Row
    return g.db

def close_db(e=None):
    """Close database connection"""
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    """Initialize database with all required tables"""
    conn = get_db()
    c = conn.cursor()
    
    # Create all tables
    _create_purchase_order_tables(c)
    _create_product_tables(c)
    _create_warehouse_tables(c) 
    _create_shipping_tables(c)
    _create_employee_tables(c)
    
    conn.commit()

def _create_purchase_order_tables(cursor):
    """Create purchase order related tables"""
    # Purchase Orders table
    cursor.execute('''CREATE TABLE IF NOT EXISTS purchase_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        po_number TEXT UNIQUE NOT NULL,
        zoho_po_id TEXT UNIQUE,
        tablet_type TEXT,
        ordered_quantity INTEGER DEFAULT 0,
        current_good_count INTEGER DEFAULT 0,
        current_damaged_count INTEGER DEFAULT 0,
        remaining_quantity INTEGER DEFAULT 0,
        closed BOOLEAN DEFAULT FALSE,
        internal_status TEXT DEFAULT 'Active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # PO Line Items table
    cursor.execute('''CREATE TABLE IF NOT EXISTS po_lines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        po_id INTEGER,
        po_number TEXT,
        inventory_item_id TEXT,
        line_item_name TEXT,
        quantity_ordered INTEGER DEFAULT 0,
        good_count INTEGER DEFAULT 0,
        damaged_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (po_id) REFERENCES purchase_orders (id)
    )''')

def _create_product_tables(cursor):
    """Create product and tablet type tables"""
    # Tablet Types table
    cursor.execute('''CREATE TABLE IF NOT EXISTS tablet_types (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tablet_type_name TEXT UNIQUE NOT NULL,
        inventory_item_id TEXT UNIQUE
    )''')
    
    # Product Details table
    cursor.execute('''CREATE TABLE IF NOT EXISTS product_details (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT UNIQUE NOT NULL,
        tablet_type_id INTEGER,
        packages_per_display INTEGER DEFAULT 0,
        tablets_per_package INTEGER DEFAULT 0,
        FOREIGN KEY (tablet_type_id) REFERENCES tablet_types (id)
    )''')

def _create_warehouse_tables(cursor):
    """Create warehouse and submission tables"""
    # Warehouse Submissions table
    cursor.execute('''CREATE TABLE IF NOT EXISTS warehouse_submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_name TEXT NOT NULL,
        product_name TEXT NOT NULL,
        box_number INTEGER,
        bag_number INTEGER,
        bag_label_count INTEGER,
        displays_made INTEGER DEFAULT 0,
        packs_remaining INTEGER DEFAULT 0,
        loose_tablets INTEGER DEFAULT 0,
        damaged_tablets INTEGER DEFAULT 0,
        discrepancy_flag BOOLEAN DEFAULT FALSE,
        assigned_po_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (assigned_po_id) REFERENCES purchase_orders (id)
    )''')

def _create_shipping_tables(cursor):
    """Create shipping and receiving tables"""
    # Shipments table
    cursor.execute('''CREATE TABLE IF NOT EXISTS shipments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        po_id INTEGER,
        tracking_number TEXT,
        carrier TEXT,
        status TEXT DEFAULT 'Pending',
        estimated_delivery DATE,
        actual_delivery DATE,
        last_checkpoint TEXT,
        delivered_at DATE,
        last_checked_at TIMESTAMP,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (po_id) REFERENCES purchase_orders (id)
    )''')
    
    # Receiving table
    cursor.execute('''CREATE TABLE IF NOT EXISTS receiving (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        po_id INTEGER,
        shipment_id INTEGER,
        received_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        delivery_photo_path TEXT,
        delivery_photo_zoho_id TEXT,
        package_condition TEXT,
        received_by TEXT,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (po_id) REFERENCES purchase_orders (id),
        FOREIGN KEY (shipment_id) REFERENCES shipments (id)
    )''')
    
    # Small boxes and bags tables
    cursor.execute('''CREATE TABLE IF NOT EXISTS small_boxes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        receiving_id INTEGER,
        box_number INTEGER,
        total_bags INTEGER DEFAULT 0,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (receiving_id) REFERENCES receiving (id)
    )''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS bags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        small_box_id INTEGER,
        bag_number INTEGER,
        product_type TEXT,
        pill_count INTEGER,
        status TEXT DEFAULT 'Available',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (small_box_id) REFERENCES small_boxes (id)
    )''')

def _create_employee_tables(cursor):
    """Create employee and authentication tables"""
    # Employees table
    cursor.execute('''CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        full_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        is_active BOOLEAN DEFAULT TRUE,
        role TEXT DEFAULT 'warehouse_staff',
        preferred_language TEXT DEFAULT 'en',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Add columns if they don't exist (migrations)
    _add_column_if_not_exists(cursor, 'employees', 'role', 'TEXT DEFAULT "warehouse_staff"')
    _add_column_if_not_exists(cursor, 'employees', 'preferred_language', 'TEXT DEFAULT "en"')

def _add_column_if_not_exists(cursor, table, column, definition):
    """Add column to table if it doesn't exist"""
    try:
        cursor.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
    except sqlite3.OperationalError:
        pass  # Column already exists
