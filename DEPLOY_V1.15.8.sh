#!/bin/bash
# TabletTracker v1.15.8 Deployment Script for PythonAnywhere
# Run this script in your PythonAnywhere console

echo "🚀 Deploying TabletTracker v1.15.8 to PythonAnywhere..."

# Navigate to project directory
cd ~/TabletTracker

# Pull latest changes from GitHub
echo "📥 Pulling latest code from GitHub..."
git fetch origin
git reset --hard origin/main

# Check version
echo "📋 Current version:"
cat __version__.py | grep __version__

# Install/update dependencies
echo "📦 Installing dependencies..."
pip3.10 install --user -r requirements.txt

# Update WSGI file to ensure it's pointing to the monolithic app
echo "🔧 Updating WSGI configuration..."
cat > /var/www/sahilk1_pythonanywhere_com_wsgi.py << 'EOF'
import sys
import os

# Add your project directory to sys.path
project_home = '/home/sahilk1/TabletTracker'
if project_home not in sys.path:
    sys.path = [project_home] + sys.path

# Set environment variables
os.chdir(project_home)

# Import Flask app
from app import app as application

if __name__ == "__main__":
    application.run()
EOF

echo "✅ Deployment complete!"
echo ""
echo "🔄 IMPORTANT: Now go to your PythonAnywhere Web tab and click 'Reload' for your web app"
echo ""
echo "🎯 New features in v1.15.8:"
echo "  - Unified authentication (admin/admin login)"
echo "  - Fixed navigation for all user roles"
echo "  - Renamed 'Count' to 'End of Month Count'"
echo "  - Enhanced role-based access control"
echo ""
echo "🌐 Your app should now be running v1.15.8 at: https://sahilk1.pythonanywhere.com"

