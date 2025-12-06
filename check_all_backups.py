#!/usr/bin/env python3
"""
Check all database backup files to find which one contains data
"""
import sqlite3
import os
from datetime import datetime

print("=" * 70)
print("Checking All Database Backups for Data")
print("=" * 70)
print()

# List of database files to check
db_files = [
    'broken_backup_20250826_201756.db',
    'tablet_counter.db',
    'tablettracker.db',
    'tablettracker_backup_20250826_193645.db',
    'tablettracker_backup_20250826_195219.db'
]

results = []

for db_file in db_files:
    if not os.path.exists(db_file):
        print(f"⏭️  {db_file} - NOT FOUND")
        continue
    
    try:
        # Get file stats
        stats = os.stat(db_file)
        size = stats.st_size
        mod_time = datetime.fromtimestamp(stats.st_mtime)
        
        print(f"\n📁 {db_file}")
        print(f"   Size: {size:,} bytes")
        print(f"   Modified: {mod_time}")
        
        # Connect and check data
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        # Check for warehouse_submissions table and count
        try:
            cursor.execute("SELECT COUNT(*) FROM warehouse_submissions")
            ws_count = cursor.fetchone()[0]
            print(f"   ✅ warehouse_submissions: {ws_count:,} rows")
            
            # Get date range of submissions
            if ws_count > 0:
                cursor.execute("SELECT MIN(submission_date), MAX(submission_date) FROM warehouse_submissions")
                min_date, max_date = cursor.fetchone()
                print(f"   📅 Date range: {min_date} to {max_date}")
        except sqlite3.OperationalError as e:
            print(f"   ⚠️  warehouse_submissions: {e}")
            ws_count = 0
        
        # Check for purchase_orders
        try:
            cursor.execute("SELECT COUNT(*) FROM purchase_orders")
            po_count = cursor.fetchone()[0]
            print(f"   ✅ purchase_orders: {po_count:,} rows")
        except sqlite3.OperationalError as e:
            print(f"   ⚠️  purchase_orders: {e}")
            po_count = 0
        
        # Check for machine_counts
        try:
            cursor.execute("SELECT COUNT(*) FROM machine_counts")
            mc_count = cursor.fetchone()[0]
            print(f"   ✅ machine_counts: {mc_count:,} rows")
        except sqlite3.OperationalError as e:
            print(f"   ⚠️  machine_counts: {e}")
            mc_count = 0
        
        # Check for receiving
        try:
            cursor.execute("SELECT COUNT(*) FROM receiving")
            recv_count = cursor.fetchone()[0]
            print(f"   ✅ receiving: {recv_count:,} rows")
        except sqlite3.OperationalError as e:
            print(f"   ⚠️  receiving: {e}")
            recv_count = 0
        
        conn.close()
        
        results.append({
            'file': db_file,
            'size': size,
            'modified': mod_time,
            'ws_count': ws_count,
            'po_count': po_count,
            'mc_count': mc_count,
            'recv_count': recv_count,
            'total': ws_count + po_count + mc_count + recv_count
        })
        
    except Exception as e:
        print(f"   ❌ Error: {e}")

print("\n" + "=" * 70)
print("Summary - Ranked by Total Data")
print("=" * 70)

# Sort by total data
results.sort(key=lambda x: x['total'], reverse=True)

for i, result in enumerate(results, 1):
    print(f"\n{i}. {result['file']}")
    print(f"   Modified: {result['modified']}")
    print(f"   Total rows: {result['total']:,}")
    print(f"   - Warehouse submissions: {result['ws_count']:,}")
    print(f"   - Purchase orders: {result['po_count']:,}")
    print(f"   - Machine counts: {result['mc_count']:,}")
    print(f"   - Receiving records: {result['recv_count']:,}")

if results and results[0]['total'] > 0:
    best = results[0]
    print("\n" + "=" * 70)
    print("🎯 RECOMMENDATION")
    print("=" * 70)
    print(f"✅ Best backup: {best['file']}")
    print(f"   Modified: {best['modified']}")
    print(f"   Total data: {best['total']:,} rows")
    print(f"\nTo restore this backup, run:")
    print(f"   python3 restore_from_backup.py {best['file']}")
else:
    print("\n❌ No backups found with data")
    print("   Data may be permanently lost")

