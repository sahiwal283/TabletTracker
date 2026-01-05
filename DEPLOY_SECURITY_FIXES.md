# Safe Deployment Guide for Security Fixes

## ⚠️ Important Notes

1. **python-magic is NOT used** - We can skip it if it causes issues
2. **CSRF tokens** - Existing forms will need CSRF tokens added
3. **Rate limiting** - May affect legitimate users if too strict
4. **Test in staging first** if possible

## Step-by-Step Deployment

### Step 1: Backup Current State

```bash
cd ~/TabletTracker

# Backup database
cp database/tablet_counter.db database/tablet_counter.db.backup.$(date +%Y%m%d_%H%M%S)

# Note current commit (for rollback)
git log -1 --oneline > /tmp/current_commit.txt
cat /tmp/current_commit.txt
```

### Step 2: Pull Latest Code

```bash
cd ~/TabletTracker
git fetch origin
git pull origin main
```

### Step 3: Install Dependencies (Skip python-magic if it fails)

```bash
# Try installing all dependencies
pip3.10 install --user Flask-WTF==1.2.1 Flask-Limiter==3.5.0 bleach==6.1.0

# If python-magic fails, that's OK - it's not used in the code
# You can skip it:
# pip3.10 install --user python-magic==0.4.27 || echo "python-magic skipped (not critical)"
```

### Step 4: Verify Environment Variables

```bash
# Check if SECRET_KEY is set (CRITICAL)
python3 -c "import os; from dotenv import load_dotenv; load_dotenv(); print('SECRET_KEY:', 'SET' if os.getenv('SECRET_KEY') else 'MISSING')"
```

If SECRET_KEY is missing, add it to your `.env` file or set it in PythonAnywhere's environment.

### Step 5: Test Database Migration (if needed)

```bash
# Check current Alembic version
python3 -c "import sqlite3; conn = sqlite3.connect('database/tablet_counter.db'); print(conn.execute('SELECT * FROM alembic_version').fetchone()); conn.close()"

# Run migrations if needed
alembic upgrade head
```

### Step 6: Test Import (Check for Errors)

```bash
# Test if app imports correctly
python3 -c "from app import create_app; app = create_app(); print('✅ App created successfully')"
```

### Step 7: Check for CSRF Issues

The new CSRF protection might break existing AJAX requests. Check your browser console after deployment.

### Step 8: Reload Web App

1. Go to PythonAnywhere Dashboard → **Web** tab
2. Click **Reload** button
3. Wait for green "Configuration" status

### Step 9: Test Critical Functions

1. **Login** - Should work normally
2. **Rate limiting** - Try 6 failed logins, should get rate limited
3. **Forms** - Check if forms submit correctly
4. **File uploads** - Test if they still work

## Rollback Plan (If Something Breaks)

### Quick Rollback

```bash
cd ~/TabletTracker

# Restore previous commit
git log --oneline | head -5  # Find the commit before security fixes
git checkout <previous-commit-hash>

# Restore database backup if needed
cp database/tablet_counter.db.backup.* database/tablet_counter.db

# Reload web app from PythonAnywhere Web tab
```

### Partial Rollback (Disable CSRF if it breaks things)

If CSRF is causing issues, you can temporarily disable it:

Edit `app/__init__.py` and comment out:
```python
# csrf = CSRFProtect()
# csrf.init_app(app)
```

## Potential Issues & Solutions

### Issue 1: python-magic Installation Fails
**Solution:** Skip it - it's not used in the code. Remove from requirements.txt if needed.

### Issue 2: CSRF Token Errors
**Solution:** Forms need CSRF tokens. Check browser console for errors. May need to update templates.

### Issue 3: Rate Limiting Too Strict
**Solution:** Adjust limits in `app/__init__.py`:
```python
default_limits=["200 per day", "50 per hour"]  # Make these higher if needed
```

### Issue 4: Import Errors
**Solution:** Check if all dependencies installed:
```bash
pip3.10 list | grep -E "(Flask-WTF|Flask-Limiter|bleach)"
```

## Verification Checklist

After deployment:
- [ ] App loads without errors
- [ ] Login works
- [ ] Forms submit correctly
- [ ] No CSRF errors in browser console
- [ ] Rate limiting works (test with failed logins)
- [ ] Security headers present (check browser DevTools → Network → Headers)

## Need Help?

If something breaks:
1. Check PythonAnywhere error logs (Dashboard → Web → Error log)
2. Check browser console for JavaScript errors
3. Try the rollback plan above








