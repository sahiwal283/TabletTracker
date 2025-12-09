#!/usr/bin/env python3
"""
Check if automated backups are running on schedule
"""
import os
import json
from datetime import datetime, timedelta
from pathlib import Path

def check_backup_schedule():
    print("=" * 80)
    print("AUTOMATED BACKUP SCHEDULE CHECK")
    print("=" * 80)
    print(f"Current Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Check backup directories
    backup_dirs = ['backups/primary', 'backups/secondary']
    
    for backup_dir in backup_dirs:
        if not os.path.exists(backup_dir):
            print(f"⚠️  Directory not found: {backup_dir}")
            continue
        
        print(f"\n{backup_dir.upper()}:")
        print("-" * 80)
        
        # Get all backup files
        backups = []
        for filename in os.listdir(backup_dir):
            if filename.startswith('tablet_counter_') and filename.endswith('.db.gz'):
                filepath = os.path.join(backup_dir, filename)
                mtime = os.path.getmtime(filepath)
                backups.append({
                    'filename': filename,
                    'filepath': filepath,
                    'mtime': mtime,
                    'datetime': datetime.fromtimestamp(mtime)
                })
        
        # Sort by modification time (newest first)
        backups.sort(key=lambda x: x['mtime'], reverse=True)
        
        if not backups:
            print("⚠️  No backups found!")
            continue
        
        # Show last 5 backups
        print(f"Found {len(backups)} total backups. Recent backups:")
        print()
        for i, backup in enumerate(backups[:5], 1):
            age = datetime.now() - backup['datetime']
            age_str = f"{age.days}d {age.seconds//3600}h ago" if age.days > 0 else f"{age.seconds//3600}h {(age.seconds%3600)//60}m ago"
            size_kb = os.path.getsize(backup['filepath']) / 1024
            print(f"  {i}. {backup['datetime'].strftime('%Y-%m-%d %H:%M:%S')} ({age_str})")
            print(f"     {backup['filename']} ({size_kb:.1f} KB)")
        
        # Check for today's backup
        print()
        today = datetime.now().date()
        todays_backups = [b for b in backups if b['datetime'].date() == today]
        
        if todays_backups:
            print(f"✅ Found {len(todays_backups)} backup(s) created TODAY:")
            for backup in todays_backups:
                print(f"   • {backup['datetime'].strftime('%H:%M:%S')} - {backup['filename']}")
        else:
            print("⚠️  No backups created today yet")
            
            # Check if we're past the scheduled time (07:59 UTC)
            now_utc = datetime.utcnow()
            scheduled_time = now_utc.replace(hour=7, minute=59, second=0, microsecond=0)
            
            if now_utc > scheduled_time:
                print(f"   ⚠️  WARNING: Scheduled backup time (07:59 UTC) has passed!")
                print(f"   Current UTC time: {now_utc.strftime('%H:%M:%S')}")
            else:
                time_until = scheduled_time - now_utc
                hours = int(time_until.total_seconds() // 3600)
                minutes = int((time_until.total_seconds() % 3600) // 60)
                print(f"   ℹ️  Scheduled backup in {hours}h {minutes}m (at 07:59 UTC)")
    
    # Check health log
    print("\n" + "=" * 80)
    print("BACKUP HEALTH STATUS:")
    print("-" * 80)
    
    health_log = 'backups/backup_health.json'
    if os.path.exists(health_log):
        try:
            with open(health_log, 'r') as f:
                health = json.load(f)
            
            last_backup = health.get('last_backup_time', 'Unknown')
            last_success = health.get('last_backup_success', False)
            failures = health.get('consecutive_failures', 0)
            
            if last_backup != 'Unknown':
                last_dt = datetime.fromisoformat(last_backup)
                age = datetime.now() - last_dt
                age_str = f"{age.days}d {age.seconds//3600}h ago" if age.days > 0 else f"{age.seconds//3600}h {(age.seconds%3600)//60}m ago"
                print(f"Last Backup: {last_dt.strftime('%Y-%m-%d %H:%M:%S')} ({age_str})")
            else:
                print(f"Last Backup: {last_backup}")
            
            status_icon = "✅" if last_success else "❌"
            print(f"Last Status: {status_icon} {'Success' if last_success else 'Failed'}")
            
            if failures > 0:
                print(f"⚠️  Consecutive Failures: {failures}")
            else:
                print(f"Consecutive Failures: {failures}")
                
        except Exception as e:
            print(f"⚠️  Could not read health log: {e}")
    else:
        print("ℹ️  No health log found")
    
    # Check scheduled task status (PythonAnywhere specific)
    print("\n" + "=" * 80)
    print("SCHEDULED TASK INFO:")
    print("-" * 80)
    print("Expected schedule: Daily at 07:59 UTC (2:59 AM EST)")
    print("Command: /home/sahilk1/TabletTracker/venv/bin/python3")
    print("         /home/sahilk1/TabletTracker/database/backup_manager.py --daily")
    print()
    print("To verify the task is scheduled in PythonAnywhere:")
    print("  1. Go to PythonAnywhere Dashboard → Tasks tab")
    print("  2. Check if the daily backup task is listed and enabled")
    print()
    
    print("=" * 80)

if __name__ == '__main__':
    check_backup_schedule()

