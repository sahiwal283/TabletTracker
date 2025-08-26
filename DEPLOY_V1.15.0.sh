#!/bin/bash
# PythonAnywhere Deployment Script for TabletTracker v1.15.0
# Run this in your PythonAnywhere bash console

echo "🚀 Deploying TabletTracker v1.15.0..."

# Step 1: Navigate to project directory
cd ~/TabletTracker

# Step 2: Pull latest version from GitHub
echo "📥 Pulling latest code from GitHub..."
git fetch origin
git reset --hard origin/main
git pull origin main

# Step 3: Check version
echo "📋 Current version:"
python3 -c "from __version__ import __version__; print(f'Version: {__version__}')"

# Step 4: Activate virtual environment and install dependencies
echo "📦 Installing dependencies..."
source venv/bin/activate
pip install -r requirements.txt

# Step 5: Run database migrations
echo "🗄️ Running database migrations..."
python3 migrate_language_column.py

# Step 6: Verify database structure
echo "🔍 Verifying database..."
python3 -c "
import sqlite3
conn = sqlite3.connect('tablet_counter.db')
cursor = conn.cursor()
cursor.execute('PRAGMA table_info(employees)')
columns = [col[1] for col in cursor.fetchall()]
print('✅ Employee table columns:', columns)
if 'preferred_language' in columns and 'role' in columns:
    print('✅ Database schema is up to date')
else:
    print('❌ Missing required columns')
conn.close()
"

# Step 7: Test app import
echo "🧪 Testing app import..."
python3 -c "
try:
    from app import app
    print('✅ App imports successfully')
    with app.test_request_context():
        print('✅ App context works')
except Exception as e:
    print(f'❌ App import failed: {e}')
"

# Step 8: Update WSGI file
echo "🔧 Updating WSGI configuration..."
cat > /var/www/sahilk1_pythonanywhere_com_wsgi.py << 'EOF'
#!/usr/bin/env python3
"""
WSGI configuration for TabletTracker v1.15.0
Updated for stable monolithic application
"""

import sys
import os

# Add your project directory to the sys.path
path = '/home/sahilk1/TabletTracker'
if path not in sys.path:
    sys.path.insert(0, path)

# Import the Flask application
from app import app as application

if __name__ == "__main__":
    application.run()
EOF

echo "✅ WSGI file updated"

# Step 9: Check file permissions
echo "🔒 Checking file permissions..."
chmod +x /var/www/sahilk1_pythonanywhere_com_wsgi.py
ls -la /var/www/sahilk1_pythonanywhere_com_wsgi.py

echo ""
echo "🎉 DEPLOYMENT COMPLETE!"
echo ""
echo "Next steps:"
echo "1. Go to PythonAnywhere Web tab"
echo "2. Reload your web app: sahilk1.pythonanywhere.com"
echo "3. Test the unified login at: https://sahilk1.pythonanywhere.com"
echo ""
echo "✨ Features now available:"
echo "   - Unified login system"
echo "   - Language preferences"
echo "   - 3-tier role system"
echo "   - Centered admin UI"
echo ""
echo "🔗 Your app: https://sahilk1.pythonanywhere.com"
