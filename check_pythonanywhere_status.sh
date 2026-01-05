#!/bin/bash
# Script to check PythonAnywhere status without pulling
# Run this in PythonAnywhere console

echo "🔍 Checking PythonAnywhere Status"
echo "=================================="
echo ""

cd ~/TabletTracker

echo "📋 Current Branch:"
git branch --show-current
echo ""

echo "📝 Current Commit (PythonAnywhere):"
git log -1 --oneline
echo ""

echo "🌐 Latest Commit on GitHub (origin/main):"
git fetch origin --quiet
git log -1 --oneline origin/main
echo ""

echo "📊 Comparison:"
LOCAL_COMMIT=$(git rev-parse HEAD)
REMOTE_COMMIT=$(git rev-parse origin/main)

if [ "$LOCAL_COMMIT" = "$REMOTE_COMMIT" ]; then
    echo "✅ PythonAnywhere is UP TO DATE with GitHub"
else
    echo "⚠️  PythonAnywhere is BEHIND GitHub"
    echo ""
    echo "Commits on GitHub but not on PythonAnywhere:"
    git log --oneline HEAD..origin/main | head -10
fi

echo ""
echo "📦 Uncommitted Changes:"
if [ -n "$(git status --porcelain)" ]; then
    echo "⚠️  You have uncommitted changes:"
    git status --short | head -10
else
    echo "✅ No uncommitted changes"
fi

