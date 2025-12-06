#!/usr/bin/env python3
"""
Try to recover data - check for other database files or PythonAnywhere backups
"""
import os
import glob
import sqlite3
from datetime import datetime

print("=" * 70)
print("Data Recovery Script")
print("=" * 70)
print()

# Check current database modification time
current_db = 'tablet_counter.db'
if os.path.exists(current_db):
    mtime = os.path.getmtime(current_db)
    mod_time = datetime.fromtimestamp(mtime)
    print(f"📅 Current database last modified: {mod_time}")
    print(f"   File size: {os.path.getsize(current_db):,} bytes")
    print()

# Search for ALL database files recursively
print("🔍 Searching for all .db files in project directory...")
db_files = []
for root, dirs, files in os.walk('.'):
    # Skip hidden directories and __pycache__
    dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
    for file in files:
        if file.endswith('.db'):
            full_path = os.path.join(root, file)
            size = os.path.getsize(full_path)
            mtime = os.path.getmtime(full_path)
            mod_time = datetime.fromtimestamp(mtime)
            db_files.append((full_path, size, mod_time))

if db_files:
    print(f"\n   Found {len(db_files)} database files:")
    # Sort by modification time (newest first)
    db_files.sort(key=lambda x: x[2], reverse=True)
    for db_file, size, mod_time in db_files:
        print(f"   - {db_file}")
        print(f"     Size: {size:,} bytes | Modified: {mod_time}")
        
        # Quick check for submissions
        try:
            conn = sqlite3.connect(db_file)
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT COUNT(*) FROM warehouse_submissions")
                count = cursor.fetchone()[0]
                if count > 0:
                    print(f"     🎯 HAS {count:,} SUBMISSIONS!")
            except:
                pass
            conn.close()
        except:
            pass
        print()
else:
    print("   No .db files found")

# Check for PythonAnywhere backup directories
print("\n🔍 Checking for PythonAnywhere backup directories...")
backup_dirs = [
    '~/backups',
    '~/backup',
    '../backups',
    '../backup'
]
for backup_dir in backup_dirs:
    expanded = os.path.expanduser(backup_dir)
    if os.path.exists(expanded):
        print(f"   ✅ Found: {expanded}")
        # List files
        try:
            files = os.listdir(expanded)
            db_backups = [f for f in files if f.endswith('.db')]
            if db_backups:
                print(f"      Database backups found: {len(db_backups)}")
                for f in db_backups[:5]:  # Show first 5
                    print(f"      - {f}")
        except:
            pass

# Check if there's a .git directory with database files (shouldn't be, but check)
print("\n🔍 Checking git history for database files...")
print("   (This would show if database was ever committed - it shouldn't be)")

print("\n" + "=" * 70)
print("Recovery Options:")
print("=" * 70)
print("1. Check PythonAnywhere file system backups:")
print("   - Go to PythonAnywhere → Files tab")
print("   - Look for backup/restore options")
print("   - PythonAnywhere may have automatic file backups")
print()
print("2. Check if database was moved:")
print("   - Search for 'tablet_counter.db' in other locations")
print("   - Check if there's a different database path in config")
print()
print("3. Check error logs for clues:")
print("   - Look at PythonAnywhere error logs")
print("   - See if there were any database operations before data disappeared")
print()
print("4. Check if data is in a different table:")
print("   - The old code might use different table names")

