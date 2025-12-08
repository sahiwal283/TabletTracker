#!/usr/bin/env python3
"""
One-time setup script for backup system
Initializes directories and creates first backup
"""
import os
import sys
from pathlib import Path


def setup_backup_system():
    """Initialize the backup system"""
    print("=" * 70)
    print("BACKUP SYSTEM SETUP")
    print("=" * 70)
    print()
    
    # Create backup directories
    print("1. Creating backup directories...")
    directories = [
        'backups',
        'backups/primary',
        'backups/secondary',
        'backups/archive',
        'backups/before_restore'
    ]
    
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)
        print(f"   ✓ {directory}")
    
    # Check if database exists
    print("\n2. Checking database...")
    if not os.path.exists('tablet_counter.db'):
        print("   ⚠️  Database not found. It will be created when the app runs.")
    else:
        size = os.path.getsize('tablet_counter.db') / 1024
        print(f"   ✓ Database found ({size:.1f} KB)")
    
    # Create initial backup
    print("\n3. Creating initial backup...")
    if os.path.exists('tablet_counter.db'):
        try:
            # Import backup manager
            import sys
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from database.backup_manager import BackupManager
            manager = BackupManager()
            success, message = manager.create_backup('daily')
            if success:
                print("   ✓ Initial backup created successfully")
            else:
                print(f"   ✗ Initial backup failed: {message}")
        except Exception as e:
            print(f"   ⊘ Skipping initial backup (run manually): {str(e)}")
            print("      Run: python3 database/backup_manager.py --daily")
    else:
        print("   ⊘ Skipped (no database yet)")
    
    # Set up automated backups
    print("\n4. Setting up automated backups...")
    print("   Run this command to schedule automated backups:")
    print()
    print("   ./database/schedule_backups.sh")
    print()
    
    # Create .gitignore for backups
    print("5. Creating .gitignore for backups...")
    gitignore_path = 'backups/.gitignore'
    gitignore_content = """# Ignore all backup files
*.db
*.db.gz
*.sha256
*.meta.json
*.log
*.json

# Keep directory structure
!.gitignore
!README.md
"""
    
    Path('backups').mkdir(parents=True, exist_ok=True)
    with open(gitignore_path, 'w') as f:
        f.write(gitignore_content)
    print(f"   ✓ Created {gitignore_path}")
    
    # Show status
    print("\n" + "=" * 70)
    print("✅ BACKUP SYSTEM SETUP COMPLETE")
    print("=" * 70)
    print()
    print("Next Steps:")
    print()
    print("1. Schedule automated backups:")
    print("   ./database/schedule_backups.sh")
    print()
    print("2. Check backup status:")
    print("   python3 database/backup_manager.py --status")
    print()
    print("3. Run health check:")
    print("   python3 database/health_check.py")
    print()
    print("4. View backups:")
    print("   python3 database/backup_manager.py --list")
    print()
    print("5. Test restoration (optional):")
    print("   python3 database/restore_manager.py --list")
    print()
    print("See database/README.md for complete documentation")
    print("=" * 70)
    print()


if __name__ == '__main__':
    setup_backup_system()

