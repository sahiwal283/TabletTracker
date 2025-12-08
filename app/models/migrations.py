"""
Comprehensive database migration system
Consolidates all migrations from migrate_db.py, migrate_to_v1.21.0.py, 
migrate_roles.py, migrate_language_column.py, and app.py init_db()

CRITICAL: All migrations are idempotent (safe to run multiple times)
CRITICAL: No data is ever deleted or lost
"""
import sqlite3
from typing import List, Dict, Optional


class MigrationRunner:
    """Runs all database migrations safely and idempotently"""
    
    def __init__(self, cursor):
        self.c = cursor
    
    def run_all(self):
        """Run all migrations in order"""
        # Core table migrations
        self._migrate_purchase_orders()
        self._migrate_po_lines()
        self._migrate_tablet_types()
        self._migrate_product_details()
        self._migrate_warehouse_submissions()
        self._migrate_shipments()
        self._migrate_receiving()
        self._migrate_small_boxes()
        self._migrate_bags()
        self._migrate_machine_counts()
        self._migrate_employees()
        self._migrate_app_settings()
        self._migrate_tablet_type_categories()
        self._migrate_roles_table()
    
    def _migrate_purchase_orders(self):
        """Migrate purchase_orders table - all column additions"""
        columns_to_add = {
            'zoho_status': 'TEXT',
            'internal_status': 'TEXT DEFAULT "Active"',
            'parent_po_number': 'TEXT',
            'machine_good_count': 'INTEGER DEFAULT 0',
            'machine_damaged_count': 'INTEGER DEFAULT 0',
        }
        for col, col_def in columns_to_add.items():
            self._add_column_if_not_exists('purchase_orders', col, col_def)
    
    def _migrate_po_lines(self):
        """Migrate po_lines table - machine count columns"""
        columns_to_add = {
            'machine_good_count': 'INTEGER DEFAULT 0',
            'machine_damaged_count': 'INTEGER DEFAULT 0',
        }
        for col, col_def in columns_to_add.items():
            self._add_column_if_not_exists('po_lines', col, col_def)
    
    def _migrate_tablet_types(self):
        """Migrate tablet_types table - category columns"""
        columns_to_add = {
            'category': 'TEXT',
            'category_id': 'INTEGER',
        }
        for col, col_def in columns_to_add.items():
            self._add_column_if_not_exists('tablet_types', col, col_def)
    
    def _migrate_product_details(self):
        """Ensure product_details table exists (created in schema)"""
        # Table creation handled in schema.py
        pass
    
    def _migrate_warehouse_submissions(self):
        """Migrate warehouse_submissions table - all column additions with backfills"""
        # submission_date column
        try:
            if not self._column_exists('warehouse_submissions', 'submission_date'):
                self.c.execute('ALTER TABLE warehouse_submissions ADD COLUMN submission_date DATE')
            # Always ensure NULL values are backfilled
            self.c.execute('UPDATE warehouse_submissions SET submission_date = DATE(created_at) WHERE submission_date IS NULL')
        except Exception as e:
            error_msg = str(e).lower()
            if 'duplicate column' not in error_msg and 'no such table' not in error_msg:
                print(f"Warning: Could not migrate submission_date column: {str(e)}")
        
        # po_assignment_verified column
        try:
            if not self._column_exists('warehouse_submissions', 'po_assignment_verified'):
                self.c.execute('ALTER TABLE warehouse_submissions ADD COLUMN po_assignment_verified BOOLEAN DEFAULT FALSE')
        except Exception as e:
            error_msg = str(e).lower()
            if 'duplicate column' not in error_msg and 'no such table' not in error_msg:
                print(f"Warning: Could not migrate po_assignment_verified column: {str(e)}")
        
        # inventory_item_id column with backfill
        try:
            if not self._column_exists('warehouse_submissions', 'inventory_item_id'):
                self.c.execute('ALTER TABLE warehouse_submissions ADD COLUMN inventory_item_id TEXT')
            # Backfill from product_details (only if table exists)
            try:
                self.c.execute('''
                    UPDATE warehouse_submissions 
                    SET inventory_item_id = (
                        SELECT tt.inventory_item_id 
                        FROM product_details pd
                        JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                        WHERE pd.product_name = warehouse_submissions.product_name
                        LIMIT 1
                    )
                    WHERE inventory_item_id IS NULL
                ''')
            except Exception:
                pass  # Backfill might fail if tables don't exist yet
        except Exception as e:
            error_msg = str(e).lower()
            if 'duplicate column' not in error_msg and 'no such table' not in error_msg:
                print(f"Warning: Could not migrate inventory_item_id column: {str(e)}")
        
        # admin_notes column
        self._add_column_if_not_exists('warehouse_submissions', 'admin_notes', 'TEXT')
        
        # submission_type column with backfill
        try:
            if not self._column_exists('warehouse_submissions', 'submission_type'):
                self.c.execute('ALTER TABLE warehouse_submissions ADD COLUMN submission_type TEXT DEFAULT "packaged"')
            # Always ensure NULL values have default
            self.c.execute('UPDATE warehouse_submissions SET submission_type = "packaged" WHERE submission_type IS NULL')
        except Exception as e:
            error_msg = str(e).lower()
            if 'duplicate column' not in error_msg and 'no such table' not in error_msg:
                print(f"Warning: Could not migrate submission_type column: {str(e)}")
        
        # NOTE: archived column was removed per user request - DO NOT ADD IT
    
    def _migrate_shipments(self):
        """Migrate shipments table - tracking columns"""
        columns_to_add = {
            'carrier_code': 'TEXT',
            'tracking_status': 'TEXT',
            'last_checkpoint': 'TEXT',
            'delivered_at': 'DATE',
            'last_checked_at': 'TIMESTAMP',
            'updated_at': 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP',
        }
        for col, col_def in columns_to_add.items():
            self._add_column_if_not_exists('shipments', col, col_def)
    
    def _migrate_receiving(self):
        """Ensure receiving table exists (created in schema)"""
        # Table creation handled in schema.py
        pass
    
    def _migrate_small_boxes(self):
        """Ensure small_boxes table exists (created in schema)"""
        # Table creation handled in schema.py
        pass
    
    def _migrate_bags(self):
        """Migrate bags table - pill_count and tablet_type_id columns"""
        columns_to_add = {
            'pill_count': 'INTEGER',
            'tablet_type_id': 'INTEGER',
        }
        for col, col_def in columns_to_add.items():
            self._add_column_if_not_exists('bags', col, col_def)
    
    def _migrate_machine_counts(self):
        """Ensure machine_counts table exists (created in schema)"""
        # Table creation handled in schema.py
        pass
    
    def _migrate_employees(self):
        """Migrate employees table - role and language columns"""
        # role column (from migrate_roles.py)
        if not self._column_exists('employees', 'role'):
            try:
                self.c.execute('ALTER TABLE employees ADD COLUMN role TEXT DEFAULT "warehouse_staff"')
                # Set default role for existing employees
                self.c.execute('UPDATE employees SET role = "warehouse_staff" WHERE role IS NULL OR role = ""')
            except Exception as e:
                if 'duplicate column' not in str(e).lower():
                    raise
        else:
            # Ensure NULL values have default
            self.c.execute('UPDATE employees SET role = "warehouse_staff" WHERE role IS NULL OR role = ""')
        
        # preferred_language column (from migrate_language_column.py)
        if not self._column_exists('employees', 'preferred_language'):
            try:
                self.c.execute('ALTER TABLE employees ADD COLUMN preferred_language TEXT DEFAULT "en"')
            except Exception as e:
                if 'duplicate column' not in str(e).lower():
                    raise
        
        # Ensure is_active column exists (may be named 'active' in older schemas)
        if not self._column_exists('employees', 'is_active'):
            if self._column_exists('employees', 'active'):
                # Rename 'active' to 'is_active' for consistency
                try:
                    # SQLite doesn't support RENAME COLUMN directly, so we'll just add is_active
                    # and sync values (both columns will exist temporarily)
                    self.c.execute('ALTER TABLE employees ADD COLUMN is_active BOOLEAN DEFAULT TRUE')
                    self.c.execute('UPDATE employees SET is_active = active WHERE is_active IS NULL')
                except Exception as e:
                    if 'duplicate column' not in str(e).lower():
                        raise
            else:
                self._add_column_if_not_exists('employees', 'is_active', 'BOOLEAN DEFAULT TRUE')
    
    def _migrate_app_settings(self):
        """Ensure app_settings table exists (created in schema)"""
        # Table creation handled in schema.py
        pass
    
    def _migrate_tablet_type_categories(self):
        """Ensure tablet_type_categories table exists (created in schema)"""
        # Table creation handled in schema.py
        pass
    
    def _migrate_roles_table(self):
        """Create roles table if it doesn't exist (from migrate_roles.py)"""
        # Check if roles table exists
        self.c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='roles'")
        if not self.c.fetchone():
            try:
                self.c.execute('''
                    CREATE TABLE roles (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        role_name TEXT UNIQUE NOT NULL,
                        display_name TEXT NOT NULL,
                        permissions TEXT NOT NULL,
                        description TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Insert default roles
                roles = [
                    ('warehouse_staff', 'Warehouse Staff', 'warehouse,count', 'Can submit warehouse counts and view basic info'),
                    ('supervisor', 'Supervisor', 'warehouse,count,dashboard,shipping', 'Can access warehouse operations, dashboard, and shipping'),
                    ('manager', 'Manager', 'warehouse,count,dashboard,shipping,reports', 'Can access all operations except admin functions'),
                    ('admin', 'Administrator', 'all', 'Full system access including employee management and configuration')
                ]
                
                for role_name, display_name, permissions, description in roles:
                    self.c.execute('''
                        INSERT OR IGNORE INTO roles (role_name, display_name, permissions, description)
                        VALUES (?, ?, ?, ?)
                    ''', (role_name, display_name, permissions, description))
            except Exception as e:
                # Table might already exist from concurrent execution
                if 'already exists' not in str(e).lower():
                    raise
    
    def _column_exists(self, table_name: str, column_name: str) -> bool:
        """Check if a column exists in a table"""
        try:
            # First check if table exists
            self.c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            if not self.c.fetchone():
                return False
            
            # Then check if column exists
            self.c.execute(f"PRAGMA table_info({table_name})")
            existing_cols = [row[1] for row in self.c.fetchall()]
            return column_name in existing_cols
        except Exception as e:
            # Table might not exist yet or other error
            print(f"Warning: Could not check column {column_name} in {table_name}: {str(e)}")
            return False
    
    def _add_column_if_not_exists(self, table_name: str, column_name: str, column_def: str):
        """Add a column to a table if it doesn't exist"""
        if not self._column_exists(table_name, column_name):
            try:
                # Check if table exists first
                self.c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
                if not self.c.fetchone():
                    print(f"Warning: Table {table_name} does not exist, skipping column {column_name}")
                    return
                
                self.c.execute(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}')
            except Exception as e:
                # Column might already exist or table might not exist yet
                error_msg = str(e).lower()
                if 'duplicate column' not in error_msg and 'no such table' not in error_msg:
                    print(f"Error adding column {column_name} to {table_name}: {str(e)}")
                    raise
