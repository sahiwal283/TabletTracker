#!/usr/bin/env python3
"""
Diagnose and fix database issues
"""
import sqlite3
import os

def main():
    db_path = 'tablet_counter.db'
    
    print("=" * 70)
    print("TabletTracker Database Diagnosis & Fix")
    print("=" * 70)
    print()
    
    if not os.path.exists(db_path):
        print(f"❌ Database not found: {db_path}")
        return
    
    print(f"✅ Database file exists: {db_path}")
    print(f"   Size: {os.path.getsize(db_path):,} bytes")
    print()
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check submissions count
    print("1. Checking warehouse_submissions...")
    try:
        cursor.execute("SELECT COUNT(*) FROM warehouse_submissions")
        count = cursor.fetchone()[0]
        print(f"   📊 Found {count} submissions")
        
        if count > 0:
            cursor.execute("SELECT MIN(submission_date), MAX(submission_date) FROM warehouse_submissions")
            min_date, max_date = cursor.fetchone()
            print(f"   📅 Date range: {min_date} to {max_date}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    print()
    
    # Check purchase_orders schema
    print("2. Checking purchase_orders table schema...")
    cursor.execute("PRAGMA table_info(purchase_orders)")
    po_columns = {row[1] for row in cursor.fetchall()}
    print(f"   Current columns: {', '.join(sorted(po_columns))}")
    
    # Add parent_po_number if missing
    if 'parent_po_number' not in po_columns:
        print("\n   🔧 Adding missing parent_po_number column...")
        try:
            cursor.execute('ALTER TABLE purchase_orders ADD COLUMN parent_po_number TEXT')
            conn.commit()
            print("   ✅ Added parent_po_number column")
        except Exception as e:
            print(f"   ❌ Error adding column: {e}")
    else:
        print("   ✅ parent_po_number already exists")
    print()
    
    # Check warehouse_submissions schema
    print("3. Checking warehouse_submissions table schema...")
    cursor.execute("PRAGMA table_info(warehouse_submissions)")
    ws_columns = {row[1] for row in cursor.fetchall()}
    print(f"   Current columns: {', '.join(sorted(ws_columns))}")
    
    missing_columns = []
    
    # Check for all required columns
    required = {
        'admin_notes': 'TEXT',
        'po_assignment_verified': 'INTEGER DEFAULT 0',
        'submission_type': 'TEXT DEFAULT "packaged"',
        'machine_good_count': 'INTEGER DEFAULT 0'
    }
    
    for col_name, col_type in required.items():
        if col_name not in ws_columns:
            missing_columns.append((col_name, col_type))
    
    if missing_columns:
        print(f"\n   🔧 Adding {len(missing_columns)} missing columns...")
        for col_name, col_type in missing_columns:
            try:
                cursor.execute(f'ALTER TABLE warehouse_submissions ADD COLUMN {col_name} {col_type}')
                conn.commit()
                print(f"   ✅ Added {col_name}")
            except Exception as e:
                print(f"   ❌ Error adding {col_name}: {e}")
    else:
        print("   ✅ All required columns exist")
    print()
    
    # Check other tables
    print("4. Checking other required tables...")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    
    required_tables = ['machine_counts', 'app_settings', 'tablet_type_categories']
    for table in required_tables:
        if table in tables:
            print(f"   ✅ {table} exists")
        else:
            print(f"   ⚠️  {table} missing")
    print()
    
    # Check bags table for tablet_type_id
    if 'bags' in tables:
        print("5. Checking bags table...")
        cursor.execute("PRAGMA table_info(bags)")
        bags_columns = {row[1] for row in cursor.fetchall()}
        if 'tablet_type_id' not in bags_columns:
            print("   🔧 Adding tablet_type_id column...")
            try:
                cursor.execute('ALTER TABLE bags ADD COLUMN tablet_type_id INTEGER')
                conn.commit()
                print("   ✅ Added tablet_type_id")
            except Exception as e:
                print(f"   ❌ Error: {e}")
        else:
            print("   ✅ tablet_type_id exists")
        print()
    
    # Check tablet_types for category
    if 'tablet_types' in tables:
        print("6. Checking tablet_types table...")
        cursor.execute("PRAGMA table_info(tablet_types)")
        tt_columns = {row[1] for row in cursor.fetchall()}
        if 'category' not in tt_columns:
            print("   🔧 Adding category column...")
            try:
                cursor.execute('ALTER TABLE tablet_types ADD COLUMN category TEXT')
                conn.commit()
                print("   ✅ Added category")
            except Exception as e:
                print(f"   ❌ Error: {e}")
        else:
            print("   ✅ category exists")
        print()
    
    conn.close()
    
    print("=" * 70)
    print("✅ Diagnosis complete!")
    print("=" * 70)
    print("\nNext: Reload your web app in PythonAnywhere dashboard")

if __name__ == '__main__':
    main()

