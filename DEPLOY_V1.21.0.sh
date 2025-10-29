#!/bin/bash

# TabletTracker Production Deployment Script v1.21.0
# Run this on PythonAnywhere to deploy the latest version
# 
# Usage:
#   chmod +x DEPLOY_V1.21.0.sh
#   ./DEPLOY_V1.21.0.sh

echo "============================================================"
echo "TabletTracker Production Deployment - v1.21.0"
echo "============================================================"
echo ""

# Step 1: Pull latest code from GitHub
echo "Step 1: Pulling latest code from GitHub..."
git pull origin main

if [ $? -ne 0 ]; then
    echo "❌ Git pull failed! Please resolve conflicts and try again."
    exit 1
fi

echo "✓ Code updated successfully"
echo ""

# Step 2: Run database migrations
echo "Step 2: Running database migrations..."
python3 migrate_to_v1.21.0.py

if [ $? -ne 0 ]; then
    echo "❌ Migration failed! Please check the errors above."
    exit 1
fi

echo "✓ Database migrated successfully"
echo ""

# Step 3: Reload web app
echo "Step 3: Instructions for reloading the web app..."
echo ""
echo "On PythonAnywhere:"
echo "1. Go to the 'Web' tab"
echo "2. Click the 'Reload' button for sahilk1.pythonanywhere.com"
echo "3. Wait for the green 'Configuration' text to appear"
echo "4. Visit https://sahilk1.pythonanywhere.com/dashboard"
echo "5. Verify you see v1.21.0 in the footer"
echo ""

echo "============================================================"
echo "✅ Deployment preparation complete!"
echo "============================================================"
echo ""
echo "What's new in v1.21.0:"
echo "  • Sequential PO filling (older POs fill first)"
echo "  • Clickable PO line items to view submissions"
echo "  • PO status indicators (Open/Closed) in Recent Submissions"
echo "  • Filter toggle to show/hide closed PO submissions"
echo "  • Exclude Draft POs from receiving submissions"
echo "  • Enhanced database compatibility"
echo ""

