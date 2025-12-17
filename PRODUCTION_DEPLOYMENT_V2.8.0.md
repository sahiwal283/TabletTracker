# Production Deployment Guide - v2.8.0

**Critical**: This version includes new dependencies that MUST be installed on production.

---

## 🚨 Pre-Deployment Checklist

Before deploying v2.8.0 to PythonAnywhere:

- [ ] Read this entire document
- [ ] Backup current database
- [ ] Note current working version
- [ ] Have rollback plan ready

---

## 📦 Step 1: Install New Dependencies on PythonAnywhere

### Open Bash Console on PythonAnywhere

1. Log in to PythonAnywhere
2. Go to **Consoles** tab
3. Start a **Bash console**

### Install Dependencies

```bash
# Navigate to your project directory
cd ~/TabletTracker

# Activate your virtual environment
source venv/bin/activate

# Pull latest code from GitHub
git pull origin main

# Install NEW dependencies (CRITICAL!)
pip install Flask-WTF==1.2.1
pip install Flask-Limiter==3.5.0
pip install python-magic==0.4.27
pip install bleach==6.1.0

# Or install all at once
pip install -r requirements.txt

# Verify installations
pip list | grep -E "Flask-WTF|Flask-Limiter|bleach|python-magic"
```

**Expected Output:**
```
Flask-WTF         1.2.1
Flask-Limiter     3.5.0
bleach            6.1.0
python-magic      0.4.27
```

---

## ⚙️ Step 2: Set Environment Variables

### On PythonAnywhere Web Tab

1. Go to **Web** tab
2. Scroll to **Environment Variables** section
3. Add/verify these variables:

```bash
SECRET_KEY = [your-strong-secret-key-minimum-32-chars]
ADMIN_PASSWORD = [your-secure-admin-password]
FLASK_ENV = production
```

**CRITICAL**: If these are not set, the application will fail to start!

---

## 🔄 Step 3: Reload Web App

### Option A: Via Web Interface
1. Go to **Web** tab
2. Click green **"Reload"** button at the top

### Option B: Via Bash Console
```bash
touch /var/www/sahilk1_pythonanywhere_com_wsgi.py
```

---

## ✅ Step 4: Verify Deployment

### Test 1: Check Application Starts
1. Visit your site URL
2. Should show login page
3. No errors in console

### Test 2: Test Login
1. Log in with credentials
2. Should work without errors
3. Check browser console for errors

### Test 3: Check Error Log
1. Go to **Web** tab
2. Click **Error log** link
3. Should see no new errors

### Test 4: Test CSRF Protection
1. Open browser dev tools (F12)
2. Go to Console
3. Run: `console.log(getCSRFToken())`
4. Should print a token value (not null)

### Test 5: Test a Form
1. Try submitting a warehouse form
2. Should work without 400 errors
3. Check Network tab to see CSRF token in request

---

## 🐛 Troubleshooting

### Error: "ModuleNotFoundError: No module named 'flask_wtf'"

**Cause**: New dependencies not installed

**Fix**:
```bash
cd ~/TabletTracker
source venv/bin/activate
pip install Flask-WTF==1.2.1 Flask-Limiter==3.5.0 bleach==6.1.0 python-magic==0.4.27
```

Then reload web app.

---

### Error: "ModuleNotFoundError: No module named 'bcrypt'"

**Cause**: Missing bcrypt module

**Fix**:
```bash
cd ~/TabletTracker
source venv/bin/activate
pip install bcrypt==4.1.2
```

Then reload web app.

---

### Error: "ValueError: SECRET_KEY environment variable must be set in production"

**Cause**: Environment variable not set

**Fix**:
1. Go to Web tab
2. Add environment variable: `SECRET_KEY` = your-strong-key
3. Reload web app

---

### Error: "400 Bad Request: The CSRF token is missing"

**Cause**: Form submitted without CSRF token (shouldn't happen in v2.8.0)

**Fix**: This shouldn't occur in v2.8.0+ as all forms have CSRF tokens. If it does:
1. Check browser console for JavaScript errors
2. Verify `getCSRFToken()` function exists in page source
3. Check meta tag: `<meta name="csrf-token" content="...">`

---

### Error: "UnboundLocalError: local variable 'conn' referenced before assignment"

**Cause**: Bug in older version of code

**Fix**: This has been fixed in commit 334bc32. Ensure you pulled latest code:
```bash
cd ~/TabletTracker
git pull origin main
```

---

## 📋 Complete Deployment Script

Run this in PythonAnywhere Bash console:

```bash
#!/bin/bash

echo "🚀 Deploying TabletTracker v2.8.0..."

# Navigate to project
cd ~/TabletTracker || exit 1

# Activate venv
source venv/bin/activate || exit 1

# Pull latest code
echo "📥 Pulling latest code..."
git pull origin main || exit 1

# Install dependencies
echo "📦 Installing dependencies..."
pip install -r requirements.txt || exit 1

# Verify key packages
echo "✅ Verifying installations..."
python3 -c "import flask_wtf; print('Flask-WTF:', flask_wtf.__version__)"
python3 -c "import flask_limiter; print('Flask-Limiter installed')"
python3 -c "import bleach; print('Bleach:', bleach.__version__)"
python3 -c "import bcrypt; print('Bcrypt installed')"

# Check for syntax errors
echo "🔍 Checking for syntax errors..."
python3 -m py_compile app/blueprints/api.py || exit 1
python3 -m py_compile app/__init__.py || exit 1

echo "✅ All checks passed!"
echo "🔄 Please reload your web app from the Web tab"
```

---

## 🎯 What's New in v2.8.0

### Security Enhancements:
- ✅ CSRF Protection (Flask-WTF)
- ✅ Rate Limiting (5 login attempts/min)
- ✅ Session Fixation Fix
- ✅ Enhanced Security Headers
- ✅ Content-Security-Policy
- ✅ Secure Error Handling
- ✅ XSS Protection Utilities

### Bug Fixes:
- ✅ Fixed UnboundLocalError in test_zoho_connection
- ✅ Fixed UnboundLocalError in find_org_id
- ✅ Fixed indentation errors
- ✅ Updated all 56+ fetch calls with CSRF protection

---

## 🔄 Rollback Plan

If issues occur:

### Quick Rollback
```bash
cd ~/TabletTracker
git log --oneline -5  # See recent commits
git checkout 4f3cef9  # Previous stable version (v2.7.0)
touch /var/www/sahilk1_pythonanywhere_com_wsgi.py  # Reload
```

### Full Rollback
1. Go to PythonAnywhere Web tab
2. Click **"Reload"**
3. If still broken:
   ```bash
   cd ~/TabletTracker
   git reset --hard origin/main^  # Go back one commit
   ```

---

## 📞 Support

If deployment fails:
1. Check error log on PythonAnywhere Web tab
2. Review this guide's troubleshooting section
3. Check that all dependencies are installed
4. Verify environment variables are set

---

## ✅ Post-Deployment Verification

After deployment, verify:

1. **Application loads**: Visit homepage - should show login
2. **Login works**: Log in with credentials
3. **Forms work**: Submit a form - should succeed
4. **CSRF protection**: Check browser console - `getCSRFToken()` should return token
5. **Rate limiting**: Try 6+ failed logins - should block after 5
6. **No errors**: Check error log - should be clean

---

**Deployment Time Estimate**: 10-15 minutes

**Complexity**: Low (just install dependencies and reload)

**Risk Level**: Low (all changes are backward compatible)

---

*Last Updated*: December 17, 2025
