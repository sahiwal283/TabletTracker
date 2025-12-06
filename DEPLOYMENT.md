# TabletTracker Deployment Guide for PythonAnywhere

## Quick Deployment Steps

### 1. Pull Latest Code
```bash
cd /home/sahilk1/TabletTracker
git pull origin main
```

### 2. Clear Python Cache
```bash
find . -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete
```

### 3. Run Database Migrations
```bash
python3 run_migration.py
```

**OR** run the deployment verification script:
```bash
python3 deploy_check.py
```

### 4. Update WSGI Configuration File

**CRITICAL**: You must manually update the WSGI file in PythonAnywhere's web interface.

1. Log into PythonAnywhere
2. Go to **Web** tab
3. Click on your web app (e.g., `sahilk1.pythonanywhere.com`)
4. Scroll down to **WSGI configuration file** section
5. Click the file path (usually `/var/www/sahilk1_pythonanywhere_com_wsgi.py`)
6. Replace the entire contents with:

```python
#!/usr/bin/env python3
"""
WSGI configuration for PythonAnywhere deployment
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
except ImportError as e:
    # If import fails, log the error
    import traceback
    error_msg = f"Failed to import create_app: {e}\n{traceback.format_exc()}"
    print(error_msg)
    raise
```

7. **Save** the file
8. **Reload** the web app (click the green "Reload" button)

### 5. Verify Deployment

Run the verification script:
```bash
python3 deploy_check.py
```

Or test manually:
```bash
python3 -c "from app import create_app; app = create_app(); print('✅ App created successfully')"
```

## Troubleshooting

### Error: `ImportError: cannot import name 'app' from 'app'`
- **Cause**: WSGI file is trying to import `app` instead of using `create_app()`
- **Fix**: Update WSGI file as shown in step 4 above

### Error: `sqlite3.OperationalError: no such column/table`
- **Cause**: Database migrations haven't been run
- **Fix**: Run `python3 run_migration.py` or `python3 deploy_check.py`

### Error: `ModuleNotFoundError: No module named 'app.models.purchase_order'`
- **Cause**: Python cache or outdated `app/models/__init__.py`
- **Fix**: 
  1. Clear Python cache (step 2 above)
  2. Pull latest code (step 1)
  3. Verify `app/models/__init__.py` doesn't import non-existent modules

### Error: `404 Not Found`
- **Cause**: App is running but routes aren't registered
- **Fix**: 
  1. Check WSGI file is correct
  2. Verify blueprints are registered in `app/__init__.py`
  3. Check error logs in PythonAnywhere dashboard

### Error: `NameError: name 'traceback' is not defined`
- **Cause**: Missing import in old code
- **Fix**: This shouldn't happen with new code. If it does, check that you've pulled the latest code

## File Structure

After deployment, your project should have:
```
/home/sahilk1/TabletTracker/
├── app/
│   ├── __init__.py          # Application factory
│   ├── blueprints/          # Route handlers
│   ├── models/              # Database models and migrations
│   ├── services/            # Business logic
│   └── utils/               # Utility functions
├── wsgi.py                  # Local WSGI file (for reference)
├── run_migration.py         # Migration script
└── deploy_check.py          # Deployment verification
```

## Important Notes

1. **WSGI File**: The WSGI file in PythonAnywhere's web interface is separate from `wsgi.py` in your project. You must update it manually through the web interface.

2. **Database Path**: The database file (`tablet_counter.db`) should be in your project root directory (`/home/sahilk1/TabletTracker/`).

3. **Virtual Environment**: If you're using a virtual environment, make sure PythonAnywhere is configured to use it.

4. **Permissions**: Ensure the database file has write permissions:
   ```bash
   chmod 664 tablet_counter.db
   ```

## Support

If you encounter issues not covered here:
1. Check PythonAnywhere error logs (Web tab → Error log)
2. Check server logs (Web tab → Server log)
3. Run `deploy_check.py` to verify setup
4. Check that all files were pulled from Git correctly
