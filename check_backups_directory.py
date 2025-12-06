#!/usr/bin/env python3
import sqlite3
import os
from datetime import datetime

print("=" * 70)
print("CHECKING BACKUPS DIRECTORY")
print("=" * 70)

# First, list everything in backups/
if os.path.exists('backups'):
    print("\n📁 Files in backups/ directory:")
    for item in os.listdir('backups'):
        filepath = os.path.join('backups', item)
        if os.path.isfile(filepath):
            size = os.path.getsize(filepath)
            mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
            print(f"   - {item} ({size:,} bytes, modified: {mtime})")
    
    print("\n" + "=" * 70)
    print("ANALYZING BACKUP FILES")
    print("=" * 70)
    
    # Now check each .db file
    for item in os.listdir('backups'):
        filepath = os.path.join('backups', item)
        if item.endswith('.db') or 'backup' in item.lower():
            print(f"\n📁 {filepath}")
            
            try:
                conn = sqlite3.connect(filepath)
                cursor = conn.cursor()
                
                # Check warehouse_submissions
                try:
                    cursor.execute("SELECT COUNT(*) FROM warehouse_submissions")
                    ws_count = cursor.fetchone()[0]
                    print(f"   ✅ warehouse_submissions: {ws_count:,} rows")
                    
                    if ws_count > 0:
                        cursor.execute("SELECT MIN(submission_date), MAX(submission_date) FROM warehouse_submissions WHERE submission_date IS NOT NULL")
                        result = cursor.fetchone()
                        if result[0]:
                            print(f"   📅 Date range: {result[0]} to {result[1]}")
                except Exception as e:
                    print(f"   ⚠️  warehouse_submissions: {e}")
                
                # Check purchase_orders
                try:
                    cursor.execute("SELECT COUNT(*) FROM purchase_orders")
                    po_count = cursor.fetchone()[0]
                    print(f"   ✅ purchase_orders: {po_count:,} rows")
                except Exception as e:
                    print(f"   ⚠️  purchase_orders: {e}")
                
                # Check machine_counts
                try:
                    cursor.execute("SELECT COUNT(*) FROM machine_counts")
                    mc_count = cursor.fetchone()[0]
                    print(f"   ✅ machine_counts: {mc_count:,} rows")
                except Exception as e:
                    print(f"   ⚠️  machine_counts: {e}")
                
                conn.close()
            except Exception as e:
                print(f"   ❌ Error: {e}")
else:
    print("\n❌ No backups/ directory found")
