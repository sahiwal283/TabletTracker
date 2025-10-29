# Production Deployment Guide - v1.21.0

## Quick Deploy (Recommended)

SSH into PythonAnywhere and run:

```bash
cd ~/TabletTracker
./DEPLOY_V1.21.0.sh
```

Then reload your web app from the PythonAnywhere Web tab.

---

## Manual Deployment Steps

If you prefer to run steps manually:

### 1. SSH into PythonAnywhere

```bash
ssh sahilk1@ssh.pythonanywhere.com
```

### 2. Navigate to your app directory

```bash
cd ~/TabletTracker
```

### 3. Pull latest code

```bash
git pull origin main
```

### 4. Run database migration

```bash
python3 migrate_to_v1.21.0.py
```

**Important:** This migration is **safe and idempotent** - it can be run multiple times without issues. It will:
- Add `submission_date` column if missing
- Backfill existing data from `created_at`
- Verify all required columns exist

### 5. Reload web app

1. Go to the **Web** tab on PythonAnywhere
2. Click the **Reload** button for `sahilk1.pythonanywhere.com`
3. Wait for the reload to complete (green "Configuration" text)

### 6. Verify deployment

Visit: https://sahilk1.pythonanywhere.com/dashboard

Check:
- ✅ Footer shows **v1.21.0**
- ✅ Recent Submissions shows PO status badges (Open/Closed)
- ✅ Filter toggle works to show/hide closed POs
- ✅ Clicking PO line items opens submission modal
- ✅ No errors in the browser console

---

## What's New in v1.21.0

### Features
- **Sequential PO Filling**: Older POs must be completely filled before newer POs receive submissions
- **Clickable PO Line Items**: Click any line item to see all submissions assigned to that PO
- **PO Status Indicators**: Visual badges show Open/Closed status in Recent Submissions
- **Filter Toggle**: Checkbox to show/hide submissions for closed POs (hidden by default)
- **Draft PO Exclusion**: Draft POs no longer receive submissions

### Bug Fixes
- Fixed PO assignment order to prioritize oldest PO numbers
- Fixed database compatibility with optional columns
- Fixed employee name retrieval in submissions endpoint

---

## Rollback Plan

If something goes wrong, you can rollback to v1.15.8:

```bash
cd ~/TabletTracker
git checkout v1.15.8
# Reload web app from PythonAnywhere Web tab
```

The database changes are backward-compatible, so rollback is safe.

---

## Troubleshooting

### Migration fails
- Check database file permissions
- Ensure `tablet_counter.db` exists in the app directory
- Review migration output for specific errors

### Web app won't reload
- Check error logs in PythonAnywhere
- Verify Python version (should be 3.10+)
- Check that all dependencies are installed

### Features not working
- Hard refresh browser (Ctrl+Shift+R or Cmd+Shift+R)
- Clear browser cache
- Check browser console for JavaScript errors

---

## Support

If you encounter issues:
1. Check the error logs on PythonAnywhere
2. Verify the migration ran successfully
3. Review this guide for missed steps
4. Contact your developer for assistance

