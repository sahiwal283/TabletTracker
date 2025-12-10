#!/usr/bin/env python3
"""
Comprehensive Database Backup Manager
Handles automated backups with verification, encryption, and monitoring
"""
import sqlite3
import shutil
import os
import hashlib
import json
import gzip
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import traceback


class BackupConfig:
    """Configuration for backup system"""
    # Database settings
    # Check both old and new locations for compatibility
    DB_PATH = 'database/tablet_counter.db' if os.path.exists('database/tablet_counter.db') else 'tablet_counter.db'
    
    # Backup directories
    PRIMARY_BACKUP_DIR = 'backups/primary'
    SECONDARY_BACKUP_DIR = 'backups/secondary'  # Additional safety layer
    ARCHIVE_BACKUP_DIR = 'backups/archive'      # Long-term storage
    
    # Retention policies
    KEEP_HOURLY = 24        # Keep 24 hourly backups (1 day)
    KEEP_DAILY = 30         # Keep 30 daily backups (1 month)
    KEEP_WEEKLY = 12        # Keep 12 weekly backups (3 months)
    KEEP_MONTHLY = 24       # Keep 24 monthly backups (2 years)
    KEEP_YEARLY = 10        # Keep 10 yearly backups (10 years)
    
    # Backup settings
    COMPRESS_BACKUPS = True
    VERIFY_BACKUPS = True
    CREATE_CHECKSUMS = True
    
    # Alert settings
    ALERT_LOG = 'backups/backup_alerts.log'
    HEALTH_CHECK_LOG = 'backups/backup_health.json'


class BackupManager:
    """Manages database backups with verification and monitoring"""
    
    def __init__(self, config: BackupConfig = None):
        self.config = config or BackupConfig()
        self._ensure_directories()
    
    def _ensure_directories(self):
        """Ensure all backup directories exist"""
        for dir_path in [
            self.config.PRIMARY_BACKUP_DIR,
            self.config.SECONDARY_BACKUP_DIR,
            self.config.ARCHIVE_BACKUP_DIR,
            'backups'
        ]:
            Path(dir_path).mkdir(parents=True, exist_ok=True)
    
    def create_backup(self, backup_type: str = 'daily') -> Tuple[bool, str]:
        """
        Create a backup of the database
        
        Args:
            backup_type: Type of backup (hourly, daily, weekly, monthly, yearly)
        
        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            timestamp = datetime.now()
            
            # Check if database exists
            if not os.path.exists(self.config.DB_PATH):
                return False, f"Database file not found: {self.config.DB_PATH}"
            
            # Generate backup filename
            backup_filename = self._generate_backup_filename(timestamp, backup_type)
            primary_path = os.path.join(self.config.PRIMARY_BACKUP_DIR, backup_filename)
            secondary_path = os.path.join(self.config.SECONDARY_BACKUP_DIR, backup_filename)
            
            # Get database stats
            stats = self._get_database_stats()
            
            print("=" * 70)
            print(f"Database Backup - {timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Type: {backup_type.upper()}")
            print("=" * 70)
            print(f"Database size: {stats['size_kb']:.1f} KB")
            print(f"Tables: {len(stats['tables'])}")
            for table, count in stats['tables'].items():
                print(f"  - {table}: {count:,} records")
            
            # Create primary backup using SQLite backup API
            success, backup_path = self._create_sqlite_backup(primary_path)
            if not success:
                return False, f"Failed to create primary backup: {backup_path}"
            
            # Compress if enabled
            if self.config.COMPRESS_BACKUPS:
                backup_path = self._compress_backup(backup_path)
            
            # Create checksum if enabled
            checksum = None
            if self.config.CREATE_CHECKSUMS:
                checksum = self._create_checksum(backup_path)
            
            # Verify backup if enabled
            if self.config.VERIFY_BACKUPS:
                is_valid, verify_msg = self._verify_backup(backup_path, stats)
                if not is_valid:
                    return False, f"Backup verification failed: {verify_msg}"
            
            # Create secondary backup (redundancy)
            if self.config.COMPRESS_BACKUPS:
                secondary_path = secondary_path + '.gz'
            shutil.copy2(backup_path, secondary_path)
            
            # Save backup metadata
            metadata = {
                'timestamp': timestamp.isoformat(),
                'type': backup_type,
                'filename': os.path.basename(backup_path),
                'size_bytes': os.path.getsize(backup_path),
                'checksum': checksum,
                'database_stats': stats,
                'verified': self.config.VERIFY_BACKUPS
            }
            self._save_metadata(backup_path, metadata)
            
            # Log success
            backup_size = os.path.getsize(backup_path)
            print(f"\n✓ Primary backup created: {backup_filename}")
            print(f"  Size: {backup_size / 1024:.1f} KB")
            if checksum:
                print(f"  Checksum: {checksum[:16]}...")
            print(f"✓ Secondary backup created")
            
            # Update health check
            self._update_health_check(True, metadata)
            
            # Cleanup old backups
            self._cleanup_old_backups()
            
            print("=" * 70)
            
            return True, f"Backup created successfully: {backup_filename}"
            
        except Exception as e:
            error_msg = f"Backup failed: {str(e)}"
            print(f"\n✗ {error_msg}")
            traceback.print_exc()
            self._log_alert('BACKUP_FAILED', error_msg)
            self._update_health_check(False, {'error': str(e)})
            return False, error_msg
    
    def _generate_backup_filename(self, timestamp: datetime, backup_type: str) -> str:
        """Generate a backup filename with timestamp and type"""
        timestamp_str = timestamp.strftime('%Y%m%d_%H%M%S')
        return f'tablet_counter_{backup_type}_{timestamp_str}.db'
    
    def _get_database_stats(self) -> Dict:
        """Get database statistics"""
        try:
            conn = sqlite3.connect(self.config.DB_PATH)
            cursor = conn.cursor()
            
            # Get file size
            size_bytes = os.path.getsize(self.config.DB_PATH)
            
            # Get table counts
            tables = {}
            table_names = [
                'warehouse_submissions', 'purchase_orders', 'po_lines',
                'shipments', 'receiving', 'small_boxes', 'bags',
                'employees', 'tablet_types', 'product_details',
                'machine_counts', 'app_settings'
            ]
            
            for table in table_names:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cursor.fetchone()[0]
                    tables[table] = count
                except sqlite3.OperationalError:
                    # Table doesn't exist
                    pass
            
            conn.close()
            
            return {
                'size_bytes': size_bytes,
                'size_kb': size_bytes / 1024,
                'tables': tables
            }
        except Exception as e:
            return {
                'size_bytes': 0,
                'size_kb': 0,
                'tables': {},
                'error': str(e)
            }
    
    def _create_sqlite_backup(self, backup_path: str) -> Tuple[bool, str]:
        """Create backup using SQLite's backup API (safe for active databases)"""
        try:
            source_conn = sqlite3.connect(self.config.DB_PATH)
            backup_conn = sqlite3.connect(backup_path)
            
            with backup_conn:
                source_conn.backup(backup_conn)
            
            source_conn.close()
            backup_conn.close()
            
            return True, backup_path
        except Exception as e:
            return False, str(e)
    
    def _compress_backup(self, backup_path: str) -> str:
        """Compress backup file using gzip"""
        compressed_path = backup_path + '.gz'
        
        with open(backup_path, 'rb') as f_in:
            with gzip.open(compressed_path, 'wb', compresslevel=9) as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        # Remove uncompressed file
        os.remove(backup_path)
        
        return compressed_path
    
    def _create_checksum(self, backup_path: str) -> str:
        """Create SHA256 checksum of backup file"""
        sha256_hash = hashlib.sha256()
        
        with open(backup_path, 'rb') as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        
        checksum = sha256_hash.hexdigest()
        
        # Save checksum to file
        checksum_path = backup_path + '.sha256'
        with open(checksum_path, 'w') as f:
            f.write(f"{checksum}  {os.path.basename(backup_path)}\n")
        
        return checksum
    
    def _verify_backup(self, backup_path: str, original_stats: Dict) -> Tuple[bool, str]:
        """Verify backup integrity"""
        try:
            # Decompress if needed
            temp_db_path = None
            if backup_path.endswith('.gz'):
                temp_db_path = backup_path[:-3] + '.verify'
                with gzip.open(backup_path, 'rb') as f_in:
                    with open(temp_db_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                verify_path = temp_db_path
            else:
                verify_path = backup_path
            
            # Try to open and query the backup
            conn = sqlite3.connect(verify_path)
            cursor = conn.cursor()
            
            # Verify table counts match
            for table, expected_count in original_stats['tables'].items():
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                actual_count = cursor.fetchone()[0]
                if actual_count != expected_count:
                    conn.close()
                    if temp_db_path and os.path.exists(temp_db_path):
                        os.remove(temp_db_path)
                    return False, f"Table {table} count mismatch: expected {expected_count}, got {actual_count}"
            
            # Run integrity check
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()[0]
            conn.close()
            
            # Cleanup temp file
            if temp_db_path and os.path.exists(temp_db_path):
                os.remove(temp_db_path)
            
            if result != 'ok':
                return False, f"Integrity check failed: {result}"
            
            return True, "Backup verified successfully"
            
        except Exception as e:
            if temp_db_path and os.path.exists(temp_db_path):
                os.remove(temp_db_path)
            return False, f"Verification error: {str(e)}"
    
    def _save_metadata(self, backup_path: str, metadata: Dict):
        """Save backup metadata to JSON file"""
        metadata_path = backup_path + '.meta.json'
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
    
    def _cleanup_old_backups(self):
        """Remove old backups based on retention policy"""
        try:
            print("\nCleaning up old backups...")
            
            for backup_dir in [self.config.PRIMARY_BACKUP_DIR, self.config.SECONDARY_BACKUP_DIR]:
                if not os.path.exists(backup_dir):
                    continue
                
                # Categorize backups by type
                backups_by_type = {
                    'hourly': [],
                    'daily': [],
                    'weekly': [],
                    'monthly': [],
                    'yearly': []
                }
                
                # Collect all backup files
                for filename in os.listdir(backup_dir):
                    if not filename.startswith('tablet_counter_'):
                        continue
                    
                    # Extract backup type
                    for backup_type in backups_by_type.keys():
                        if f'_{backup_type}_' in filename:
                            filepath = os.path.join(backup_dir, filename)
                            mtime = os.path.getmtime(filepath)
                            backups_by_type[backup_type].append((filepath, mtime))
                            break
                
                # Apply retention policy for each type
                retention_limits = {
                    'hourly': self.config.KEEP_HOURLY,
                    'daily': self.config.KEEP_DAILY,
                    'weekly': self.config.KEEP_WEEKLY,
                    'monthly': self.config.KEEP_MONTHLY,
                    'yearly': self.config.KEEP_YEARLY
                }
                
                total_deleted = 0
                for backup_type, backups in backups_by_type.items():
                    # Sort by modification time (newest first)
                    backups.sort(key=lambda x: x[1], reverse=True)
                    
                    # Keep only the specified number of backups
                    limit = retention_limits[backup_type]
                    to_delete = backups[limit:]
                    
                    for filepath, _ in to_delete:
                        try:
                            # Delete backup file and associated files
                            os.remove(filepath)
                            total_deleted += 1
                            
                            # Delete associated files (checksum, metadata)
                            for ext in ['.sha256', '.meta.json']:
                                assoc_file = filepath + ext
                                if os.path.exists(assoc_file):
                                    os.remove(assoc_file)
                        except Exception as e:
                            print(f"  ⚠ Could not delete {os.path.basename(filepath)}: {e}")
                
                if total_deleted > 0:
                    print(f"  ✓ Deleted {total_deleted} old backup(s) from {os.path.basename(backup_dir)}")
            
        except Exception as e:
            print(f"  ⚠ Cleanup warning: {e}")
    
    def _log_alert(self, alert_type: str, message: str):
        """Log an alert to the alert log file"""
        try:
            Path(self.config.ALERT_LOG).parent.mkdir(parents=True, exist_ok=True)
            with open(self.config.ALERT_LOG, 'a') as f:
                timestamp = datetime.now().isoformat()
                f.write(f"[{timestamp}] {alert_type}: {message}\n")
        except Exception as e:
            print(f"Failed to log alert: {e}")
    
    def _update_health_check(self, success: bool, metadata: Dict):
        """Update backup health check status"""
        try:
            Path(self.config.HEALTH_CHECK_LOG).parent.mkdir(parents=True, exist_ok=True)
            
            health_data = {
                'last_backup_time': datetime.now().isoformat(),
                'last_backup_success': success,
                'last_backup_metadata': metadata,
                'consecutive_failures': 0
            }
            
            # Load existing health data
            if os.path.exists(self.config.HEALTH_CHECK_LOG):
                with open(self.config.HEALTH_CHECK_LOG, 'r') as f:
                    try:
                        existing_data = json.load(f)
                        if not success:
                            health_data['consecutive_failures'] = existing_data.get('consecutive_failures', 0) + 1
                    except json.JSONDecodeError:
                        pass
            
            # Save health data
            with open(self.config.HEALTH_CHECK_LOG, 'w') as f:
                json.dump(health_data, f, indent=2)
            
            # Alert on consecutive failures
            if health_data['consecutive_failures'] >= 3:
                self._log_alert('CRITICAL', f"3 consecutive backup failures!")
                
        except Exception as e:
            print(f"Failed to update health check: {e}")
    
    def list_backups(self, backup_type: Optional[str] = None) -> List[Dict]:
        """List all available backups"""
        backups = []
        
        for backup_dir in [self.config.PRIMARY_BACKUP_DIR, self.config.SECONDARY_BACKUP_DIR]:
            if not os.path.exists(backup_dir):
                continue
            
            for filename in os.listdir(backup_dir):
                if not filename.startswith('tablet_counter_'):
                    continue
                
                # Filter by type if specified
                if backup_type and f'_{backup_type}_' not in filename:
                    continue
                
                filepath = os.path.join(backup_dir, filename)
                
                # Load metadata if available
                metadata_path = filepath + '.meta.json'
                metadata = {}
                if os.path.exists(metadata_path):
                    with open(metadata_path, 'r') as f:
                        try:
                            metadata = json.load(f)
                        except json.JSONDecodeError:
                            pass
                
                backups.append({
                    'filename': filename,
                    'path': filepath,
                    'directory': os.path.basename(backup_dir),
                    'size_bytes': os.path.getsize(filepath),
                    'modified_time': os.path.getmtime(filepath),
                    'metadata': metadata
                })
        
        # Sort by modification time (newest first)
        backups.sort(key=lambda x: x['modified_time'], reverse=True)
        
        return backups
    
    def print_backup_status(self):
        """Print backup system status"""
        print("\n" + "=" * 70)
        print("BACKUP SYSTEM STATUS")
        print("=" * 70)
        
        # Count backups by type
        all_backups = self.list_backups()
        backup_counts = {
            'hourly': 0,
            'daily': 0,
            'weekly': 0,
            'monthly': 0,
            'yearly': 0
        }
        
        for backup in all_backups:
            for backup_type in backup_counts.keys():
                if f'_{backup_type}_' in backup['filename']:
                    backup_counts[backup_type] += 1
                    break
        
        print("\nBackup Inventory:")
        for backup_type, count in backup_counts.items():
            limit = getattr(self.config, f'KEEP_{backup_type.upper()}')
            print(f"  {backup_type.capitalize()}: {count} / {limit} backups")
        
        # Show recent backups
        print("\nRecent Backups (last 5):")
        for backup in all_backups[:5]:
            timestamp = datetime.fromtimestamp(backup['modified_time'])
            size_kb = backup['size_bytes'] / 1024
            print(f"  {timestamp.strftime('%Y-%m-%d %H:%M:%S')} | {size_kb:7.1f} KB | {backup['filename']}")
        
        # Health check
        if os.path.exists(self.config.HEALTH_CHECK_LOG):
            with open(self.config.HEALTH_CHECK_LOG, 'r') as f:
                health = json.load(f)
                print("\nHealth Status:")
                print(f"  Last backup: {health.get('last_backup_time', 'Never')}")
                print(f"  Last status: {'✓ Success' if health.get('last_backup_success') else '✗ Failed'}")
                failures = health.get('consecutive_failures', 0)
                if failures > 0:
                    print(f"  ⚠ Consecutive failures: {failures}")
        
        print("=" * 70)


def main():
    """Main entry point for backup manager"""
    import sys
    
    manager = BackupManager()
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == '--status':
            manager.print_backup_status()
        elif command == '--list':
            backups = manager.list_backups()
            print(f"\nFound {len(backups)} backups:")
            for backup in backups[:20]:
                timestamp = datetime.fromtimestamp(backup['modified_time'])
                size_kb = backup['size_bytes'] / 1024
                print(f"  {timestamp.strftime('%Y-%m-%d %H:%M')} | {size_kb:6.1f} KB | {backup['filename']}")
        elif command in ['--hourly', '--daily', '--weekly', '--monthly', '--yearly']:
            backup_type = command[2:]  # Remove '--'
            success, message = manager.create_backup(backup_type)
            sys.exit(0 if success else 1)
        else:
            print(f"Unknown command: {command}")
            print("Usage: backup_manager.py [--hourly|--daily|--weekly|--monthly|--yearly|--status|--list]")
            sys.exit(1)
    else:
        # Default: create daily backup
        success, message = manager.create_backup('daily')
        sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()

