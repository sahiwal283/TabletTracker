# Rollback to v1.66.0 (Last Working Version Before Refactor)

## Important Notes

⚠️ **WARNING**: Rolling back will:
- Remove all refactoring work (modular structure, blueprints, etc.)
- Restore the old monolithic `app.py` structure
- You'll need to update the WSGI file on PythonAnywhere to use the old structure

## Steps to Rollback

### On PythonAnywhere:

1. **SSH into PythonAnywhere** (or use Bash console)

2. **Navigate to project directory:**
   ```bash
   cd /home/sahilk1/TabletTracker
   ```

3. **Create a backup branch (optional but recommended):**
   ```bash
   git branch backup-before-rollback
   ```

4. **Rollback to commit 872f17f (v1.66.0):**
   ```bash
   git reset --hard 872f17f
   ```

5. **Force push to remote (if you want to update the remote):**
   ```bash
   git push origin main --force
   ```
   ⚠️ **WARNING**: Force push will overwrite remote history. Only do this if you're sure.

6. **Restore the old WSGI file:**
   The WSGI file should use:
   ```python
   from app import app as application
   ```
   Instead of:
   ```python
   from app import create_app
   application = create_app()
   ```

7. **Restore the old app.py file:**
   Make sure `app.py` exists in the root directory (it should after rollback)

8. **Clear Python cache:**
   ```bash
   find . -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true
   find . -type f -name "*.pyc" -delete
   ```

9. **Reload the web app** in PythonAnywhere dashboard

## Alternative: Rollback Locally First

If you want to test locally first:

```bash
cd /Users/sahilkhatri/Projects/Work/brands/Haute/TabletTracker
git reset --hard 872f17f
```

Then test locally before pushing to PythonAnywhere.

## What Will Be Restored

- Old monolithic `app.py` structure
- All routes in single file
- Old database initialization in `app.py`
- Version 1.66.0

## What Will Be Lost

- All refactoring work (modular structure)
- Blueprint-based routing
- New migration system
- Service layer
- Utility modules

