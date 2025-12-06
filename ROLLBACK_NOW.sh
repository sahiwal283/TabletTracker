#!/bin/bash
# Emergency rollback to last working version before refactor

echo "=========================================="
echo "ROLLING BACK TO LAST WORKING VERSION"
echo "=========================================="
echo ""

# Commit before refactor started
WORKING_COMMIT="872f17f"

echo "Current version:"
git log --oneline -1

echo ""
echo "Rolling back to: $WORKING_COMMIT (before refactor)"
echo "This will restore the working code that matches your Nov 4 database backup"
echo ""

# Create a backup of current state (in case we need to reference it)
git branch backup-failed-refactor-$(date +%Y%m%d) 2>/dev/null

# Hard reset to working commit
echo "Executing: git reset --hard $WORKING_COMMIT"
git reset --hard $WORKING_COMMIT

echo ""
echo "✅ Rollback complete!"
echo ""
echo "Next steps for PythonAnywhere:"
echo "1. Edit WSGI file: /var/www/sahilk1_pythonanywhere_com_wsgi.py"
echo "2. Change it to:"
echo ""
echo "---START WSGI CONTENT---"
cat << 'WSGI'
import sys
import os

path = '/home/sahilk1/TabletTracker'
if path not in sys.path:
    sys.path.insert(0, path)

os.chdir(path)

from app import app as application
WSGI
echo "---END WSGI CONTENT---"
echo ""
echo "3. Reload web app in PythonAnywhere dashboard"
echo "4. Test the app"
echo ""
echo "=========================================="

