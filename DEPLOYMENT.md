# PythonAnywhere Deployment Guide

This guide will walk you through deploying TabletTracker v1.0.0 to PythonAnywhere.

## Prerequisites

1. PythonAnywhere account (free tier works)
2. Your project files uploaded to PythonAnywhere
3. Zoho API credentials ready

## Step-by-Step Deployment

### 1. Upload Your Files

1. Go to PythonAnywhere Dashboard > Files
2. Upload your TabletTracker project folder
3. Your files should be at: `/home/yourusername/TabletTracker/`

### 2. Create Virtual Environment

Open a PythonAnywhere console and run:

```bash
cd ~/TabletTracker
python3.10 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Setup Environment Variables

Create `.env` file in your project directory:

```bash
# In PythonAnywhere Files tab, create new file: .env
SECRET_KEY=your-strong-secret-key-here
ZOHO_CLIENT_ID=your_zoho_client_id
ZOHO_CLIENT_SECRET=your_zoho_client_secret  
ZOHO_REFRESH_TOKEN=your_zoho_refresh_token
ZOHO_ORGANIZATION_ID=your_org_id
FLASK_ENV=production
```

### 4. Initialize Database

In the console:

```bash
cd ~/TabletTracker
source venv/bin/activate
python setup_db.py
```

### 5. Configure Web App

1. Go to PythonAnywhere Dashboard > Web
2. Click "Add a new web app"
3. Choose "Manual configuration" > Python 3.10
4. Set Source code directory: `/home/yourusername/TabletTracker`
5. Edit WSGI configuration file:

```python
import sys
import os

# Add your project directory to the sys.path
path = '/home/yourusername/TabletTracker'  # Replace 'yourusername'
if path not in sys.path:
    sys.path.insert(0, path)

# Activate virtual environment
activate_this = '/home/yourusername/TabletTracker/venv/bin/activate_this.py'
with open(activate_this) as file_:
    exec(file_.read(), dict(__file__=activate_this))

# Import your Flask application
from app import app as application

if __name__ == "__main__":
    application.run()
```

6. Set up static files (if you have any):
   - URL: `/static/`
   - Directory: `/home/yourusername/TabletTracker/static/`

### 6. Test Deployment

1. Click "Reload" button in Web tab
2. Visit your app: `https://yourusername.pythonanywhere.com`
3. Test key features:
   - Warehouse form: `/warehouse`
   - Dashboard: `/dashboard` 
   - Admin panel: `/admin` (password: admin123)
   - Version check: `/version`

### 7. Zoho Integration Setup

1. Test Zoho connection: Visit `/api/test_zoho_connection`
2. If successful, sync POs: Click "Sync Zoho POs" in dashboard
3. Verify data appears correctly

## Security Notes

1. **Change the admin password** in `app.py` line 574
2. **Use a strong SECRET_KEY** in production
3. **Keep your .env file secure** - never commit it to git

## Troubleshooting

### Common Issues

1. **Import Errors**: Check virtual environment activation in WSGI file
2. **Database Errors**: Ensure `setup_db.py` ran successfully  
3. **Static Files**: Check static file mappings in Web tab
4. **Zoho API Issues**: Verify credentials and test connection endpoint

### Logs

Check error logs in PythonAnywhere Dashboard > Web > Log files

### Support

- PythonAnywhere Help: https://help.pythonanywhere.com/
- Application Version: Check `/version` endpoint

## Post-Deployment

1. Train your team on the new mobile interface
2. Test thoroughly with real data
3. Setup regular backups of your database
4. Monitor error logs for the first few days

## Version Management

Current version: **v1.0.0**

To deploy updates:
1. Upload new files to PythonAnywhere
2. Update version in `__version__.py`  
3. Run any new migrations
4. Reload the web app

---

**Deployment completed!** 🎉

Your TabletTracker is now live and ready for production use.
