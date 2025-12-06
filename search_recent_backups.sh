#!/bin/bash
echo "========================================"
echo "Searching for backups from November-December 2025"
echo "========================================"

echo ""
echo "1. All files modified after Oct 30:"
find /home/sahilk1/TabletTracker -type f -name "*.db*" -newermt "2025-10-30" -ls 2>/dev/null

echo ""
echo "2. All backup directories:"
find /home/sahilk1/TabletTracker -type d -name "*backup*" -o -name "*bak*" 2>/dev/null

echo ""
echo "3. Checking for .db files in common backup locations:"
ls -lah /home/sahilk1/TabletTracker/backups/ 2>/dev/null
ls -lah /home/sahilk1/TabletTracker/.backup/ 2>/dev/null
ls -lah /home/sahilk1/.backup/ 2>/dev/null

echo ""
echo "4. Files with tablet/tracker modified in last 2 months:"
find /home/sahilk1 -maxdepth 3 -type f \( -name "*tablet*" -o -name "*tracker*" \) -mtime -60 -ls 2>/dev/null | grep -i "\.db"

echo ""
echo "========================================"
