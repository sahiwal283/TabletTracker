#!/usr/bin/env python3
import sqlite3
import os

backups = [
    'tablet_counter.db.backup_20251030_001520',
    'backups/tablet_counter.db.backup_20251104_165629',
    'tablet_counter.db.BROKEN_BACKUP'
]

print("=" * 70)
print("CHECKING HIDDEN BACKUP FILES")
print("=" * 70)

for backup in backups:
    print(f"\n📁 {backup}")
    if not os.path.exists(backup):
        print(f"   ❌ File not found")
        continue
    
    size = os.path.getsize(backup)
    print(f"   Size: {size:,} bytes")
    
    try:
        conn = sqlite3.connect(backup)
        cursor = conn.cursor()
        
        # Check warehouse_submissions
        try:
            cursor.execute("SELECT COUNT(*) FROM warehouse_submissions")
            ws_count = cursor.fetchone()[0]
            print(f"   ✅ warehouse_submissions: {ws_count:,} rows")
            
            if ws_count > 0:
                cursor.execute("SELECT MIN(submission_date), MAX(submission_date) FROM warehouse_submissions")
                min_date, max_date = cursor.fetchone()
                print(f"   📅 Date range: {min_date} to {max_date}")
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
        
        # Check receiving
        try:
            cursor.execute("SELECT COUNT(*) FROM receiving")
            recv_count = cursor.fetchone()[0]
            print(f"   ✅ receiving: {recv_count:,} rows")
        except Exception as e:
            print(f"   ⚠️  receiving: {e}")
        
        conn.close()
    except Exception as e:
        print(f"   ❌ Error: {e}")
