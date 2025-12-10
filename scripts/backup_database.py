#!/usr/bin/env python3
"""
Automated Database Backup Script
Runs daily on PythonAnywhere to create timestamped backups

Schedule this in PythonAnywhere:
1. Go to "Tasks" tab
2. Add scheduled task: /home/sahilk1/TabletTracker/backup_database.py
3. Set to run daily at a quiet time (e.g., 3:00 AM UTC)
"""
import sqlite3
import shutil
import os
from datetime import datetime, timedelta
from pathlib import Path

# Configuration
DB_PATH = 'tablet_counter.db'
BACKUP_DIR = 'backups'
KEEP_DAYS = 30  # Keep 30 days of backups
KEEP_MONTHLY = 12  # Keep 12 monthly backups

def create_backup():
    """Create a timestamped backup of the database"""
    try:
        # Ensure backup directory exists
        Path(BACKUP_DIR).mkdir(exist_ok=True)
        
        # Generate timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f'tablet_counter.db.backup_{timestamp}'
        backup_path = os.path.join(BACKUP_DIR, backup_filename)
        
        # Check if database exists
        if not os.path.exists(DB_PATH):
            print(f"✗ Database file not found: {DB_PATH}")
            return False
        
        # Get database stats before backup
        db_size = os.path.getsize(DB_PATH)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM warehouse_submissions")
        submission_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM purchase_orders")
        po_count = cursor.fetchone()[0]
        conn.close()
        
        print("=" * 60)
        print(f"Database Backup - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
        print(f"Database size: {db_size / 1024:.1f} KB")
        print(f"Submissions: {submission_count}")
        print(f"Purchase Orders: {po_count}")
        
        # Create backup using SQLite backup API (safer than file copy)
        source_conn = sqlite3.connect(DB_PATH)
        backup_conn = sqlite3.connect(backup_path)
        
        with backup_conn:
            source_conn.backup(backup_conn)
        
        source_conn.close()
        backup_conn.close()
        
        # Verify backup
        if os.path.exists(backup_path):
            backup_size = os.path.getsize(backup_path)
            print(f"\n✓ Backup created: {backup_filename}")
            print(f"  Backup size: {backup_size / 1024:.1f} KB")
        else:
            print(f"\n✗ Backup failed: File not created")
            return False
        
        # Cleanup old backups
        cleanup_old_backups()
        
        print("=" * 60)
        return True
        
    except Exception as e:
        print(f"\n✗ Backup failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def cleanup_old_backups():
    """Remove old backups based on retention policy"""
    try:
        print("\nCleaning up old backups...")
        
        if not os.path.exists(BACKUP_DIR):
            return
        
        # Get all backup files
        backup_files = []
        for filename in os.listdir(BACKUP_DIR):
            if filename.startswith('tablet_counter.db.backup_'):
                filepath = os.path.join(BACKUP_DIR, filename)
                mtime = os.path.getmtime(filepath)
                backup_files.append((filepath, mtime, filename))
        
        # Sort by modification time (newest first)
        backup_files.sort(key=lambda x: x[1], reverse=True)
        
        cutoff_date = datetime.now() - timedelta(days=KEEP_DAYS)
        cutoff_timestamp = cutoff_date.timestamp()
        
        kept_daily = 0
        kept_monthly = 0
        deleted = 0
        monthly_backups = set()
        
        for filepath, mtime, filename in backup_files:
            file_date = datetime.fromtimestamp(mtime)
            month_key = file_date.strftime('%Y-%m')
            
            # Keep all backups from the last KEEP_DAYS days
            if mtime >= cutoff_timestamp:
                kept_daily += 1
                continue
            
            # Keep one backup per month for KEEP_MONTHLY months
            if month_key not in monthly_backups and len(monthly_backups) < KEEP_MONTHLY:
                monthly_backups.add(month_key)
                kept_monthly += 1
                continue
            
            # Delete old backups
            try:
                os.remove(filepath)
                deleted += 1
            except Exception as e:
                print(f"  ⚠ Could not delete {filename}: {e}")
        
        print(f"  ✓ Kept {kept_daily} daily backups (last {KEEP_DAYS} days)")
        print(f"  ✓ Kept {kept_monthly} monthly backups")
        if deleted > 0:
            print(f"  ✓ Deleted {deleted} old backup(s)")
        
    except Exception as e:
        print(f"  ⚠ Cleanup warning: {e}")

def list_backups():
    """List all available backups"""
    try:
        if not os.path.exists(BACKUP_DIR):
            print("No backups directory found")
            return
        
        backup_files = []
        for filename in os.listdir(BACKUP_DIR):
            if filename.startswith('tablet_counter.db.backup_'):
                filepath = os.path.join(BACKUP_DIR, filename)
                mtime = os.path.getmtime(filepath)
                size = os.path.getsize(filepath)
                backup_files.append((filename, mtime, size))
        
        if not backup_files:
            print("No backups found")
            return
        
        backup_files.sort(key=lambda x: x[1], reverse=True)
        
        print("\nAvailable Backups:")
        print("-" * 60)
        for filename, mtime, size in backup_files[:10]:  # Show last 10
            date_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
            size_kb = size / 1024
            print(f"{date_str} | {size_kb:6.1f} KB | {filename}")
        
        if len(backup_files) > 10:
            print(f"... and {len(backup_files) - 10} more backups")
        print("-" * 60)
        print(f"Total: {len(backup_files)} backups")
        
    except Exception as e:
        print(f"Error listing backups: {e}")

if __name__ == '__main__':
    import sys
    
    # Support --list flag to view backups
    if len(sys.argv) > 1 and sys.argv[1] == '--list':
        list_backups()
    else:
        success = create_backup()
        sys.exit(0 if success else 1)

