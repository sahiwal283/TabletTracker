# PythonAnywhere Backup Setup Guide

## Overview

This guide explains how to set up automated backups on PythonAnywhere for your TabletTracker application.

## Initial Setup

### 1. Upload Backup Scripts

Make sure all files in the `database/` directory are uploaded to PythonAnywhere:

```
database/
├── backup_manager.py
├── restore_manager.py
├── health_check.py
├── setup_backups.py
├── README.md
└── pythonanywhere_setup.md (this file)
```

### 2. Initialize Backup System

Open a **Bash console** on PythonAnywhere and run:

```bash
cd ~/TabletTracker  # or your project directory
python3 database/setup_backups.py
```

This will:
- Create backup directories
- Create an initial backup
- Set up .gitignore for backup files

### 3. Test Manual Backup

Test that backups work:

```bash
python3 database/backup_manager.py --daily
```

You should see output confirming the backup was created.

## Automated Backup Schedule

### Setting Up Scheduled Tasks

PythonAnywhere uses a task scheduler instead of cron. Here's how to set it up:

1. Go to your **PythonAnywhere Dashboard**
2. Click on the **Tasks** tab
3. Add the following scheduled tasks:

#### Daily Backup (Required)

**Description:** Daily database backup  
**Command:**
```
/home/YOUR_USERNAME/TabletTracker/venv/bin/python3 /home/YOUR_USERNAME/TabletTracker/database/backup_manager.py --daily
```
**Schedule:** Every day at **02:00 UTC**

> Replace `YOUR_USERNAME` with your actual PythonAnywhere username

#### Weekly Backup (Recommended)

**Description:** Weekly database backup  
**Command:**
```
/home/YOUR_USERNAME/TabletTracker/venv/bin/python3 /home/YOUR_USERNAME/TabletTracker/database/backup_manager.py --weekly
```
**Schedule:** Create a daily task for Sunday at **03:00 UTC**

#### Monthly Backup (Recommended)

**Description:** Monthly database backup  
**Command:**
```
/home/YOUR_USERNAME/TabletTracker/venv/bin/python3 /home/YOUR_USERNAME/TabletTracker/database/backup_manager.py --monthly
```
**Schedule:** First day of month at **04:00 UTC**

#### Health Check (Recommended)

**Description:** Backup system health check  
**Command:**
```
/home/YOUR_USERNAME/TabletTracker/venv/bin/python3 /home/YOUR_USERNAME/TabletTracker/database/health_check.py
```
**Schedule:** Every day at **12:00 UTC**

### PythonAnywhere Task Limitations

**Free Accounts:**
- Only 1 scheduled task allowed
- Choose the **daily backup** task

**Paid Accounts:**
- Multiple scheduled tasks allowed
- Set up all recommended tasks above

## Manual Commands

### Create a Backup

```bash
cd ~/TabletTracker
python3 database/backup_manager.py --daily
```

### List Backups

```bash
python3 database/backup_manager.py --list
```

### Check System Status

```bash
python3 database/backup_manager.py --status
```

### Run Health Check

```bash
python3 database/health_check.py
```

### Restore from Backup

```bash
python3 database/restore_manager.py --interactive
```

## Monitoring

### Check Backup Logs

```bash
cat ~/TabletTracker/backups/backup.log
```

### Check Alert Log

```bash
cat ~/TabletTracker/backups/backup_alerts.log
```

### Check Health Status

```bash
cat ~/TabletTracker/backups/backup_health.json
```

## Disk Space Management

PythonAnywhere has disk quotas. Monitor your usage:

### Check Disk Usage

```bash
du -sh ~/TabletTracker/backups/
```

### View Backup Sizes

```bash
du -h ~/TabletTracker/backups/primary/ | sort -h
```

### Adjust Retention Policy

If you're running low on space, edit `database/backup_manager.py`:

```python
class BackupConfig:
    # Reduce these numbers if needed
    KEEP_DAILY = 14      # Instead of 30
    KEEP_WEEKLY = 8      # Instead of 12
    KEEP_MONTHLY = 12    # Instead of 24
```

## Disaster Recovery

### Complete Database Loss

1. Open a Bash console
2. List available backups:
   ```bash
   cd ~/TabletTracker
   python3 database/restore_manager.py --list
   ```

3. Restore interactively:
   ```bash
   python3 database/restore_manager.py --interactive
   ```

4. Reload your web app:
   - Go to **Web** tab
   - Click **Reload yourusername.pythonanywhere.com**

### Database Corruption

1. Check integrity:
   ```bash
   cd ~/TabletTracker
   python3 database/health_check.py
   ```

2. If corrupted, restore from most recent backup:
   ```bash
   python3 database/restore_manager.py --interactive
   ```

3. Reload web app

## Offsite Backups (Recommended)

PythonAnywhere backups are stored on PythonAnywhere's servers. For maximum safety, periodically download backups to your local machine or cloud storage.

### Download Backups via Web Interface

1. Go to **Files** tab
2. Navigate to `TabletTracker/backups/primary/`
3. Download recent backups to your local machine
4. Store in a safe location (Dropbox, Google Drive, etc.)

### Download Backups via SFTP

Use an SFTP client (FileZilla, Cyberduck, etc.):

```
Host: yourusername.pythonanywhere.com
Username: yourusername
Password: your_password
```

Navigate to `TabletTracker/backups/` and download files.

### Automated Offsite Backups (Paid Accounts)

If you have a paid PythonAnywhere account, you can set up a task to sync backups to cloud storage using tools like `rclone`.

## Troubleshooting

### Task Not Running

**Check task logs:**
1. Go to **Tasks** tab
2. Check the task history/logs
3. Look for error messages

**Common issues:**
- Wrong path to Python or script
- Permission issues (run `chmod +x database/*.py`)
- Missing dependencies

### Backup Failed

**Check the backup log:**
```bash
tail -n 50 ~/TabletTracker/backups/backup.log
```

**Common causes:**
- Disk space full (check quota)
- Database locked (web app using it)
- Permissions issues

### Out of Disk Space

**Check quota:**
```bash
du -sh ~
```

**Free up space:**
```bash
# Remove old backups manually
cd ~/TabletTracker/backups/primary
ls -lt | tail -n 10  # List oldest backups
# Delete oldest ones if needed
```

**Or reduce retention policy** (see Disk Space Management above)

## Best Practices

1. **Test Restoration Monthly** - Verify backups are working
2. **Monitor Disk Space** - Check quota regularly
3. **Download Important Backups** - Keep offsite copies
4. **Check Health Status** - Review health checks weekly
5. **Update Retention Policy** - Adjust based on disk space
6. **Document Restoration** - Keep this guide handy

## Support

If you encounter issues:

1. Check the logs (see Monitoring section)
2. Run health check: `python3 database/health_check.py`
3. Review this guide
4. Check PythonAnywhere help forum
5. Contact PythonAnywhere support for platform issues

## Summary

Your PythonAnywhere backup system includes:

✅ Automated scheduled backups  
✅ Multiple backup types (daily, weekly, monthly)  
✅ Backup verification and checksums  
✅ Health monitoring  
✅ Easy restoration process  
✅ Compressed backups to save space  

**Your data is protected!**

