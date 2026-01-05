"""
Database migration utilities
Handles schema changes and column additions
"""
import sqlite3
import logging

logger = logging.getLogger(__name__)


class MigrationRunner:
    """Runs database migrations safely"""
    
    def __init__(self, cursor):
        self.c = cursor
    
    def run_all(self):
        """Run all migrations"""
        self._migrate_purchase_orders()
        self._migrate_po_lines()
        self._migrate_tablet_types()
        self._migrate_warehouse_submissions()
        self._migrate_shipments()
        self._migrate_bags()
        self._migrate_tablet_type_categories()
        self._migrate_receiving()
        self._migrate_machine_counts()
    
    def _migrate_purchase_orders(self):
        """Migrate purchase_orders table"""
        # Add zoho_status column
        self._add_column_if_not_exists('purchase_orders', 'zoho_status', 'TEXT')
        
        # Add internal_status column
        self._add_column_if_not_exists('purchase_orders', 'internal_status', 'TEXT DEFAULT "Active"')
        
        # Add parent_po_number column
        self._add_column_if_not_exists('purchase_orders', 'parent_po_number', 'TEXT')
        
        # Add machine count columns
        self._add_column_if_not_exists('purchase_orders', 'machine_good_count', 'INTEGER DEFAULT 0')
        self._add_column_if_not_exists('purchase_orders', 'machine_damaged_count', 'INTEGER DEFAULT 0')
    
    def _migrate_po_lines(self):
        """Migrate po_lines table"""
        # Add machine count columns
        self._add_column_if_not_exists('po_lines', 'machine_good_count', 'INTEGER DEFAULT 0')
        self._add_column_if_not_exists('po_lines', 'machine_damaged_count', 'INTEGER DEFAULT 0')
    
    def _migrate_tablet_types(self):
        """Migrate tablet_types table"""
        # Add category column
        self._add_column_if_not_exists('tablet_types', 'category', 'TEXT')
        
        # Add category_id column
        self._add_column_if_not_exists('tablet_types', 'category_id', 'INTEGER')
    
        # Add variety pack support columns
        self._add_column_if_not_exists('tablet_types', 'is_variety_pack', 'BOOLEAN DEFAULT 0')
        self._add_column_if_not_exists('tablet_types', 'tablets_per_bottle', 'INTEGER')
        self._add_column_if_not_exists('tablet_types', 'bottles_per_pack', 'INTEGER')
        self._add_column_if_not_exists('tablet_types', 'variety_pack_contents', 'TEXT')
    
    def _migrate_warehouse_submissions(self):
        """Migrate warehouse_submissions table"""
        # Add submission_date column
        if not self._column_exists('warehouse_submissions', 'submission_date'):
            try:
                self.c.execute('ALTER TABLE warehouse_submissions ADD COLUMN submission_date DATE')
                # Backfill existing records
                self.c.execute('UPDATE warehouse_submissions SET submission_date = DATE(created_at) WHERE submission_date IS NULL')
            except:
                pass
        
        # Add po_assignment_verified column
        if not self._column_exists('warehouse_submissions', 'po_assignment_verified'):
            try:
                self.c.execute('ALTER TABLE warehouse_submissions ADD COLUMN po_assignment_verified BOOLEAN DEFAULT FALSE')
            except:
                pass
        
        # Add inventory_item_id column
        if not self._column_exists('warehouse_submissions', 'inventory_item_id'):
            try:
                self.c.execute('ALTER TABLE warehouse_submissions ADD COLUMN inventory_item_id TEXT')
                # Backfill
                self.c.execute('''
                    UPDATE warehouse_submissions 
                    SET inventory_item_id = (
                        SELECT tt.inventory_item_id 
                        FROM product_details pd
                        JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                        WHERE pd.product_name = warehouse_submissions.product_name
                    )
                    WHERE inventory_item_id IS NULL
                ''')
            except:
                pass
        
        # Add admin_notes column
        self._add_column_if_not_exists('warehouse_submissions', 'admin_notes', 'TEXT')
        
        # Add submission_type column
        if not self._column_exists('warehouse_submissions', 'submission_type'):
            try:
                self.c.execute('ALTER TABLE warehouse_submissions ADD COLUMN submission_type TEXT DEFAULT "packaged"')
                self.c.execute('UPDATE warehouse_submissions SET submission_type = "packaged" WHERE submission_type IS NULL')
            except:
                pass
        
        # Add machine_id column for machine submissions
        self._add_column_if_not_exists('warehouse_submissions', 'machine_id', 'INTEGER REFERENCES machines(id)')
        
        # Add tablets_pressed_into_cards column for machine submissions
        # This properly stores the total tablets pressed into cards (turns × cards_per_turn × tablets_per_package)
        # Previously stored in loose_tablets which was misleading for machine submissions
        if not self._column_exists('warehouse_submissions', 'tablets_pressed_into_cards'):
            try:
                self.c.execute('ALTER TABLE warehouse_submissions ADD COLUMN tablets_pressed_into_cards INTEGER DEFAULT 0')
                # Backfill existing machine submissions: copy from loose_tablets
                # For machine submissions, loose_tablets actually contains tablets_pressed_into_cards
                self.c.execute('''
                    UPDATE warehouse_submissions 
                    SET tablets_pressed_into_cards = loose_tablets
                    WHERE submission_type = 'machine' 
                    AND loose_tablets IS NOT NULL 
                    AND loose_tablets > 0
                ''')
            except Exception as e:
                logger.warning(f"Could not add tablets_pressed_into_cards column: {str(e)}")
    
        # Add receipt_number column for tracking receipt numbers
        self._add_column_if_not_exists('warehouse_submissions', 'receipt_number', 'TEXT')
    
    def _migrate_shipments(self):
        """Migrate shipments table"""
        columns_to_add = {
            'carrier_code': 'TEXT',
            'tracking_status': 'TEXT',
            'last_checkpoint': 'TEXT',
            'delivered_at': 'DATE',
            'last_checked_at': 'TIMESTAMP',
        }
        for col, coltype in columns_to_add.items():
            self._add_column_if_not_exists('shipments', col, coltype)
    
    def _migrate_bags(self):
        """Migrate bags table"""
        self._add_column_if_not_exists('bags', 'pill_count', 'INTEGER')
        self._add_column_if_not_exists('bags', 'tablet_type_id', 'INTEGER')
        
        # Add Zoho receive push tracking columns
        # zoho_receive_pushed: tracks if bag has been pushed to Zoho receives
        # zoho_receive_id: stores the Zoho receive ID after successful push
        self._add_column_if_not_exists('bags', 'zoho_receive_pushed', 'BOOLEAN DEFAULT 0')
        self._add_column_if_not_exists('bags', 'zoho_receive_id', 'TEXT')
    
    def _migrate_tablet_type_categories(self):
        """Migrate tablet_type_categories table - ensure it exists"""
        # Table creation is handled in schema, but we ensure category_id column exists
        pass
    
    def _migrate_receiving(self):
        """Migrate receiving table - add receive_name column"""
        # Add receive_name column
        self._add_column_if_not_exists('receiving', 'receive_name', 'TEXT')
        
        # Note: Backfilling is handled by the standalone backfill script
        # This ensures proper sequential numbering per PO
    
    def _migrate_machine_counts(self):
        """Migrate machine_counts table - add machine_id column"""
        # Add machine_id column to link machine counts to specific machines
        self._add_column_if_not_exists('machine_counts', 'machine_id', 'INTEGER REFERENCES machines(id)')
    
    def _column_exists(self, table_name, column_name):
        """Check if a column exists in a table"""
        try:
            self.c.execute(f"PRAGMA table_info({table_name})")
            existing_cols = [row[1] for row in self.c.fetchall()]
            return column_name in existing_cols
        except:
            return False
    
    def _add_column_if_not_exists(self, table_name, column_name, column_def):
        """Add a column to a table if it doesn't exist"""
        if not self._column_exists(table_name, column_name):
            try:
                self.c.execute(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}')
            except Exception as e:
                # Column might already exist or table might not exist yet
                pass

