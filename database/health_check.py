#!/usr/bin/env python3
"""
Backup Health Check
Monitors backup system health and alerts on issues
"""
import os
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple


class BackupHealthChecker:
    """Monitors backup system health"""
    
    def __init__(self):
        self.db_path = 'tablet_counter.db'
        self.backup_dirs = ['backups/primary', 'backups/secondary']
        self.health_log = 'backups/backup_health.json'
        self.alert_log = 'backups/backup_alerts.log'
    
    def check_database_health(self) -> Tuple[bool, List[str]]:
        """Check if main database is healthy"""
        issues = []
        
        if not os.path.exists(self.db_path):
            issues.append("❌ Main database file missing!")
            return False, issues
        
        try:
            # Check database integrity
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()[0]
            
            if result != 'ok':
                issues.append(f"❌ Database integrity check failed: {result}")
            
            # Check critical tables exist
            critical_tables = [
                'warehouse_submissions', 'purchase_orders', 'employees',
                'shipments', 'receiving', 'tablet_types'
            ]
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            existing_tables = {row[0] for row in cursor.fetchall()}
            
            for table in critical_tables:
                if table not in existing_tables:
                    issues.append(f"⚠️  Critical table missing: {table}")
            
            conn.close()
            
            if not issues:
                return True, ["✓ Database is healthy"]
            else:
                return False, issues
                
        except Exception as e:
            issues.append(f"❌ Database error: {str(e)}")
            return False, issues
    
    def check_backup_freshness(self) -> Tuple[bool, List[str]]:
        """Check if backups are recent"""
        issues = []
        
        # Expected backup frequencies (in hours)
        expected_frequencies = {
            'hourly': 2,    # Should have backup within 2 hours
            'daily': 26,    # Should have backup within 26 hours
            'weekly': 8*24, # Should have backup within 8 days
        }
        
        now = datetime.now()
        
        for backup_dir in self.backup_dirs:
            if not os.path.exists(backup_dir):
                issues.append(f"⚠️  Backup directory missing: {backup_dir}")
                continue
            
            # Check each backup type
            for backup_type, max_age_hours in expected_frequencies.items():
                most_recent = None
                
                for filename in os.listdir(backup_dir):
                    if f'_{backup_type}_' in filename and filename.startswith('tablet_counter_'):
                        filepath = os.path.join(backup_dir, filename)
                        mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                        
                        if most_recent is None or mtime > most_recent:
                            most_recent = mtime
                
                if most_recent is None:
                    issues.append(f"⚠️  No {backup_type} backups found in {os.path.basename(backup_dir)}")
                else:
                    age_hours = (now - most_recent).total_seconds() / 3600
                    if age_hours > max_age_hours:
                        issues.append(f"⚠️  Last {backup_type} backup is {age_hours:.1f}h old (expected < {max_age_hours}h)")
        
        if not issues:
            return True, ["✓ Backups are fresh"]
        else:
            return False, issues
    
    def check_backup_integrity(self) -> Tuple[bool, List[str]]:
        """Verify integrity of recent backups"""
        issues = []
        checked = 0
        
        for backup_dir in self.backup_dirs:
            if not os.path.exists(backup_dir):
                continue
            
            # Get recent backups (last 3 of each type)
            recent_backups = []
            for filename in os.listdir(backup_dir):
                if filename.startswith('tablet_counter_') and not filename.endswith(('.sha256', '.meta.json')):
                    filepath = os.path.join(backup_dir, filename)
                    mtime = os.path.getmtime(filepath)
                    recent_backups.append((filepath, mtime))
            
            # Sort by modification time (newest first) and take last 3
            recent_backups.sort(key=lambda x: x[1], reverse=True)
            recent_backups = recent_backups[:3]
            
            for backup_path, _ in recent_backups:
                checked += 1
                
                # Check if checksum file exists
                checksum_path = backup_path + '.sha256'
                if not os.path.exists(checksum_path):
                    issues.append(f"⚠️  Missing checksum: {os.path.basename(backup_path)}")
                    continue
                
                # Verify metadata exists
                metadata_path = backup_path + '.meta.json'
                if not os.path.exists(metadata_path):
                    issues.append(f"⚠️  Missing metadata: {os.path.basename(backup_path)}")
        
        if checked == 0:
            issues.append("❌ No backups found to verify!")
            return False, issues
        
        if not issues:
            return True, [f"✓ Verified {checked} recent backups"]
        else:
            return False, issues
    
    def check_disk_space(self) -> Tuple[bool, List[str]]:
        """Check available disk space"""
        issues = []
        
        try:
            import shutil
            total, used, free = shutil.disk_usage('.')
            
            free_gb = free / (1024**3)
            free_percent = (free / total) * 100
            
            # Alert if less than 1GB or 10% free
            if free_gb < 1:
                issues.append(f"❌ Low disk space: {free_gb:.2f} GB free")
            elif free_percent < 10:
                issues.append(f"⚠️  Low disk space: {free_percent:.1f}% free ({free_gb:.2f} GB)")
            else:
                return True, [f"✓ Disk space: {free_gb:.2f} GB free ({free_percent:.1f}%)"]
                
        except Exception as e:
            issues.append(f"⚠️  Could not check disk space: {str(e)}")
        
        return len(issues) == 0, issues if issues else ["✓ Disk space OK"]
    
    def check_backup_counts(self) -> Tuple[bool, List[str]]:
        """Check if we have expected number of backups"""
        issues = []
        
        # Expected minimum counts
        expected_counts = {
            'hourly': 6,    # At least 6 hourly backups
            'daily': 7,     # At least 7 daily backups
            'weekly': 4,    # At least 4 weekly backups
            'monthly': 3,   # At least 3 monthly backups
        }
        
        for backup_dir in self.backup_dirs:
            if not os.path.exists(backup_dir):
                continue
            
            backup_counts = {
                'hourly': 0,
                'daily': 0,
                'weekly': 0,
                'monthly': 0,
                'yearly': 0
            }
            
            for filename in os.listdir(backup_dir):
                for backup_type in backup_counts.keys():
                    if f'_{backup_type}_' in filename:
                        backup_counts[backup_type] += 1
                        break
            
            # Check counts
            for backup_type, expected_min in expected_counts.items():
                actual = backup_counts[backup_type]
                if actual < expected_min:
                    issues.append(f"⚠️  Only {actual} {backup_type} backups (expected ≥ {expected_min}) in {os.path.basename(backup_dir)}")
        
        if not issues:
            return True, ["✓ Backup counts are healthy"]
        else:
            return False, issues
    
    def run_health_check(self) -> Dict:
        """Run comprehensive health check"""
        print("\n" + "=" * 70)
        print("BACKUP SYSTEM HEALTH CHECK")
        print("=" * 70)
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        all_checks = {
            'Database Health': self.check_database_health(),
            'Backup Freshness': self.check_backup_freshness(),
            'Backup Integrity': self.check_backup_integrity(),
            'Disk Space': self.check_disk_space(),
            'Backup Counts': self.check_backup_counts(),
        }
        
        critical_failures = []
        warnings = []
        
        for check_name, (passed, messages) in all_checks.items():
            print(f"{check_name}:")
            for message in messages:
                print(f"  {message}")
                if '❌' in message:
                    critical_failures.append(f"{check_name}: {message}")
                elif '⚠️' in message:
                    warnings.append(f"{check_name}: {message}")
            print()
        
        # Overall status
        print("=" * 70)
        if not critical_failures and not warnings:
            status = 'HEALTHY'
            print("✅ OVERALL STATUS: HEALTHY")
        elif critical_failures:
            status = 'CRITICAL'
            print("❌ OVERALL STATUS: CRITICAL")
            print(f"\nCritical Issues ({len(critical_failures)}):")
            for issue in critical_failures:
                print(f"  • {issue}")
        else:
            status = 'WARNING'
            print("⚠️  OVERALL STATUS: WARNING")
            print(f"\nWarnings ({len(warnings)}):")
            for warning in warnings:
                print(f"  • {warning}")
        
        print("=" * 70)
        print()
        
        # Save health check results
        health_data = {
            'timestamp': datetime.now().isoformat(),
            'status': status,
            'checks': {name: {'passed': passed, 'messages': messages} 
                      for name, (passed, messages) in all_checks.items()},
            'critical_failures': critical_failures,
            'warnings': warnings
        }
        
        try:
            Path(self.health_log).parent.mkdir(parents=True, exist_ok=True)
            with open(self.health_log, 'w') as f:
                json.dump(health_data, f, indent=2)
        except Exception as e:
            print(f"⚠️  Could not save health check: {e}")
        
        # Log alerts
        if critical_failures:
            self._log_alert('CRITICAL', f"{len(critical_failures)} critical issues detected")
            # Return non-zero exit code for monitoring systems
            return health_data
        elif warnings:
            self._log_alert('WARNING', f"{len(warnings)} warnings detected")
        
        return health_data
    
    def _log_alert(self, level: str, message: str):
        """Log an alert"""
        try:
            Path(self.alert_log).parent.mkdir(parents=True, exist_ok=True)
            with open(self.alert_log, 'a') as f:
                timestamp = datetime.now().isoformat()
                f.write(f"[{timestamp}] {level}: {message}\n")
        except Exception as e:
            print(f"Could not log alert: {e}")


def main():
    """Main entry point"""
    import sys
    
    checker = BackupHealthChecker()
    health_data = checker.run_health_check()
    
    # Exit with non-zero code if critical issues
    if health_data['status'] == 'CRITICAL':
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()

