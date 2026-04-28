#!/bin/bash
# Safe deployment script for security fixes
# Run this in PythonAnywhere console

set -e  # Exit on error

echo "🔒 Deploying Security Fixes to PythonAnywhere"
echo "=============================================="

cd ~/TabletTracker

# Step 1: Backup
echo ""
echo "📦 Step 1: Creating backup..."
BACKUP_FILE="database/tablet_counter.db.backup.$(date +%Y%m%d_%H%M%S)"
if [ -f database/tablet_counter.db ]; then
    cp database/tablet_counter.db "$BACKUP_FILE"
    echo "✅ Database backed up to: $BACKUP_FILE"
else
    echo "⚠️  No database file found to backup"
fi

# Step 2: Pull latest code
echo ""
echo "📥 Step 2: Pulling latest code..."
git fetch origin
git pull origin main || {
    echo "❌ Failed to pull code. Check your git credentials."
    exit 1
}
echo "✅ Code updated"

# Step 3: Install critical dependencies
echo ""
echo "📦 Step 3: Installing dependencies..."
echo "Installing Flask-WTF (CSRF protection)..."
pip3.10 install --user Flask-WTF==1.2.1 || {
    echo "❌ Failed to install Flask-WTF"
    exit 1
}

echo "Installing Flask-Limiter (Rate limiting)..."
pip3.10 install --user Flask-Limiter==3.5.0 || {
    echo "❌ Failed to install Flask-Limiter"
    exit 1
}

echo "Installing bleach (HTML sanitization)..."
pip3.10 install --user bleach==6.1.0 || {
    echo "❌ Failed to install bleach"
    exit 1
}

echo "✅ Dependencies installed"

# Step 4: Check environment variables
echo ""
echo "🔐 Step 4: Checking environment variables..."
python3 << 'EOF'
import os
from dotenv import load_dotenv
load_dotenv()

secret_key = os.getenv('SECRET_KEY')
if secret_key:
    print(f"✅ SECRET_KEY is set (length: {len(secret_key)})")
else:
    print("⚠️  WARNING: SECRET_KEY is not set!")
    print("   Add it to your .env file or PythonAnywhere environment")
EOF

# Step 5: Test imports
echo ""
echo "🧪 Step 5: Testing application import..."
python3 << 'EOF'
try:
    from app import create_app
    app = create_app()
    print("✅ Application imports successfully")
except Exception as e:
    print(f"❌ Import failed: {e}")
    import traceback
    traceback.print_exc()
    exit(1)
EOF

# Step 6: Run migrations if needed
echo ""
echo "🗄️  Step 6: Checking database migrations..."
alembic current || echo "⚠️  Alembic check failed (may be OK if already up to date)"
alembic upgrade head || echo "⚠️  Migration failed (check manually)"

echo ""
echo "✅ Deployment preparation complete!"
echo ""
echo "📋 Next steps:"
echo "1. Go to PythonAnywhere Dashboard → Web tab"
echo "2. Click 'Reload' button"
echo "3. Test login and forms"
echo "4. Check browser console for any CSRF errors"
echo ""
echo "🔄 To rollback if needed:"
echo "   git checkout <previous-commit>"
echo "   cp $BACKUP_FILE database/tablet_counter.db"
echo "   Reload web app"









