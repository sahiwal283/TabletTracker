#!/usr/bin/env python3
"""
Test script to verify consolidated migrations work correctly
Run this to test: python3 test_migrations.py
"""
import sqlite3
import os
from app.models.schema import SchemaManager

def test_migrations():
    """Test that migrations work correctly"""
    print("🧪 Testing consolidated migration system...")
    
    # Backup existing database if it exists
    db_path = 'tablet_counter.db'
    if os.path.exists(db_path):
        backup_path = 'tablet_counter_backup.db'
        import shutil
        shutil.copy2(db_path, backup_path)
        print(f"✅ Backed up existing database to {backup_path}")
    
    try:
        # Initialize database
        sm = SchemaManager()
        sm.initialize_all_tables()
        print("✅ Database initialization successful")
        
        # Verify tables exist
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in c.fetchall()]
        
        required_tables = [
            'purchase_orders', 'po_lines', 'tablet_types', 'product_details',
            'warehouse_submissions', 'shipments', 'receiving', 'small_boxes',
            'bags', 'machine_counts', 'employees', 'app_settings',
            'tablet_type_categories', 'roles'
        ]
        
        missing_tables = [t for t in required_tables if t not in tables]
        if missing_tables:
            print(f"❌ Missing tables: {missing_tables}")
            return False
        
        print(f"✅ All {len(required_tables)} required tables exist")
        
        # Verify key columns exist
        c.execute("PRAGMA table_info(warehouse_submissions)")
        ws_cols = [row[1] for row in c.fetchall()]
        required_ws_cols = ['submission_date', 'po_assignment_verified', 'inventory_item_id', 'admin_notes', 'submission_type']
        missing_cols = [col for col in required_ws_cols if col not in ws_cols]
        if missing_cols:
            print(f"❌ Missing columns in warehouse_submissions: {missing_cols}")
            return False
        
        print("✅ All required columns exist")
        
        # Verify employees table has role and preferred_language
        c.execute("PRAGMA table_info(employees)")
        emp_cols = [row[1] for row in c.fetchall()]
        if 'role' not in emp_cols or 'preferred_language' not in emp_cols:
            print(f"❌ Missing columns in employees: role={('role' in emp_cols)}, preferred_language={('preferred_language' in emp_cols)}")
            return False
        
        print("✅ Employee columns verified")
        
        conn.close()
        print("\n🎉 All migrations verified successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Migration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = test_migrations()
    exit(0 if success else 1)

