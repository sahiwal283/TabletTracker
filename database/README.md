# Database Backup & Restore System

## Overview

This comprehensive backup system ensures your TabletTracker data is protected with automated, verified backups and easy restoration.

## Features

- ✅ **Automated Scheduled Backups** - Hourly, daily, weekly, monthly, and yearly backups
- ✅ **Multiple Backup Locations** - Primary and secondary backup directories for redundancy
- ✅ **Backup Verification** - Automatic integrity checks and checksums
- ✅ **Compression** - Backups are compressed to save disk space
- ✅ **Smart Retention** - Configurable retention policies (24 hourly, 30 daily, 12 weekly, 24 monthly, 10 yearly)
- ✅ **Health Monitoring** - Regular health checks with alerts
- ✅ **Safe Restoration** - Automatic backup before restore
- ✅ **Interactive Tools** - Easy-to-use CLI tools

## Quick Start

### 1. Set Up Automated Backups

```bash
cd database
./schedule_backups.sh
```

This will configure automated backups to run:
- **Hourly**: Every hour on the hour
- **Daily**: Every day at 2:00 AM
- **Weekly**: Every Sunday at 3:00 AM
- **Monthly**: 1st of every month at 4:00 AM
- **Yearly**: January 1st at 5:00 AM

### 2. Check Backup Status

```bash
python3 database/backup_manager.py --status
```

### 3. Restore from Backup (if needed)

```bash
cd database
./quick_restore.sh
```

Or directly:

```bash
python3 database/restore_manager.py --interactive
```

## Manual Backup Commands

### Create a Backup

```bash
# Daily backup (recommended)
python3 database/backup_manager.py --daily

# Or specify type
python3 database/backup_manager.py --hourly
python3 database/backup_manager.py --weekly
python3 database/backup_manager.py --monthly
python3 database/backup_manager.py --yearly
```

### List Backups

```bash
python3 database/backup_manager.py --list
```

### Check System Health

```bash
python3 database/health_check.py
```

## Restoration

### Interactive Restoration

The easiest way to restore:

```bash
python3 database/restore_manager.py --interactive
```

This will:
1. Show all available backups
2. Let you select which backup to restore
3. Verify the backup
4. Backup your current database (just in case)
5. Restore the selected backup
6. Verify the restoration

### Direct Restoration

If you know which backup to restore:

```bash
python3 database/restore_manager.py backups/primary/tablet_counter_daily_20241206_020000.db.gz
```

### Force Restoration

To skip verification prompts:

```bash
python3 database/restore_manager.py <backup_file> --force
```

## Directory Structure

```
backups/
├── primary/           # Primary backup location
├── secondary/         # Secondary backup location (redundancy)
├── archive/           # Long-term archive backups
├── before_restore/    # Backups created before restoration
├── backup_health.json # Health check status
├── backup_alerts.log  # Alert log
└── backup.log         # Backup operation log
```

## Backup File Naming

```
tablet_counter_{type}_{timestamp}.db.gz
```

Example: `tablet_counter_daily_20241206_020000.db.gz`

Each backup includes:
- `.gz` - Compressed database file
- `.sha256` - Checksum for verification
- `.meta.json` - Metadata (timestamp, stats, verification status)

## Retention Policy

| Type    | Kept | Purpose              |
|---------|------|----------------------|
| Hourly  | 24   | Recent changes (1d)  |
| Daily   | 30   | Short-term (1m)      |
| Weekly  | 12   | Medium-term (3m)     |
| Monthly | 24   | Long-term (2y)       |
| Yearly  | 10   | Archive (10y)        |

Old backups are automatically cleaned up based on this policy.

## Health Checks

The health check system monitors:

1. **Database Health** - Integrity checks on main database
2. **Backup Freshness** - Ensures recent backups exist
3. **Backup Integrity** - Verifies backup checksums
4. **Disk Space** - Alerts if running low on space
5. **Backup Counts** - Ensures minimum backup counts

Health checks run every 6 hours (configurable in cron).

### Manual Health Check

```bash
python3 database/health_check.py
```

## Monitoring and Alerts

### Check Alert Log

```bash
cat backups/backup_alerts.log
```

### Check Health Status

```bash
cat backups/backup_health.json
```

### Check Backup Log

```bash
tail -f backups/backup.log
```

## Troubleshooting

### No Backups Found

```bash
# Manually create a backup
python3 database/backup_manager.py --daily

# Check if backup directories exist
ls -la backups/
```

### Backup Failed

```bash
# Check the error log
tail backups/backup.log

# Check database health
python3 database/health_check.py

# Try manual backup with verbose output
python3 database/backup_manager.py --daily
```

### Restore Failed

```bash
# List available backups
python3 database/restore_manager.py --list

# Verify a specific backup
python3 database/restore_manager.py <backup_file> --force
```

### Disk Space Issues

```bash
# Check disk space
df -h

# Clean up old backups manually
ls -lht backups/primary/ | tail -n 20
# Delete oldest backups if needed
```

## Advanced Configuration

Edit `database/backup_manager.py` to customize:

```python
class BackupConfig:
    # Retention policies
    KEEP_HOURLY = 24        # Number of hourly backups to keep
    KEEP_DAILY = 30         # Number of daily backups to keep
    KEEP_WEEKLY = 12        # Number of weekly backups to keep
    KEEP_MONTHLY = 24       # Number of monthly backups to keep
    KEEP_YEARLY = 10        # Number of yearly backups to keep
    
    # Features
    COMPRESS_BACKUPS = True      # Compress backups with gzip
    VERIFY_BACKUPS = True        # Verify backups after creation
    CREATE_CHECKSUMS = True      # Create SHA256 checksums
```

## Production Deployment (PythonAnywhere)

For PythonAnywhere, use the Task scheduler:

1. Go to **Tasks** tab
2. Add scheduled tasks:
   ```
   # Hourly backup (every hour at :00)
   /home/yourusername/TabletTracker/venv/bin/python /home/yourusername/TabletTracker/database/backup_manager.py --hourly
   
   # Daily backup (2:00 AM UTC)
   /home/yourusername/TabletTracker/venv/bin/python /home/yourusername/TabletTracker/database/backup_manager.py --daily
   
   # Health check (every 6 hours)
   /home/yourusername/TabletTracker/venv/bin/python /home/yourusername/TabletTracker/database/health_check.py
   ```

## Security Best Practices

1. **Regular Offsite Backups** - Copy backups to external storage periodically
2. **Test Restorations** - Regularly test restoration process
3. **Monitor Alerts** - Check alert logs regularly
4. **Verify Checksums** - Backups are automatically verified with SHA256
5. **Multiple Locations** - Backups are stored in primary and secondary locations

## Disaster Recovery Plan

### Complete Data Loss

1. Find most recent backup:
   ```bash
   python3 database/restore_manager.py --list
   ```

2. Restore from backup:
   ```bash
   python3 database/restore_manager.py --interactive
   ```

3. Verify restoration:
   ```bash
   python3 database/health_check.py
   ```

4. Restart application:
   ```bash
   # For PythonAnywhere: Reload web app
   # For local: Restart Flask app
   ```

### Corrupted Database

1. Check database integrity:
   ```bash
   sqlite3 tablet_counter.db "PRAGMA integrity_check"
   ```

2. If corrupted, restore from most recent backup:
   ```bash
   python3 database/restore_manager.py --interactive
   ```

### Accidental Data Deletion

1. Restore from backup before deletion occurred
2. Export specific data if needed
3. Merge with current database if necessary

## Support

For issues or questions:

1. Check health status: `python3 database/health_check.py`
2. Review alert log: `cat backups/backup_alerts.log`
3. Review backup log: `cat backups/backup.log`
4. Check disk space: `df -h`

## File Permissions

Make scripts executable:

```bash
chmod +x database/schedule_backups.sh
chmod +x database/quick_restore.sh
chmod +x database/backup_manager.py
chmod +x database/restore_manager.py
chmod +x database/health_check.py
```

## Conclusion

Your database is now protected with:
- ✅ Automated hourly, daily, weekly, monthly, and yearly backups
- ✅ Verification and integrity checks
- ✅ Health monitoring and alerts
- ✅ Easy restoration process
- ✅ Multiple backup locations for redundancy

**Your data will never be lost again!**

