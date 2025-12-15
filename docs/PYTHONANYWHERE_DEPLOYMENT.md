# PythonAnywhere Deployment Guide for TabletTracker v2.0

## Critical: Application Factory Pattern Changes

**TabletTracker v2.0 uses an application factory pattern.** The old `app.py` monolithic file has been refactored into modular blueprints. This requires updating your PythonAnywhere WSGI configuration.

---

## Step 1: Update WSGI File on PythonAnywhere

### Location
PythonAnywhere WSGI file is located at: `/var/www/sahilk1_pythonanywhere_com_wsgi.py`

### Required Changes

**OLD WSGI Configuration (will NOT work):**
```python
from app import app as application
```

**NEW WSGI Configuration (REQUIRED for v2.0):**
```python
#!/usr/bin/env python3
"""
WSGI configuration for PythonAnywhere deployment
TabletTracker v2.0 - Application Factory Pattern
"""

import sys
import os

# Add your project directory to the sys.path
path = '/home/sahilk1/TabletTracker'
if path not in sys.path:
    sys.path.insert(0, path)

# Change to the project directory
os.chdir(path)

# Import and create Flask application using factory pattern
try:
    from app import create_app
    application = create_app()
    print(f"✅ Flask app created successfully with {len(application.blueprints)} blueprints registered")
    if len(application.blueprints) == 0:
        print("⚠️  WARNING: No blueprints registered! Check blueprint imports.")
except Exception as e:
    # Log the error and raise it - don't fall back to old app.py
    import traceback
    error_msg = f"❌ CRITICAL: Failed to create Flask app: {str(e)}\n{traceback.format_exc()}"
    print(error_msg)
    raise

if __name__ == "__main__":
    application.run()
```

### How to Update on PythonAnywhere

1. Go to PythonAnywhere Web tab: https://www.pythonanywhere.com/user/sahilk1/webapps/
2. Click on your web app (`sahilk1.pythonanywhere.com`)
3. Scroll to "Code" section
4. Click on the WSGI configuration file link (blue text)
5. **Replace the entire contents** with the NEW configuration above
6. Click "Save" button (top right)
7. Go back to Web tab
8. Click green "Reload" button

---

## Step 2: Verify File Structure on Server

### Required Directory Structure
```
/home/sahilk1/TabletTracker/
├── app/                        # Package directory (contains __init__.py)
│   ├── __init__.py            # Application factory (create_app function)
│   ├── blueprints/            # All route handlers
│   ├── models/                # Database models
│   ├── services/              # Business logic
│   └── utils/                 # Helper functions
├── app.py                      # Entry point (imports create_app)
├── wsgi.py                     # Local WSGI file (reference only)
├── config.py
├── requirements.txt
├── database/
│   └── tablet_counter.db
└── templates/
```

### Check These Files Exist

**Via PythonAnywhere Bash Console:**
```bash
cd /home/sahilk1/TabletTracker
ls -la app/__init__.py  # Must exist and contain create_app()
ls -la app.py           # Should be ~23 lines, imports create_app
ls -la app/blueprints/  # Should contain all blueprint files
```

### Verify app/__init__.py Has create_app()
```bash
grep -n "def create_app" app/__init__.py
```
Should return: `10:def create_app(config_class=Config):`

---

## Step 3: Database Path Verification

**TabletTracker v2.0 uses:** `database/tablet_counter.db`

### Check Database Path in config.py
```bash
grep "DATABASE" config.py
```
Should show: `DATABASE_PATH = os.path.join(BASE_DIR, 'database', 'tablet_counter.db')`

### Verify Database Exists
```bash
ls -lh database/tablet_counter.db
```

If database doesn't exist at new location, move it:
```bash
mv tablet_counter.db database/tablet_counter.db
```

---

## Step 4: Install Updated Dependencies

```bash
cd /home/sahilk1/TabletTracker
source venv/bin/activate  # Activate virtual environment
pip install -r requirements.txt --upgrade
```

---

## Step 5: Reload Application

1. Go to Web tab on PythonAnywhere
2. Click green **"Reload sahilk1.pythonanywhere.com"** button
3. Wait 10 seconds for reload to complete

---

## Step 6: Verify Deployment

### Check Error Log
1. Go to Web tab
2. Scroll to "Log files" section
3. Click on **Error log** link
4. Look for recent entries

**Success indicators:**
```
✅ Flask app created successfully with 8 blueprints registered
WSGI app 0 (mountpoint='') ready in X seconds
```

**Error indicators to watch for:**
```
❌ ImportError: cannot import name 'app' from 'app'
   → WSGI file not updated correctly
   
❌ ImportError: cannot import name 'create_app' from 'app'
   → app/__init__.py not present or corrupted
   
❌ ModuleNotFoundError: No module named 'app.blueprints'
   → Blueprint files missing or incorrect structure
```

### Test Critical Paths

1. **Login Page:** `https://sahilk1.pythonanywhere.com/`
2. **Admin Login:** Use `admin` / `admin`
3. **Dashboard:** Should load without `progress_percent` error
4. **Purchase Orders:** `/purchase-orders` page
5. **Receiving:** `/receiving` page (formerly `/shipping`)

---

## Common Errors and Solutions

### Error: `ImportError: cannot import name 'app' from 'app'`
**Cause:** WSGI file still using old import style  
**Solution:** Update WSGI file to use `from app import create_app` (see Step 1)

### Error: `jinja2.exceptions.UndefinedError: 'progress_percent' is undefined`
**Cause:** Old template file on server  
**Solution:** Pull latest code from GitHub:
```bash
cd /home/sahilk1/TabletTracker
git fetch origin
git checkout refactor/v2.0-modernization
git pull origin refactor/v2.0-modernization
```

### Error: `werkzeug.routing.exceptions.BuildError: Could not build url for endpoint 'dashboard.admin_dashboard'`
**Cause:** Old template references to renamed endpoints  
**Solution:** Pull latest templates from GitHub (see above)

### Error: `sqlite3.OperationalError: no such column`
**Cause:** Database schema out of sync  
**Solution:** Run database migrations:
```bash
cd /home/sahilk1/TabletTracker
source venv/bin/activate
# Run any pending migrations if applicable
```

### Error: `NameError: name 'sqlite3' is not defined`
**Cause:** Missing import statement  
**Solution:** Already fixed in latest code, pull from GitHub

---

## Rollback to v1.15.8 (If Needed)

If v2.0 has critical issues, you can rollback:

### Quick Rollback Steps
```bash
cd /home/sahilk1/TabletTracker
git checkout main  # Switch back to stable main branch
```

Then update WSGI file back to old format:
```python
from app import app as application
```

And reload the web app.

---

## Post-Deployment Checklist

- [ ] WSGI file updated to use `create_app()`
- [ ] Application reloaded successfully
- [ ] Error log shows no critical errors
- [ ] Login page loads
- [ ] Admin can log in
- [ ] Dashboard loads without errors
- [ ] Purchase Orders page works
- [ ] Receiving page works
- [ ] Production submission works
- [ ] Reports generate correctly
- [ ] Zoho sync works

---

## Getting Help

### View Real-Time Logs
PythonAnywhere Bash Console:
```bash
tail -f /var/log/sahilk1.pythonanywhere.com.error.log
```

### Check Git Status
```bash
cd /home/sahilk1/TabletTracker
git branch  # Should show refactor/v2.0-modernization
git log -1  # Show last commit
git status  # Check for uncommitted changes
```

### Blueprint Registration Check
Create a test script to verify blueprints are loaded:
```python
from app import create_app
app = create_app()
print(f"Registered blueprints: {list(app.blueprints.keys())}")
```

Expected output:
```
['admin', 'api', 'auth', 'dashboard', 'production', 'purchase_orders', 'receiving', 'submissions']
```

---

## Important Notes

1. **Do not delete old `app.py`** - it's now a simple entry point that imports `create_app()`
2. **The `app/` directory is now a Python package** - it must have `__init__.py`
3. **All routes are in blueprints** - no routes should be in root `app.py`
4. **WSGI change is mandatory** - v2.0 will not work with old WSGI configuration

---

## Version Information

- **Local Version:** TabletTracker v1.15.8 → v2.0
- **Branch:** `refactor/v2.0-modernization`
- **Python Version:** 3.10.12
- **Flask Version:** Check `requirements.txt`

---

*Last Updated: December 10, 2025*  
*For questions, check GitHub issues or error logs*





