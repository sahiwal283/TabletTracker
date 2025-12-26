# PythonAnywhere Deployment Fix for v2.0

## Problem
The refactored v2.0 uses an application factory pattern (`create_app()`), but PythonAnywhere's WSGI file still tries to import the old `app` object directly, causing:

```
ImportError: cannot import name 'app' from 'app'
```

## Solution

### Step 1: Pull the Latest Code on PythonAnywhere

SSH into PythonAnywhere or use their Bash console:

```bash
cd /home/sahilk1/TabletTracker
git pull origin refactor/v2.0-modernization
```

### Step 2: Update the WSGI Configuration File

1. Go to **PythonAnywhere Dashboard** → **Web** tab
2. Click on your web app (sahilk1.pythonanywhere.com)
3. Scroll down to **Code section**
4. Click the link to edit your **WSGI configuration file**
5. Replace the entire content with:

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

6. **Save** the file (green button at the top)

### Step 3: Reload the Web App

1. Go back to the **Web** tab
2. Click the big green **"Reload sahilk1.pythonanywhere.com"** button at the top
3. Wait for the reload to complete (green checkmark)

### Step 4: Verify It Works

1. Open your app: https://sahilk1.pythonanywhere.com
2. You should see the login page (not a white screen)
3. Check the **Error log** on the Web tab - you should see:
   ```
   ✅ Flask app created successfully with 8 blueprints registered
   ```

### Step 5: Check for Errors

If you still see errors:

1. Go to **Web** tab → **Error log** 
2. Look for the actual error message
3. Common issues:
   - Missing dependencies: `pip install -r requirements.txt` in your venv
   - Database path issues: Check `config.py` has correct path
   - Import errors: Check all blueprint imports in `app/__init__.py`

## Troubleshooting

### Still Getting ImportError?

Check that your project structure looks like this:

```
/home/sahilk1/TabletTracker/
├── app/
│   ├── __init__.py          ← Must contain create_app()
│   ├── blueprints/          ← All route files
│   ├── models/
│   ├── services/
│   └── utils/
├── database/
│   └── tablet_counter.db
├── templates/
├── config.py
├── wsgi.py                  ← Updated in this fix
└── requirements.txt
```

### Check Blueprint Registration

In the PythonAnywhere Bash console:

```bash
cd /home/sahilk1/TabletTracker
source venv/bin/activate
python -c "from app import create_app; app = create_app(); print(f'Blueprints: {list(app.blueprints.keys())}')"
```

You should see 8 blueprints:
- `auth`
- `admin`
- `api`
- `dashboard`
- `production`
- `purchase_orders`
- `receiving`
- `submissions`

### Database Permissions

If you get database errors:

```bash
cd /home/sahilk1/TabletTracker
chmod 666 database/tablet_counter.db
chmod 777 database/
```

## Rollback Plan

If v2.0 doesn't work and you need to go back to the old version:

```bash
cd /home/sahilk1/TabletTracker
git checkout main
```

Then update the WSGI file back to the old format:

```python
import sys
path = '/home/sahilk1/TabletTracker'
if path not in sys.path:
    sys.path.insert(0, path)

from app import app as application
```

And reload the web app.

## Success Indicators

✅ **No errors in Error log**  
✅ **Login page loads**  
✅ **Can log in as admin**  
✅ **Dashboard loads with data**  
✅ **All navigation links work**  

If all of these work, your v2.0 deployment is successful! 🎉









