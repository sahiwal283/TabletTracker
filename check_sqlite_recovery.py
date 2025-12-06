#!/usr/bin/env python3
"""
Check SQLite recovery options - look for journal files and check database integrity
"""
import os
import sqlite3
import glob

print("=" * 70)
print("SQLite Recovery Check")
print("=" * 70)
print()

db_file = 'tablet_counter.db'

# Check for SQLite journal files (these can help recover data)
print("1. Checking for SQLite journal files...")
journal_files = [
    f'{db_file}-journal',
    f'{db_file}-wal',
    f'{db_file}-shm',
    '.tablet_counter.db-journal',
    '.tablet_counter.db-wal',
    '.tablet_counter.db-shm'
]

found_journals = []
for journal in journal_files:
    if os.path.exists(journal):
        size = os.path.getsize(journal)
        found_journals.append((journal, size))
        print(f"   ✅ Found: {journal} ({size:,} bytes)")
        print(f"      ⚠️  This might contain uncommitted data!")

if not found_journals:
    print("   ❌ No journal files found")

# Check database integrity
print("\n2. Checking database integrity...")
try:
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    
    # Run integrity check
    cursor.execute("PRAGMA integrity_check")
    result = cursor.fetchone()
    if result[0] == 'ok':
        print("   ✅ Database integrity: OK")
    else:
        print(f"   ⚠️  Database integrity issues: {result[0]}")
    
    # Check if there are any deleted pages (might be recoverable)
    cursor.execute("PRAGMA page_count")
    page_count = cursor.fetchone()[0]
    cursor.execute("PRAGMA freelist_count")
    free_pages = cursor.fetchone()[0]
    
    print(f"   📄 Total pages: {page_count}")
    print(f"   🗑️  Free pages (deleted): {free_pages}")
    
    if free_pages > 0:
        print(f"      ⚠️  There are {free_pages} free pages - data might be recoverable!")
    
    conn.close()
except Exception as e:
    print(f"   ❌ Error checking database: {e}")

# Check if database was recently modified
print("\n3. Checking database modification time...")
if os.path.exists(db_file):
    import time
    from datetime import datetime
    mtime = os.path.getmtime(db_file)
    mod_time = datetime.fromtimestamp(mtime)
    now = datetime.now()
    age = now - mod_time
    
    print(f"   📅 Last modified: {mod_time}")
    print(f"   ⏰ Age: {age}")
    
    if age.total_seconds() < 3600:  # Less than 1 hour
        print(f"      ⚠️  Database was modified very recently!")
        print(f"      This suggests data was lost during the rollback/reload")

# Check for SQLite recovery tools
print("\n4. Recovery options:")
print("   💡 If journal files exist, you might be able to recover data")
print("   💡 SQLite has a .recover command that can extract data from corrupted databases")
print("   💡 Check PythonAnywhere file backups in the Files tab")

print("\n" + "=" * 70)
print("Next Steps:")
print("=" * 70)
print("1. Check PythonAnywhere Files tab for automatic backups")
print("2. If journal files exist, we might be able to recover data")
print("3. Check error logs to see when init_db() was called")
print("4. The data might be in a different database file location")

