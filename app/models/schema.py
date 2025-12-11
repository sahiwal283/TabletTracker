"""
Database schema management and migrations
Consolidates all table creation from app.py init_db()
"""
import sqlite3
import traceback


class SchemaManager:
    """Manages database schema creation and migrations"""
    
    def __init__(self, db_path='tablet_counter.db'):
        self.db_path = db_path
    
    def initialize_all_tables(self):
        """Initialize all database tables and run migrations"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        try:
            # Create all tables (IF NOT EXISTS ensures idempotency)
            self._create_purchase_orders_table(c)
            self._create_po_lines_table(c)
            self._create_tablet_types_table(c)
            self._create_product_details_table(c)
            self._create_warehouse_submissions_table(c)
            self._create_shipments_table(c)
            self._create_receiving_table(c)
            self._create_small_boxes_table(c)
            self._create_bags_table(c)
            self._create_machine_counts_table(c)
            self._create_machines_table(c)
            self._create_employees_table(c)
            self._create_app_settings_table(c)
            self._create_tablet_type_categories_table(c)
            
            conn.commit()  # Commit table creation before migrations
            
            # Run all migrations (adds columns, backfills data)
            from app.models.migrations import MigrationRunner
            migration_runner = MigrationRunner(c)
            migration_runner.run_all()
            
            # Initialize default settings
            self._initialize_default_settings(c)
            
            conn.commit()
        except Exception as e:
            print(f"Error initializing database schema: {str(e)}")
            traceback.print_exc()
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def _create_purchase_orders_table(self, c):
        """Create purchase_orders table"""
        c.execute('''CREATE TABLE IF NOT EXISTS purchase_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            po_number TEXT UNIQUE NOT NULL,
            zoho_po_id TEXT UNIQUE,
            tablet_type TEXT,
            zoho_status TEXT,
            ordered_quantity INTEGER DEFAULT 0,
            current_good_count INTEGER DEFAULT 0,
            current_damaged_count INTEGER DEFAULT 0,
            remaining_quantity INTEGER DEFAULT 0,
            closed BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
    
    def _create_po_lines_table(self, c):
        """Create po_lines table"""
        c.execute('''CREATE TABLE IF NOT EXISTS po_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            po_id INTEGER,
            po_number TEXT,
            inventory_item_id TEXT NOT NULL,
            line_item_name TEXT,
            quantity_ordered INTEGER DEFAULT 0,
            good_count INTEGER DEFAULT 0,
            damaged_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (po_id) REFERENCES purchase_orders (id)
        )''')
    
    def _create_tablet_types_table(self, c):
        """Create tablet_types table"""
        c.execute('''CREATE TABLE IF NOT EXISTS tablet_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tablet_type_name TEXT UNIQUE NOT NULL,
            inventory_item_id TEXT UNIQUE,
            category TEXT
        )''')
    
    def _create_product_details_table(self, c):
        """Create product_details table"""
        c.execute('''CREATE TABLE IF NOT EXISTS product_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT UNIQUE NOT NULL,
            tablet_type_id INTEGER,
            packages_per_display INTEGER DEFAULT 0,
            tablets_per_package INTEGER DEFAULT 0,
            FOREIGN KEY (tablet_type_id) REFERENCES tablet_types (id)
        )''')
    
    def _create_warehouse_submissions_table(self, c):
        """Create warehouse_submissions table"""
        c.execute('''CREATE TABLE IF NOT EXISTS warehouse_submissions (
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
    
    def _create_shipments_table(self, c):
        """Create shipments table"""
        c.execute('''CREATE TABLE IF NOT EXISTS shipments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            po_id INTEGER,
            tracking_number TEXT,
            carrier TEXT,
            carrier_code TEXT,
            shipped_date DATE,
            estimated_delivery DATE,
            actual_delivery DATE,
            tracking_status TEXT,
            last_checkpoint TEXT,
            delivered_at DATE,
            last_checked_at TIMESTAMP,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (po_id) REFERENCES purchase_orders (id)
        )''')
    
    def _create_receiving_table(self, c):
        """Create receiving table"""
        c.execute('''CREATE TABLE IF NOT EXISTS receiving (
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
        )''')
    
    def _create_small_boxes_table(self, c):
        """Create small_boxes table"""
        c.execute('''CREATE TABLE IF NOT EXISTS small_boxes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receiving_id INTEGER,
            box_number INTEGER,
            total_bags INTEGER DEFAULT 0,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (receiving_id) REFERENCES receiving (id)
        )''')
    
    def _create_bags_table(self, c):
        """Create bags table"""
        c.execute('''CREATE TABLE IF NOT EXISTS bags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            small_box_id INTEGER,
            bag_number INTEGER,
            bag_label_count INTEGER,
            pill_count INTEGER,
            tablet_type_id INTEGER,
            status TEXT DEFAULT 'Available',
            receive_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (small_box_id) REFERENCES small_boxes (id)
        )''')
    
    def _create_machine_counts_table(self, c):
        """Create machine_counts table"""
        c.execute('''CREATE TABLE IF NOT EXISTS machine_counts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tablet_type_id INTEGER,
            machine_count INTEGER NOT NULL,
            employee_name TEXT NOT NULL,
            count_date DATE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (tablet_type_id) REFERENCES tablet_types (id)
        )''')
    
    def _create_machines_table(self, c):
        """Create machines table"""
        c.execute('''CREATE TABLE IF NOT EXISTS machines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_name TEXT UNIQUE NOT NULL,
            cards_per_turn INTEGER NOT NULL DEFAULT 1,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Initialize default machines if none exist
        existing_machines = c.execute('SELECT COUNT(*) as count FROM machines').fetchone()
        if existing_machines[0] == 0:
            default_machines = [
                ('Machine 1', 1),
                ('Machine 2', 1)
            ]
            for machine_name, cards_per_turn in default_machines:
                c.execute('''
                    INSERT INTO machines (machine_name, cards_per_turn, is_active)
                    VALUES (?, ?, TRUE)
                ''', (machine_name, cards_per_turn))
    
    def _create_employees_table(self, c):
        """Create employees table"""
        c.execute('''CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'warehouse_staff',
            preferred_language TEXT DEFAULT 'en',
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
    
    def _create_app_settings_table(self, c):
        """Create app_settings table"""
        c.execute('''CREATE TABLE IF NOT EXISTS app_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            setting_key TEXT UNIQUE NOT NULL,
            setting_value TEXT NOT NULL,
            description TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
    
    def _create_tablet_type_categories_table(self, c):
        """Create tablet_type_categories table"""
        c.execute('''CREATE TABLE IF NOT EXISTS tablet_type_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_name TEXT UNIQUE NOT NULL,
            category_order INTEGER UNIQUE NOT NULL
        )''')
    
    def _initialize_default_settings(self, c):
        """Initialize default app settings"""
        default_settings = [
            ('cards_per_turn', '1', 'Number of cards produced in one turn of the machine')
        ]
        for key, value, description in default_settings:
            existing = c.execute('SELECT id FROM app_settings WHERE setting_key = ?', (key,)).fetchone()
            if not existing:
                c.execute('''
                    INSERT INTO app_settings (setting_key, setting_value, description)
                    VALUES (?, ?, ?)
                ''', (key, value, description))
