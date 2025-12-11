#!/bin/bash
# CRITICAL PRODUCTION FIX SCRIPT FOR PYTHONANYWHERE
# Run this script on PythonAnywhere to fix bcrypt and conn errors

set -e

echo "🔧 Starting production deployment fix..."

# Navigate to project directory
cd ~/TabletTracker || cd /home/sahilk1/TabletTracker

echo "📦 Step 1: Installing bcrypt..."
# Try virtual environment first
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
    pip install --upgrade bcrypt==4.1.2
    echo "✅ bcrypt installed in virtual environment"
elif [ -d "venv" ]; then
    source venv/bin/activate
    pip install --upgrade bcrypt==4.1.2
    echo "✅ bcrypt installed in virtual environment"
else
    # Fallback to user installation
    pip3.10 install --user --upgrade bcrypt==4.1.2
    echo "✅ bcrypt installed for user"
fi

echo "🧹 Step 2: Clearing Python cache..."
find . -name "*.pyc" -delete 2>/dev/null || true
find . -name "__pycache__" -type d -exec rm -r {} + 2>/dev/null || true
echo "✅ Cache cleared"

echo "📥 Step 3: Pulling latest code..."
git pull origin refactor/v2.0-modernization || echo "⚠️  Git pull failed - check manually"

echo "✅ Step 4: Verifying code..."
# Check that generate_production_report doesn't have conn in exception handler
if grep -A 15 "def generate_production_report" app/blueprints/api.py | grep -q "if conn:"; then
    echo "❌ ERROR: Found 'if conn:' in generate_production_report exception handler!"
    echo "   This should not be there. The function doesn't use database connections."
    exit 1
else
    echo "✅ Code verification passed - no conn reference in generate_production_report"
fi

# Check that bcrypt is imported
if grep -q "import bcrypt" app/utils/auth_utils.py; then
    echo "✅ bcrypt import found in auth_utils.py"
else
    echo "❌ ERROR: bcrypt import not found!"
    exit 1
fi

echo ""
echo "✅ All checks passed!"
echo ""
echo "📋 Next steps:"
echo "1. Go to PythonAnywhere Dashboard → Web tab"
echo "2. Click 'Reload' button for your web app"
echo "3. Check error logs to verify fixes"
echo ""
echo "🔍 To verify bcrypt is installed:"
echo "   python3.10 -c 'import bcrypt; print(bcrypt.__version__)'"
