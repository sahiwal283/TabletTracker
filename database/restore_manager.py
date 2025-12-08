#!/usr/bin/env python3
"""
Database Restore Manager
Handles safe restoration of database backups with verification
"""
import sqlite3
import os
import shutil
import gzip
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
import hashlib


class RestoreManager:
    """Manages database restoration from backups"""
    
    def __init__(self, db_path: str = 'tablet_counter.db'):
        self.db_path = db_path
        self.backup_before_restore_dir = 'backups/before_restore'
        Path(self.backup_before_restore_dir).mkdir(parents=True, exist_ok=True)
    
    def list_available_backups(self) -> list:
        """List all available backups with details"""
        backups = []
        backup_dirs = ['backups/primary', 'backups/secondary', 'backups/archive']
        
        for backup_dir in backup_dirs:
            if not os.path.exists(backup_dir):
                continue
            
            for filename in os.listdir(backup_dir):
                if not filename.startswith('tablet_counter_'):
                    continue
                
                # Skip metadata and checksum files
                if filename.endswith(('.meta.json', '.sha256')):
                    continue
                
                filepath = os.path.join(backup_dir, filename)
                
                # Load metadata
                metadata_path = filepath + '.meta.json'
                metadata = {}
                if os.path.exists(metadata_path):
                    try:
                        with open(metadata_path, 'r') as f:
                            metadata = json.load(f)
                    except:
                        pass
                
                backups.append({
                    'filename': filename,
                    'path': filepath,
                    'directory': backup_dir,
                    'size_bytes': os.path.getsize(filepath),
                    'modified_time': os.path.getmtime(filepath),
                    'metadata': metadata
                })
        
        # Sort by modification time (newest first)
        backups.sort(key=lambda x: x['modified_time'], reverse=True)
        
        return backups
    
    def print_available_backups(self):
        """Print formatted list of available backups"""
        backups = self.list_available_backups()
        
        if not backups:
            print("No backups found!")
            return
        
        print("\n" + "=" * 100)
        print("AVAILABLE BACKUPS")
        print("=" * 100)
        print(f"{'#':<4} {'Date/Time':<20} {'Type':<10} {'Size':<12} {'Records':<15} {'Filename'}")
        print("-" * 100)
        
        for idx, backup in enumerate(backups[:30], 1):  # Show last 30
            timestamp = datetime.fromtimestamp(backup['modified_time'])
            date_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')
            size_kb = backup['size_bytes'] / 1024
            
            # Extract backup type from filename
            backup_type = 'unknown'
            for btype in ['hourly', 'daily', 'weekly', 'monthly', 'yearly']:
                if f'_{btype}_' in backup['filename']:
                    backup_type = btype
                    break
            
            # Get record count from metadata
            records = 'N/A'
            if backup['metadata'] and 'database_stats' in backup['metadata']:
                stats = backup['metadata']['database_stats']
                if 'tables' in stats and 'warehouse_submissions' in stats['tables']:
                    records = f"{stats['tables']['warehouse_submissions']:,}"
            
            print(f"{idx:<4} {date_str:<20} {backup_type:<10} {size_kb:>8.1f} KB  {records:<15} {backup['filename']}")
        
        if len(backups) > 30:
            print(f"\n... and {len(backups) - 30} more backups")
        
        print("=" * 100)
        print(f"Total: {len(backups)} backups available\n")
    
    def verify_backup(self, backup_path: str) -> Tuple[bool, str]:
        """Verify a backup file is valid"""
        try:
            # Decompress if needed
            temp_db_path = None
            if backup_path.endswith('.gz'):
                temp_db_path = backup_path[:-3] + '.verify_temp'
                with gzip.open(backup_path, 'rb') as f_in:
                    with open(temp_db_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                verify_path = temp_db_path
            else:
                verify_path = backup_path
            
            # Verify checksum if available
            checksum_path = backup_path + '.sha256'
            if os.path.exists(checksum_path):
                with open(checksum_path, 'r') as f:
                    expected_checksum = f.read().strip().split()[0]
                
                # Calculate actual checksum
                sha256_hash = hashlib.sha256()
                with open(backup_path, 'rb') as f:
                    for byte_block in iter(lambda: f.read(4096), b""):
                        sha256_hash.update(byte_block)
                actual_checksum = sha256_hash.hexdigest()
                
                if actual_checksum != expected_checksum:
                    if temp_db_path and os.path.exists(temp_db_path):
                        os.remove(temp_db_path)
                    return False, "Checksum mismatch - backup file may be corrupted"
            
            # Try to open and verify database
            conn = sqlite3.connect(verify_path)
            cursor = conn.cursor()
            
            # Run integrity check
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()[0]
            
            if result != 'ok':
                conn.close()
                if temp_db_path and os.path.exists(temp_db_path):
                    os.remove(temp_db_path)
                return False, f"Integrity check failed: {result}"
            
            # Get basic stats
            cursor.execute("SELECT COUNT(*) FROM warehouse_submissions")
            submission_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM purchase_orders")
            po_count = cursor.fetchone()[0]
            
            conn.close()
            
            # Cleanup temp file
            if temp_db_path and os.path.exists(temp_db_path):
                os.remove(temp_db_path)
            
            return True, f"Backup verified: {submission_count} submissions, {po_count} POs"
            
        except Exception as e:
            if temp_db_path and os.path.exists(temp_db_path):
                os.remove(temp_db_path)
            return False, f"Verification failed: {str(e)}"
    
    def backup_current_database(self) -> Optional[str]:
        """Create a backup of the current database before restoration"""
        if not os.path.exists(self.db_path):
            return None
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f'before_restore_{timestamp}.db'
        backup_path = os.path.join(self.backup_before_restore_dir, backup_filename)
        
        try:
            # Use SQLite backup API for safety
            source_conn = sqlite3.connect(self.db_path)
            backup_conn = sqlite3.connect(backup_path)
            
            with backup_conn:
                source_conn.backup(backup_conn)
            
            source_conn.close()
            backup_conn.close()
            
            return backup_path
        except Exception as e:
            print(f"Warning: Could not backup current database: {e}")
            return None
    
    def restore_from_backup(self, backup_path: str, force: bool = False) -> Tuple[bool, str]:
        """
        Restore database from a backup file
        
        Args:
            backup_path: Path to backup file
            force: Skip confirmation prompt
        
        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            print("\n" + "=" * 70)
            print("DATABASE RESTORATION")
            print("=" * 70)
            
            # Verify backup exists
            if not os.path.exists(backup_path):
                return False, f"Backup file not found: {backup_path}"
            
            # Verify backup
            print("\n1. Verifying backup file...")
            is_valid, verify_msg = self.verify_backup(backup_path)
            print(f"   {verify_msg}")
            
            if not is_valid and not force:
                return False, "Backup verification failed. Use --force to restore anyway."
            
            # Show backup metadata
            metadata_path = backup_path + '.meta.json'
            if os.path.exists(metadata_path):
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
                print("\n2. Backup Information:")
                print(f"   Created: {metadata.get('timestamp', 'Unknown')}")
                print(f"   Type: {metadata.get('type', 'Unknown')}")
                if 'database_stats' in metadata:
                    stats = metadata['database_stats']
                    print(f"   Database size: {stats.get('size_kb', 0):.1f} KB")
                    if 'tables' in stats:
                        print("   Records:")
                        for table, count in stats['tables'].items():
                            print(f"     - {table}: {count:,}")
            
            # Confirm restoration
            if not force:
                print("\n⚠️  WARNING: This will replace your current database!")
                response = input("\nType 'RESTORE' to confirm: ")
                if response != 'RESTORE':
                    return False, "Restoration cancelled by user"
            
            # Backup current database
            print("\n3. Backing up current database...")
            current_backup = self.backup_current_database()
            if current_backup:
                print(f"   ✓ Current database backed up to: {os.path.basename(current_backup)}")
            else:
                print("   ℹ No current database to backup")
            
            # Decompress if needed
            restore_source = backup_path
            temp_db_path = None
            if backup_path.endswith('.gz'):
                print("\n4. Decompressing backup...")
                temp_db_path = backup_path[:-3] + '.restore_temp'
                with gzip.open(backup_path, 'rb') as f_in:
                    with open(temp_db_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                restore_source = temp_db_path
                print("   ✓ Backup decompressed")
            
            # Perform restoration
            print(f"\n{'5' if backup_path.endswith('.gz') else '4'}. Restoring database...")
            shutil.copy2(restore_source, self.db_path)
            print(f"   ✓ Database restored from: {os.path.basename(backup_path)}")
            
            # Cleanup temp file
            if temp_db_path and os.path.exists(temp_db_path):
                os.remove(temp_db_path)
            
            # Verify restored database
            print(f"\n{'6' if backup_path.endswith('.gz') else '5'}. Verifying restored database...")
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("PRAGMA integrity_check")
            integrity_result = cursor.fetchone()[0]
            
            if integrity_result != 'ok':
                conn.close()
                return False, f"Restored database failed integrity check: {integrity_result}"
            
            cursor.execute("SELECT COUNT(*) FROM warehouse_submissions")
            submission_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM purchase_orders")
            po_count = cursor.fetchone()[0]
            
            conn.close()
            
            print(f"   ✓ Integrity check: OK")
            print(f"   ✓ Warehouse submissions: {submission_count:,}")
            print(f"   ✓ Purchase orders: {po_count:,}")
            
            print("\n" + "=" * 70)
            print("✅ RESTORATION COMPLETED SUCCESSFULLY!")
            print("=" * 70)
            print("\n⚠️  IMPORTANT: Restart your web application to use the restored database")
            if current_backup:
                print(f"\nℹ  Previous database saved to: {current_backup}")
            print()
            
            return True, "Database restored successfully"
            
        except Exception as e:
            print(f"\n✗ Restoration failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return False, f"Restoration failed: {str(e)}"


def main():
    """Main entry point for restore manager"""
    import sys
    
    manager = RestoreManager()
    
    if len(sys.argv) > 1 and sys.argv[1] == '--list':
        manager.print_available_backups()
    elif len(sys.argv) > 1 and sys.argv[1] == '--interactive':
        # Interactive restoration
        manager.print_available_backups()
        
        try:
            selection = input("\nEnter backup number to restore (or 'q' to quit): ")
            if selection.lower() == 'q':
                print("Cancelled")
                sys.exit(0)
            
            backup_idx = int(selection) - 1
            backups = manager.list_available_backups()
            
            if backup_idx < 0 or backup_idx >= len(backups):
                print("Invalid selection")
                sys.exit(1)
            
            selected_backup = backups[backup_idx]
            success, message = manager.restore_from_backup(selected_backup['path'])
            sys.exit(0 if success else 1)
            
        except (ValueError, KeyboardInterrupt):
            print("\nCancelled")
            sys.exit(1)
    elif len(sys.argv) > 1:
        # Direct restoration
        backup_path = sys.argv[1]
        force = '--force' in sys.argv
        success, message = manager.restore_from_backup(backup_path, force)
        sys.exit(0 if success else 1)
    else:
        print("Usage:")
        print("  restore_manager.py --list              List available backups")
        print("  restore_manager.py --interactive       Interactive restore")
        print("  restore_manager.py <backup_path>       Restore specific backup")
        print("  restore_manager.py <backup_path> --force  Restore without verification")
        sys.exit(1)


if __name__ == '__main__':
    main()

