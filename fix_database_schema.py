#!/usr/bin/env python3
"""
Fix database schema to match current code requirements
Adds missing columns that were added after the Nov 4 backup
"""
import sqlite3
import os

def fix_schema():
    """Add missing columns to make the Nov 4 backup work with current code"""
    
    db_path = 'tablet_counter.db'
    
    print("=" * 70)
    print("Fixing Database Schema")
    print("=" * 70)
    print()
    
    if not os.path.exists(db_path):
        print(f"❌ Database not found: {db_path}")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check current schema
        print("1. Checking purchase_orders table...")
        cursor.execute("PRAGMA table_info(purchase_orders)")
        po_columns = {row[1] for row in cursor.fetchall()}
        print(f"   Current columns: {', '.join(sorted(po_columns))}")
        
        # Add parent_po_number if missing
        if 'parent_po_number' not in po_columns:
            print("\n2. Adding parent_po_number column...")
            cursor.execute('''
                ALTER TABLE purchase_orders 
                ADD COLUMN parent_po_number TEXT
            ''')
            conn.commit()
            print("   ✅ Added parent_po_number column")
        else:
            print("\n2. parent_po_number column already exists ✓")
        
        # Check warehouse_submissions table
        print("\n3. Checking warehouse_submissions table...")
        cursor.execute("PRAGMA table_info(warehouse_submissions)")
        ws_columns = {row[1] for row in cursor.fetchall()}
        print(f"   Current columns: {', '.join(sorted(ws_columns))}")
        
        # Add missing columns if needed
        columns_to_add = {
            'admin_notes': 'TEXT',
            'po_assignment_verified': 'INTEGER DEFAULT 0',
            'submission_type': 'TEXT DEFAULT "packaged"',
            'machine_good_count': 'INTEGER DEFAULT 0'
        }
        
        for col_name, col_type in columns_to_add.items():
            if col_name not in ws_columns:
                print(f"\n4. Adding {col_name} column...")
                cursor.execute(f'''
                    ALTER TABLE warehouse_submissions 
                    ADD COLUMN {col_name} {col_type}
                ''')
                conn.commit()
                print(f"   ✅ Added {col_name} column")
            else:
                print(f"\n4. {col_name} column already exists ✓")
        
        # Check if machine_counts table exists
        print("\n5. Checking machine_counts table...")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='machine_counts'")
        if not cursor.fetchone():
            print("   Creating machine_counts table...")
            cursor.execute('''
                CREATE TABLE machine_counts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    po_id INTEGER,
                    tablet_type_id INTEGER,
                    machine_count INTEGER,
                    employee_name TEXT,
                    submission_date DATE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (po_id) REFERENCES purchase_orders(id),
                    FOREIGN KEY (tablet_type_id) REFERENCES tablet_types(id)
                )
            ''')
            conn.commit()
            print("   ✅ Created machine_counts table")
        else:
            print("   ✅ machine_counts table already exists")
        
        # Check if app_settings table exists
        print("\n6. Checking app_settings table...")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='app_settings'")
        if not cursor.fetchone():
            print("   Creating app_settings table...")
            cursor.execute('''
                CREATE TABLE app_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    setting_key TEXT UNIQUE NOT NULL,
                    setting_value TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()
            print("   ✅ Created app_settings table")
        else:
            print("   ✅ app_settings table already exists")
        
        # Check if tablet_types has category column
        print("\n7. Checking tablet_types table...")
        cursor.execute("PRAGMA table_info(tablet_types)")
        tt_columns = {row[1] for row in cursor.fetchall()}
        
        if 'category' not in tt_columns:
            print("   Adding category column...")
            cursor.execute('''
                ALTER TABLE tablet_types 
                ADD COLUMN category TEXT
            ''')
            conn.commit()
            print("   ✅ Added category column")
        else:
            print("   ✅ category column already exists")
        
        # Check if bags table has tablet_type_id
        print("\n8. Checking bags table...")
        cursor.execute("PRAGMA table_info(bags)")
        bags_columns = {row[1] for row in cursor.fetchall()}
        
        if 'tablet_type_id' not in bags_columns:
            print("   Adding tablet_type_id column...")
            cursor.execute('''
                ALTER TABLE bags 
                ADD COLUMN tablet_type_id INTEGER
            ''')
            conn.commit()
            print("   ✅ Added tablet_type_id column")
        else:
            print("   ✅ tablet_type_id column already exists")
        
        conn.close()
        
        print("\n" + "=" * 70)
        print("✅ Schema fix completed successfully!")
        print("=" * 70)
        print("\nNext step: Reload your web app in PythonAnywhere")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error fixing schema: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    fix_schema()

