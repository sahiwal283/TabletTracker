#!/usr/bin/env python3
"""
Restore production data from old database location to new Alembic-managed database
"""
import sqlite3
import shutil
import os
from datetime import datetime

def restore_production_data():
    old_db = 'tablet_counter.db'  # Old location (root)
    new_db = 'database/tablet_counter.db'  # New location (Alembic)
    backup_db = f'tablet_counter_backup_before_restore_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
    
    print("=" * 80)
    print("RESTORE PRODUCTION DATA TO ALEMBIC DATABASE")
    print("=" * 80)
    print()
    
    # Step 1: Check old database exists
    print("STEP 1: Checking old database...")
    print("-" * 80)
    
    if not os.path.exists(old_db):
        print(f"❌ Old database not found: {old_db}")
        print("   If you already moved it, check if it's in database/ directory")
        return False
    
    # Get old database stats
    old_conn = sqlite3.connect(old_db)
    old_cursor = old_conn.cursor()
    
    old_cursor.execute("SELECT COUNT(*) FROM warehouse_submissions")
    submissions = old_cursor.fetchone()[0]
    
    old_cursor.execute("SELECT COUNT(*) FROM purchase_orders")
    pos = old_cursor.fetchone()[0]
    
    old_cursor.execute("SELECT COUNT(*) FROM employees")
    employees = old_cursor.fetchone()[0]
    
    old_size = os.path.getsize(old_db) / 1024
    
    print(f"✓ Old database found: {old_size:.1f} KB")
    print(f"  • Submissions: {submissions}")
    print(f"  • Purchase Orders: {pos}")
    print(f"  • Employees: {employees}")
    
    old_conn.close()
    print()
    
    # Step 2: Backup new database (just in case)
    print("STEP 2: Backing up new database...")
    print("-" * 80)
    
    if os.path.exists(new_db):
        shutil.copy2(new_db, backup_db)
        new_size = os.path.getsize(new_db) / 1024
        print(f"✓ New database backed up to: {backup_db} ({new_size:.1f} KB)")
    else:
        print("  ℹ New database doesn't exist yet (will be created)")
    
    print()
    
    # Step 3: Copy old database to new location
    print("STEP 3: Copying old database to new location...")
    print("-" * 80)
    
    # Ensure database directory exists
    os.makedirs('database', exist_ok=True)
    
    # Copy the database
    shutil.copy2(old_db, new_db)
    print(f"✓ Copied {old_db} → {new_db}")
    print()
    
    # Step 4: Verify data copied
    print("STEP 4: Verifying data...")
    print("-" * 80)
    
    new_conn = sqlite3.connect(new_db)
    new_cursor = new_conn.cursor()
    
    new_cursor.execute("SELECT COUNT(*) FROM warehouse_submissions")
    new_submissions = new_cursor.fetchone()[0]
    
    new_cursor.execute("SELECT COUNT(*) FROM purchase_orders")
    new_pos = new_cursor.fetchone()[0]
    
    new_cursor.execute("SELECT COUNT(*) FROM employees")
    new_employees = new_cursor.fetchone()[0]
    
    print(f"✓ Data verified in new database:")
    print(f"  • Submissions: {new_submissions}")
    print(f"  • Purchase Orders: {new_pos}")
    print(f"  • Employees: {new_employees}")
    
    if new_submissions == submissions and new_pos == pos:
        print("  ✅ Data counts match!")
    else:
        print("  ⚠️  Data counts don't match - investigate!")
    
    print()
    
    # Step 5: Check Alembic version table
    print("STEP 5: Checking Alembic migration status...")
    print("-" * 80)
    
    try:
        new_cursor.execute("SELECT * FROM alembic_version")
        alembic_version = new_cursor.fetchone()
        if alembic_version:
            print(f"✓ Alembic version table exists: {alembic_version[0]}")
        else:
            print("⚠️  Alembic version table is empty")
    except sqlite3.OperationalError:
        print("⚠️  Alembic version table not found - migrations may need to run")
        print("   This is OK if the old database didn't use Alembic")
    
    new_conn.close()
    print()
    
    # Step 6: Run Alembic migrations (if needed)
    print("STEP 6: Running Alembic migrations...")
    print("-" * 80)
    print("   Run this command manually:")
    print("   alembic upgrade head")
    print()
    print("   This will ensure the schema matches the refactored code")
    print()
    
    print("=" * 80)
    print("✅ RESTORATION COMPLETE")
    print("=" * 80)
    print()
    print("Next Steps:")
    print("1. Run: alembic upgrade head")
    print("2. Verify data is still intact")
    print("3. Reload web app")
    print("4. Test the application")
    print()
    print(f"Backup saved: {backup_db}")
    print("=" * 80)
    
    return True

if __name__ == '__main__':
    restore_production_data()
