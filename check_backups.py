#!/usr/bin/env python3
"""
Check all backup database files to find one with data
"""
import sqlite3
import os
import glob

print("=" * 70)
print("Backup Database Check")
print("=" * 70)
print()

backup_files = [
    'broken_backup_20250826_201756.db',
    'tablettracker.db',
    'tablettracker_backup_20250826_193645.db',
    'tablettracker_backup_20250826_195219.db'
]

for backup_file in backup_files:
    if not os.path.exists(backup_file):
        continue
    
    size = os.path.getsize(backup_file)
    print(f"\n📁 Checking: {backup_file} ({size:,} bytes)")
    print("-" * 70)
    
    try:
        conn = sqlite3.connect(backup_file)
        cursor = conn.cursor()
        
        # Get table list
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        
        total_rows = 0
        for table in tables:
            table_name = table[0]
            if table_name == 'sqlite_sequence':
                continue
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                total_rows += count
                if count > 0:
                    print(f"   ✅ {table_name}: {count:,} rows")
            except Exception as e:
                print(f"   ⚠️  {table_name}: Error - {e}")
        
        # Check warehouse_submissions specifically
        try:
            cursor.execute("SELECT COUNT(*) FROM warehouse_submissions")
            sub_count = cursor.fetchone()[0]
            if sub_count > 0:
                print(f"\n   🎯 Warehouse Submissions: {sub_count:,} records")
                # Get date range
                cursor.execute("SELECT MIN(created_at), MAX(created_at) FROM warehouse_submissions")
                date_range = cursor.fetchone()
                if date_range[0]:
                    print(f"   📅 Date range: {date_range[0]} to {date_range[1]}")
        except Exception as e:
            print(f"   ⚠️  warehouse_submissions table: {e}")
        
        print(f"\n   📊 Total rows across all tables: {total_rows:,}")
        
        conn.close()
        
    except Exception as e:
        print(f"   ❌ Error reading backup: {e}")
        import traceback
        traceback.print_exc()

print("\n" + "=" * 70)
print("Check complete!")
print("=" * 70)
print("\n💡 Look for the backup with the most warehouse_submissions records.")
print("   That's the one to restore from.")

