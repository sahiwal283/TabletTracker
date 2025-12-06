#!/usr/bin/env python3
"""
Restore database from a backup file
Usage: python3 restore_from_backup.py <backup_file.db>
"""
import sqlite3
import sys
import os
import shutil
from datetime import datetime

if len(sys.argv) < 2:
    print("Usage: python3 restore_from_backup.py <backup_file.db>")
    print("\nAvailable backups:")
    backups = [
        'broken_backup_20250826_201756.db',
        'tablettracker.db',
        'tablettracker_backup_20250826_193645.db',
        'tablettracker_backup_20250826_195219.db'
    ]
    for backup in backups:
        if os.path.exists(backup):
            size = os.path.getsize(backup)
            print(f"  - {backup} ({size:,} bytes)")
    sys.exit(1)

backup_file = sys.argv[1]

if not os.path.exists(backup_file):
    print(f"❌ Backup file not found: {backup_file}")
    sys.exit(1)

print("=" * 70)
print("Database Restore Script")
print("=" * 70)
print()

# Create backup of current database
current_db = 'tablet_counter.db'
if os.path.exists(current_db):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f'tablet_counter_backup_before_restore_{timestamp}.db'
    print(f"1. Creating backup of current database...")
    shutil.copy2(current_db, backup_name)
    print(f"   ✅ Current database backed up to: {backup_name}")

# Check backup file has data
print(f"\n2. Checking backup file: {backup_file}")
try:
    conn = sqlite3.connect(backup_file)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM warehouse_submissions")
    count = cursor.fetchone()[0]
    print(f"   ✅ Found {count:,} warehouse submissions in backup")
    conn.close()
except Exception as e:
    print(f"   ⚠️  Warning: Could not verify backup file: {e}")
    response = input("   Continue anyway? (yes/no): ")
    if response.lower() != 'yes':
        print("   Restore cancelled.")
        sys.exit(1)

# Restore
print(f"\n3. Restoring from backup...")
print(f"   Source: {backup_file}")
print(f"   Target: {current_db}")

try:
    # Copy backup to current database
    shutil.copy2(backup_file, current_db)
    print(f"   ✅ Database restored successfully!")
    
    # Verify restore
    print(f"\n4. Verifying restored database...")
    conn = sqlite3.connect(current_db)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM warehouse_submissions")
    count = cursor.fetchone()[0]
    print(f"   ✅ Warehouse submissions: {count:,} records")
    
    cursor.execute("SELECT COUNT(*) FROM purchase_orders")
    po_count = cursor.fetchone()[0]
    print(f"   ✅ Purchase orders: {po_count:,} records")
    
    conn.close()
    
    print("\n" + "=" * 70)
    print("✅ Restore completed successfully!")
    print("=" * 70)
    print("\n⚠️  IMPORTANT: Reload your web app in PythonAnywhere dashboard")
    print("   The restored database should now be accessible.")
    
except Exception as e:
    print(f"   ❌ Error during restore: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

