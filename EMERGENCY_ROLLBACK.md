# 🚨 EMERGENCY ROLLBACK TO WORKING VERSION

## Current Situation
- Database restored with 60 submissions (Sept 2 - Oct 29)
- App code is broken from failed refactor
- Need to restore working code to match the database

## Rollback Instructions for PythonAnywhere

### Step 1: Find the last working commit
```bash
cd /home/sahilk1/TabletTracker
git log --oneline --all | grep -E "v1\.[0-9]+" | head -10
```

### Step 2: Roll back to last working version (before refactor)
```bash
# Find the commit before the refactor started (likely around Nov 4-5)
git log --oneline --before="2025-12-06" | head -5

# Roll back to that commit (replace COMMIT_HASH with actual hash)
git reset --hard COMMIT_HASH

# Or use a specific version tag if available
git checkout v1.65.1  # or whatever the last working version was
```

### Step 3: Restore the simple WSGI file
Edit `/var/www/sahilk1_pythonanywhere_com_wsgi.py`:

```python
import sys
import os

# Add your project directory to the sys.path
path = '/home/sahilk1/TabletTracker'
if path not in sys.path:
    sys.path.insert(0, path)

os.chdir(path)

# Import Flask app from the old app.py
from app import app as application
```

### Step 4: Reload the web app
Go to PythonAnywhere → Web tab → Click "Reload"

### Step 5: Test the app
Visit your site and verify:
- ✅ Login works
- ✅ Can see 60 submissions
- ✅ Can see 35 purchase orders
- ✅ All features work

## What Went Wrong
1. Refactor attempted to reorganize code into modular structure
2. `init_db()` was called during refactor, wiping the database
3. No backup was created before starting
4. Database restored from Nov 4 backup
5. Now need to restore code to match that time period

## Prevention for Future
1. **ALWAYS** create database backup before ANY code changes
2. Test refactors in a separate environment first
3. Set up automatic daily database backups
4. Use database migrations instead of `init_db()` for schema changes

