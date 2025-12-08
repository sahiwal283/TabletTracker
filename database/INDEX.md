# Database Management - Complete Index

## 📁 File Structure

```
database/
├── INDEX.md                          # This file - navigation hub
├── README.md                         # Backup system complete guide
├── DATABASE_MANAGEMENT.md            # Full database management guide
├── pythonanywhere_setup.md           # Production deployment guide
│
├── backup_manager.py                 # Core backup system (21 KB)
├── restore_manager.py                # Restoration system (14 KB)
├── health_check.py                   # Health monitoring (12 KB)
├── setup_backups.py                  # Initial setup script
├── schedule_backups.sh               # Automation scheduler
└── quick_restore.sh                  # Quick restore access
```

---

## 🗺️ Navigation Guide

### I Want To...

**Set Up Backups for the First Time**
→ Read: [QUICK_START_BACKUPS.md](../QUICK_START_BACKUPS.md)
→ Run: `./database/schedule_backups.sh`

**Learn About the Backup System**
→ Read: [README.md](README.md)

**Understand Database Management**
→ Read: [DATABASE_MANAGEMENT.md](DATABASE_MANAGEMENT.md)

**Deploy to PythonAnywhere**
→ Read: [pythonanywhere_setup.md](pythonanywhere_setup.md)

**Get a Complete Overview**
→ Read: [DATABASE_BACKUP_SUMMARY.md](../DATABASE_BACKUP_SUMMARY.md)

**Restore My Database**
→ Run: `./database/quick_restore.sh`
→ Or: `python3 database/restore_manager.py --interactive`

**Check Backup Health**
→ Run: `python3 database/health_check.py`

**Create a Manual Backup**
→ Run: `python3 database/backup_manager.py --daily`

---

## 📚 Documentation by Purpose

### Quick References
| File | Use When | Time |
|------|----------|------|
| [QUICK_START_BACKUPS.md](../QUICK_START_BACKUPS.md) | First time setup | 2 min |
| [DATABASE_BACKUP_SUMMARY.md](../DATABASE_BACKUP_SUMMARY.md) | Need overview | 5 min |

### Detailed Guides
| File | Use When | Time |
|------|----------|------|
| [README.md](README.md) | Using backup system | 15 min |
| [DATABASE_MANAGEMENT.md](DATABASE_MANAGEMENT.md) | Managing database | 30 min |
| [pythonanywhere_setup.md](pythonanywhere_setup.md) | Production deploy | 10 min |

---

## 🔧 Tools by Function

### Backup Operations
| Tool | Command | Purpose |
|------|---------|---------|
| `backup_manager.py` | `--daily` | Create daily backup |
| `backup_manager.py` | `--hourly` | Create hourly backup |
| `backup_manager.py` | `--weekly` | Create weekly backup |
| `backup_manager.py` | `--monthly` | Create monthly backup |
| `backup_manager.py` | `--yearly` | Create yearly backup |
| `backup_manager.py` | `--status` | Show backup status |
| `backup_manager.py` | `--list` | List all backups |

### Restoration Operations
| Tool | Command | Purpose |
|------|---------|---------|
| `restore_manager.py` | `--interactive` | Interactive restore |
| `restore_manager.py` | `--list` | List available backups |
| `restore_manager.py` | `<file>` | Restore specific backup |
| `restore_manager.py` | `<file> --force` | Force restore (skip verification) |
| `quick_restore.sh` | (no args) | Quick restore shortcut |

### Monitoring Operations
| Tool | Command | Purpose |
|------|---------|---------|
| `health_check.py` | (no args) | Run health check |

### Setup Operations
| Tool | Command | Purpose |
|------|---------|---------|
| `setup_backups.py` | (no args) | Initialize backup system |
| `schedule_backups.sh` | (no args) | Set up automation |

---

## 🎯 Common Workflows

### Initial Setup
```bash
# 1. Initialize
python3 database/setup_backups.py

# 2. Schedule automation
./database/schedule_backups.sh

# 3. Verify
python3 database/backup_manager.py --status
```

### Daily Monitoring
```bash
# Check status
python3 database/backup_manager.py --status

# Run health check (if needed)
python3 database/health_check.py
```

### Emergency Recovery
```bash
# 1. List available backups
python3 database/restore_manager.py --list

# 2. Restore interactively
python3 database/restore_manager.py --interactive

# 3. Verify restoration
python3 database/health_check.py
```

### Manual Backup
```bash
# Create immediate backup
python3 database/backup_manager.py --daily

# Verify it was created
python3 database/backup_manager.py --list
```

---

## 📊 System Architecture

### Backup Flow
```
Database (tablet_counter.db)
    ↓
backup_manager.py
    ↓
├─→ Create SQLite backup (safe API)
├─→ Compress with gzip
├─→ Generate SHA256 checksum
├─→ Verify integrity
├─→ Save metadata
├─→ Copy to secondary location
└─→ Cleanup old backups
    ↓
backups/primary/  (Main storage)
backups/secondary/ (Redundancy)
```

### Restore Flow
```
User Request
    ↓
restore_manager.py
    ↓
├─→ List available backups
├─→ User selects backup
├─→ Verify backup integrity
├─→ Backup current database
├─→ Decompress (if needed)
├─→ Restore database file
└─→ Verify restoration
    ↓
Restored Database
```

### Health Check Flow
```
Scheduled Trigger (every 6h)
    ↓
health_check.py
    ↓
├─→ Check database integrity
├─→ Check backup freshness
├─→ Verify backup checksums
├─→ Monitor disk space
└─→ Count backups
    ↓
├─→ Save health status (JSON)
├─→ Log alerts (if needed)
└─→ Exit code (0=OK, 1=Critical)
```

---

## 🔐 Security & Safety

### Data Protection Layers
1. **Automated Backups** - Scheduled, no manual intervention
2. **Verification** - Integrity checks before and after
3. **Checksums** - SHA256 for tamper detection
4. **Redundancy** - Primary + secondary locations
5. **Pre-Restore Backup** - Safety copy before restoration
6. **Compression** - Space efficient storage
7. **Monitoring** - Alerts on failures

### File Permissions
```bash
# Make scripts executable (already done)
chmod +x database/*.sh
chmod +x database/*.py

# Backup files are readable (automatic)
# Database requires read/write (automatic)
```

---

## 📈 Retention Policy

| Backup Type | Frequency | Kept | Total Coverage |
|------------|-----------|------|----------------|
| Hourly | Every hour | 24 | 1 day |
| Daily | 2:00 AM | 30 | 1 month |
| Weekly | Sunday 3 AM | 12 | 3 months |
| Monthly | 1st of month | 24 | 2 years |
| Yearly | Jan 1st | 10 | 10 years |

---

## 🚨 Alerts & Monitoring

### Health Check Results
- **Healthy** ✅ - All systems operational
- **Warning** ⚠️ - Non-critical issues detected
- **Critical** ❌ - Immediate attention required

### Alert Locations
```
backups/backup_health.json  - Current health status
backups/backup_alerts.log   - Alert history
backups/backup.log         - Backup operation log
```

### Critical Alerts
- 3+ consecutive backup failures
- Database integrity check failed
- Disk space < 1 GB
- No backups in 48 hours

---

## 💡 Best Practices

1. **✅ Run automation setup** - Set and forget
2. **✅ Monitor weekly** - Check status once a week
3. **✅ Test monthly** - Practice restoration monthly
4. **✅ Offsite backup** - Download backups periodically
5. **✅ Review logs** - Check for warnings
6. **✅ Update docs** - Keep team informed
7. **✅ Verify checksums** - Automatic, but understand it

---

## 🆘 Troubleshooting Index

| Problem | Solution | Reference |
|---------|----------|-----------|
| Backup failed | Check logs, run health check | [README.md](README.md#troubleshooting) |
| Can't restore | Verify backup exists, check permissions | [README.md](README.md#restoration) |
| Low disk space | Clean old backups, adjust retention | [DATABASE_MANAGEMENT.md](DATABASE_MANAGEMENT.md#troubleshooting) |
| Database locked | Restart app, check processes | [DATABASE_MANAGEMENT.md](DATABASE_MANAGEMENT.md#troubleshooting) |
| Corrupted DB | Restore from backup | [README.md](README.md#restoration) |
| Missing table | Run schema initialization | [DATABASE_MANAGEMENT.md](DATABASE_MANAGEMENT.md#schema-management) |

---

## 📞 Support Resources

### Check Status
```bash
python3 database/backup_manager.py --status
python3 database/health_check.py
```

### Check Logs
```bash
tail -n 50 backups/backup.log
cat backups/backup_alerts.log
cat backups/backup_health.json
```

### Get Help
1. Review this index
2. Check specific documentation
3. Run health diagnostics
4. Review logs
5. Consult Database Agent (this system)

---

## 🎓 Learning Path

**Beginner** (Day 1)
1. Read [QUICK_START_BACKUPS.md](../QUICK_START_BACKUPS.md)
2. Run setup scripts
3. Create manual backup
4. List backups

**Intermediate** (Week 1)
1. Read [README.md](README.md)
2. Understand backup types
3. Check health status
4. Review retention policy

**Advanced** (Month 1)
1. Read [DATABASE_MANAGEMENT.md](DATABASE_MANAGEMENT.md)
2. Practice restoration
3. Optimize retention settings
4. Set up offsite backups

**Expert** (Ongoing)
1. Monitor system health
2. Test disaster recovery
3. Optimize performance
4. Document procedures

---

## ✅ Quick Health Check

```bash
# Run this anytime to verify everything is OK
cd /Users/sahilkhatri/Projects/Work/brands/Haute/TabletTracker

echo "=== Database Status ==="
sqlite3 tablet_counter.db "PRAGMA integrity_check"

echo -e "\n=== Backup Status ==="
python3 database/backup_manager.py --status

echo -e "\n=== Health Check ==="
python3 database/health_check.py

echo -e "\n=== Recent Backups ==="
ls -lht backups/primary/ | head -n 5
```

---

**Last Updated:** December 6, 2025  
**Maintained By:** Database Agent  
**Status:** ✅ Active & Monitoring

**Your complete database protection system is ready!** 🎉

