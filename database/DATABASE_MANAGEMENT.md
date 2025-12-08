# TabletTracker Database Management Guide

## Table of Contents

1. [Database Overview](#database-overview)
2. [Backup & Recovery](#backup--recovery)
3. [Schema Management](#schema-management)
4. [Data Integrity](#data-integrity)
5. [Performance Monitoring](#performance-monitoring)
6. [Migrations](#migrations)
7. [Troubleshooting](#troubleshooting)

---

## Database Overview

### Database Engine
- **Type:** SQLite 3
- **Location:** `tablet_counter.db`
- **Size:** Variable (typically 100-500 KB)

### Key Tables

| Table | Purpose | Key Relationships |
|-------|---------|-------------------|
| `warehouse_submissions` | Production counts from warehouse | `assigned_po_id → purchase_orders` |
| `purchase_orders` | PO tracking | Parent to `po_lines` |
| `po_lines` | Individual items in POs | `po_id → purchase_orders` |
| `shipments` | Shipment tracking | `po_id → purchase_orders` |
| `receiving` | Received shipments | `po_id → purchase_orders`, `shipment_id → shipments` |
| `small_boxes` | Box contents | `receiving_id → receiving` |
| `bags` | Bag/package details | `small_box_id → small_boxes` |
| `employees` | User accounts | None |
| `tablet_types` | Product types | Parent to `product_details` |
| `product_details` | Product specifications | `tablet_type_id → tablet_types` |
| `machine_counts` | Machine counts | `tablet_type_id → tablet_types` |
| `app_settings` | Application settings | None |

### Database Schema Location
- Schema definitions: `app/models/schema.py`
- Migrations: `app/models/migrations.py`
- Database utilities: `app/utils/db_utils.py`

---

## Backup & Recovery

### Automated Backup System

#### Setup
```bash
# Initial setup
python3 database/setup_backups.py

# Schedule automated backups
./database/schedule_backups.sh
```

#### Backup Types & Schedule
- **Hourly:** Every hour (24 kept)
- **Daily:** 2:00 AM (30 kept)
- **Weekly:** Sunday 3:00 AM (12 kept)
- **Monthly:** 1st of month 4:00 AM (24 kept)
- **Yearly:** January 1st 5:00 AM (10 kept)

#### Manual Backup
```bash
# Create daily backup
python3 database/backup_manager.py --daily

# Check backup status
python3 database/backup_manager.py --status

# List all backups
python3 database/backup_manager.py --list
```

#### Restoration

**Interactive (Recommended):**
```bash
python3 database/restore_manager.py --interactive
```

**Direct:**
```bash
python3 database/restore_manager.py backups/primary/tablet_counter_daily_20241206_020000.db.gz
```

**Force (skip verification):**
```bash
python3 database/restore_manager.py <backup_file> --force
```

### Backup Verification

All backups are automatically:
- ✅ Verified with PRAGMA integrity_check
- ✅ Checksummed with SHA256
- ✅ Compressed with gzip
- ✅ Stored in multiple locations
- ✅ Tested for data consistency

### Backup Locations
```
backups/
├── primary/          # Primary backup location
├── secondary/        # Redundant copy
├── archive/          # Long-term storage
└── before_restore/   # Pre-restoration backups
```

---

## Schema Management

### Current Schema Version
Check with:
```python
import sqlite3
conn = sqlite3.connect('tablet_counter.db')
cursor = conn.cursor()
cursor.execute("SELECT setting_value FROM app_settings WHERE setting_key = 'schema_version'")
version = cursor.fetchone()
print(f"Schema version: {version[0] if version else 'Unknown'}")
```

### Schema Updates

Schema is managed by `SchemaManager` class in `app/models/schema.py`:

```python
from app.models.schema import SchemaManager

# Initialize schema (creates tables if needed)
schema_manager = SchemaManager()
schema_manager.initialize_all_tables()
```

### Adding a New Table

1. Add table creation method to `SchemaManager`:
```python
def _create_your_new_table(self, c):
    """Create your_new_table"""
    c.execute('''CREATE TABLE IF NOT EXISTS your_new_table (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        column_name TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
```

2. Add to `initialize_all_tables()`:
```python
self._create_your_new_table(c)
```

3. Test in development first!

### Adding a Column to Existing Table

Use migrations in `app/models/migrations.py`:

```python
class MigrationRunner:
    def migration_XXX_add_new_column(self, cursor):
        """Add new_column to existing_table"""
        try:
            cursor.execute("ALTER TABLE existing_table ADD COLUMN new_column TEXT DEFAULT ''")
            print("✓ Migration XXX: Added new_column")
            return True
        except sqlite3.OperationalError as e:
            if 'duplicate column' in str(e).lower():
                print("  ℹ Migration XXX: Column already exists")
                return True
            raise
```

---

## Data Integrity

### Integrity Checks

#### Automated (via backup system)
```bash
python3 database/health_check.py
```

#### Manual
```bash
sqlite3 tablet_counter.db "PRAGMA integrity_check"
```

Expected output: `ok`

### Foreign Key Checks

Enable foreign key constraints:
```python
conn = sqlite3.connect('tablet_counter.db')
conn.execute("PRAGMA foreign_keys = ON")
```

Check foreign key violations:
```bash
sqlite3 tablet_counter.db "PRAGMA foreign_key_check"
```

### Data Validation

Located in `app/utils/calculations.py` and service files:
- `app/services/po_service.py`
- `app/services/product_service.py`
- `app/services/receiving_service.py`
- `app/services/submission_service.py`

### Referential Integrity

Key relationships to maintain:
- `warehouse_submissions.assigned_po_id → purchase_orders.id`
- `po_lines.po_id → purchase_orders.id`
- `shipments.po_id → purchase_orders.id`
- `receiving.po_id → purchase_orders.id`
- `receiving.shipment_id → shipments.id`
- `small_boxes.receiving_id → receiving.id`
- `bags.small_box_id → small_boxes.id`

---

## Performance Monitoring

### Database Size
```bash
ls -lh tablet_counter.db
```

### Table Sizes
```bash
sqlite3 tablet_counter.db ".tables"
sqlite3 tablet_counter.db "SELECT COUNT(*) FROM warehouse_submissions"
sqlite3 tablet_counter.db "SELECT COUNT(*) FROM purchase_orders"
```

### Query Performance

Enable query timing:
```bash
sqlite3 tablet_counter.db
.timer on
SELECT * FROM warehouse_submissions WHERE created_at > date('now', '-7 days');
```

### Optimization

#### Vacuum Database
```bash
sqlite3 tablet_counter.db "VACUUM"
```

#### Analyze for Query Optimization
```bash
sqlite3 tablet_counter.db "ANALYZE"
```

#### Create Indexes (if needed)
```sql
-- Example: Index on frequently queried columns
CREATE INDEX IF NOT EXISTS idx_submissions_created 
ON warehouse_submissions(created_at);

CREATE INDEX IF NOT EXISTS idx_submissions_po 
ON warehouse_submissions(assigned_po_id);
```

---

## Migrations

### Migration System

Migrations are handled by `MigrationRunner` in `app/models/migrations.py`.

### Running Migrations

Migrations run automatically on app startup via `initialize_all_tables()`.

### Creating a New Migration

1. Add migration method to `MigrationRunner`:
```python
def migration_XXX_your_description(self, cursor):
    """Description of what this migration does"""
    try:
        # Your migration code here
        cursor.execute("ALTER TABLE ...")
        print("✓ Migration XXX: Description")
        return True
    except sqlite3.OperationalError as e:
        # Handle already applied
        if 'duplicate column' in str(e).lower():
            print("  ℹ Migration XXX: Already applied")
            return True
        raise
```

2. Add to `run_all()`:
```python
self.migration_XXX_your_description(cursor)
```

3. Test thoroughly before deploying!

### Migration Best Practices

1. **Always use IF NOT EXISTS** for table creation
2. **Handle "already applied"** gracefully in migrations
3. **Test in development first**
4. **Backup before migrating** (automatic with our system)
5. **Make migrations idempotent** (safe to run multiple times)
6. **Document migration purpose** with clear docstrings

### Rollback Plan

If a migration fails:

1. Restore from backup:
   ```bash
   python3 database/restore_manager.py --interactive
   ```

2. Fix migration code

3. Test in development

4. Deploy fixed version

---

## Troubleshooting

### Database Locked Error

**Cause:** Another process is accessing the database

**Solution:**
```bash
# Check for processes using database
lsof tablet_counter.db

# If on PythonAnywhere, reload web app
# If local, restart Flask app
```

### Database Corrupted

**Check integrity:**
```bash
sqlite3 tablet_counter.db "PRAGMA integrity_check"
```

**If corrupted, restore from backup:**
```bash
python3 database/restore_manager.py --interactive
```

### Missing Tables

**Reinitialize schema:**
```python
from app.models.database import init_db
init_db()
```

### Data Inconsistency

**Check for orphaned records:**
```sql
-- Find submissions without valid PO
SELECT * FROM warehouse_submissions 
WHERE assigned_po_id IS NOT NULL 
  AND assigned_po_id NOT IN (SELECT id FROM purchase_orders);

-- Find PO lines without valid PO
SELECT * FROM po_lines 
WHERE po_id NOT IN (SELECT id FROM purchase_orders);
```

### Performance Issues

**Common causes:**
- Large number of records without indexes
- Missing VACUUM/ANALYZE
- Database file fragmentation

**Solutions:**
```bash
# Optimize database
sqlite3 tablet_counter.db "VACUUM"
sqlite3 tablet_counter.db "ANALYZE"

# Check database size
ls -lh tablet_counter.db

# Archive old data if needed
```

### Backup Failures

**Check health:**
```bash
python3 database/health_check.py
```

**Check logs:**
```bash
cat backups/backup.log
cat backups/backup_alerts.log
```

**Common causes:**
- Disk space full
- Permission issues
- Database locked

### Connection Issues

**Check database file permissions:**
```bash
ls -la tablet_counter.db
```

**Should be readable/writable by web server user**

**Fix permissions:**
```bash
chmod 644 tablet_counter.db
```

---

## Database Maintenance Schedule

### Daily
- ✅ Automated backup (2:00 AM)
- ✅ Health check (automatic)

### Weekly
- ✅ Automated weekly backup (Sunday)
- Review backup health status
- Check disk space

### Monthly
- ✅ Automated monthly backup (1st of month)
- Review backup logs
- Test restoration process
- Download offsite backup copy
- Run VACUUM if database > 10 MB

### Quarterly
- Review retention policies
- Archive old data if needed
- Performance review
- Update documentation

### Yearly
- ✅ Automated yearly backup (Jan 1st)
- Comprehensive data audit
- Security review
- Disaster recovery drill

---

## Quick Reference

### Common Commands

```bash
# Backups
python3 database/backup_manager.py --daily     # Create backup
python3 database/backup_manager.py --list      # List backups
python3 database/backup_manager.py --status    # Check status

# Restoration
python3 database/restore_manager.py --interactive  # Restore

# Health
python3 database/health_check.py               # Health check

# Direct database access
sqlite3 tablet_counter.db                       # Open database
.tables                                         # List tables
.schema table_name                              # Show table schema
SELECT COUNT(*) FROM table_name;                # Count records
```

### Important Files

| File | Purpose |
|------|---------|
| `tablet_counter.db` | Main database |
| `app/models/schema.py` | Schema definitions |
| `app/models/migrations.py` | Migration system |
| `app/utils/db_utils.py` | Database utilities |
| `database/backup_manager.py` | Backup system |
| `database/restore_manager.py` | Restore system |
| `database/health_check.py` | Health monitoring |

---

## Emergency Contacts & Resources

### Documentation
- SQLite Documentation: https://www.sqlite.org/docs.html
- Python sqlite3 module: https://docs.python.org/3/library/sqlite3.html

### Emergency Procedures
1. **Data Loss:** See [Backup & Recovery](#backup--recovery)
2. **Corruption:** Run integrity check, restore from backup
3. **Performance:** VACUUM, ANALYZE, check indexes
4. **Locked:** Restart app, check processes

### Support Checklist
Before seeking help:
- [ ] Run health check
- [ ] Review backup logs
- [ ] Check database integrity
- [ ] Check disk space
- [ ] Try restoration test
- [ ] Document error messages
- [ ] Note when issue started

---

**Last Updated:** December 6, 2024  
**Schema Version:** 1.15.8  
**Database Agent:** Responsible for all database operations, integrity, backups, and migrations

