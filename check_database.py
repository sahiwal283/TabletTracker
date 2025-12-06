#!/usr/bin/env python3
"""
Check database file and data
Run this on PythonAnywhere to see what's in the database
"""
import sqlite3
import os

print("=" * 70)
print("Database Check Script")
print("=" * 70)
print()

# Check for database files
db_files = ['tablet_counter.db', 'app.db', 'database.db']
found_files = []

for db_file in db_files:
    if os.path.exists(db_file):
        size = os.path.getsize(db_file)
        found_files.append((db_file, size))
        print(f"✅ Found: {db_file} ({size:,} bytes)")

if not found_files:
    print("❌ No database files found!")
    print("   Searching for .db files...")
    import glob
    db_files_found = glob.glob("*.db")
    if db_files_found:
        for db_file in db_files_found:
            size = os.path.getsize(db_file)
            print(f"   Found: {db_file} ({size:,} bytes)")
    else:
        print("   No .db files found in current directory")

print()

# Check the main database file
db_path = 'tablet_counter.db'
if os.path.exists(db_path):
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get table list
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        print(f"📊 Tables in database: {len(tables)}")
        for table in tables:
            table_name = table[0]
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            print(f"   - {table_name}: {count:,} rows")
        
        # Check warehouse_submissions specifically
        if any('warehouse_submissions' in str(t) for t in tables):
            cursor.execute("SELECT COUNT(*) FROM warehouse_submissions")
            count = cursor.fetchone()[0]
            print(f"\n📦 Warehouse Submissions: {count:,} records")
            
            if count > 0:
                cursor.execute("SELECT * FROM warehouse_submissions LIMIT 5")
                rows = cursor.fetchall()
                print(f"   Sample records (first 5):")
                for row in rows:
                    print(f"      {row}")
        
        # Check purchase_orders
        if any('purchase_orders' in str(t) for t in tables):
            cursor.execute("SELECT COUNT(*) FROM purchase_orders")
            count = cursor.fetchone()[0]
            print(f"\n📋 Purchase Orders: {count:,} records")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Error reading database: {e}")
        import traceback
        traceback.print_exc()
else:
    print(f"❌ Database file '{db_path}' not found!")

print("\n" + "=" * 70)
print("Check complete!")
print("=" * 70)

