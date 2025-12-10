# 🚀 Deploy TabletTracker v2.0 to PythonAnywhere - Quick Guide

## ⚠️ CRITICAL: You MUST Update the WSGI File

The refactored v2.0 uses an **application factory pattern**. The old WSGI configuration will NOT work.

---

## 📋 Quick Deployment Steps

### 1️⃣ Update Code on Server
```bash
cd /home/sahilk1/TabletTracker
git fetch origin
git checkout refactor/v2.0-modernization
git pull origin refactor/v2.0-modernization
```

### 2️⃣ Update WSGI File (MANDATORY)

**Go to:** https://www.pythonanywhere.com/user/sahilk1/webapps/

**Click:** WSGI configuration file (blue link in "Code" section)

**Replace entire contents with:**
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
    # Log the error and raise it
    import traceback
    error_msg = f"❌ CRITICAL: Failed to create Flask app: {str(e)}\n{traceback.format_exc()}"
    print(error_msg)
    raise

if __name__ == "__main__":
    application.run()
```

**Click:** Save (top right)

### 3️⃣ Reload Web App

**Go to:** Web tab  
**Click:** Green "Reload" button  
**Wait:** 10 seconds

### 4️⃣ Check Error Log

**Scroll to:** "Log files" section  
**Click:** Error log

**✅ Success looks like:**
```
✅ Flask app created successfully with 8 blueprints registered
WSGI app 0 (mountpoint='') ready in X seconds
```

**❌ If you see errors:**
- `ImportError: cannot import name 'app'` → WSGI file not updated correctly, redo step 2
- `ModuleNotFoundError: No module named 'app.blueprints'` → Code not pulled correctly, redo step 1

### 5️⃣ Test the Application

Visit: `https://sahilk1.pythonanywhere.com/`

**Test these pages:**
- ✅ Login page loads
- ✅ Admin login works (admin/admin)
- ✅ Dashboard loads without errors
- ✅ Purchase Orders page works (`/purchase-orders`)
- ✅ Receiving page works (`/receiving`)

---

## 🔧 Troubleshooting

### Error: "progress_percent is undefined"
**Solution:** Code not updated, pull latest:
```bash
cd /home/sahilk1/TabletTracker
git pull origin refactor/v2.0-modernization
```
Then reload web app.

### Error: "Could not build url for endpoint 'dashboard.admin_dashboard'"
**Solution:** Old endpoint names, pull latest code (see above).

### Error: ImportError when importing blueprints
**Solution:** Check file structure:
```bash
ls -la app/blueprints/
```
Should show: `admin.py`, `api.py`, `auth.py`, `dashboard.py`, `production.py`, `purchase_orders.py`, `receiving.py`, `submissions.py`

---

## 🔙 Emergency Rollback

If v2.0 doesn't work, rollback to v1.15.8:

```bash
cd /home/sahilk1/TabletTracker
git checkout main
```

Update WSGI file back to:
```python
from app import app as application
```

Reload web app.

---

## 📊 What Changed in v2.0?

| Before (v1.x) | After (v2.0) | Why |
|---------------|--------------|-----|
| Single 6864-line `app.py` | Modular blueprints in `app/blueprints/` | Maintainability |
| `from app import app` | `from app import create_app` + `create_app()` | Application factory pattern |
| `/shipping` route | `/receiving` route | Semantic accuracy |
| `admin_dashboard()` | `dashboard_view()` | Naming consistency |
| Ad-hoc migrations | Numbered migrations | Better version control |

---

## 📞 Need Help?

**Full Documentation:** `docs/PYTHONANYWHERE_DEPLOYMENT.md`

**Check Logs:**
```bash
tail -f /var/log/sahilk1.pythonanywhere.com.error.log
```

**Verify Blueprints:**
```bash
cd /home/sahilk1/TabletTracker
python3 -c "from app import create_app; app = create_app(); print(list(app.blueprints.keys()))"
```

Expected: `['admin', 'api', 'auth', 'dashboard', 'production', 'purchase_orders', 'receiving', 'submissions']`

---

## ✅ Post-Deployment Checklist

After deployment, verify:

- [ ] WSGI file updated with `create_app()` pattern
- [ ] Web app reloaded successfully
- [ ] Error log shows no critical errors
- [ ] Login page loads
- [ ] Admin dashboard accessible
- [ ] Can view purchase orders
- [ ] Can view receiving page
- [ ] Can submit production data
- [ ] Reports generate correctly

---

**Time Required:** ~5-10 minutes  
**Risk Level:** Low (easy rollback available)  
**Last Updated:** December 10, 2025

