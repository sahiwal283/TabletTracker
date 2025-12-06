#!/bin/bash
echo "=========================================="
echo "FINAL COMPREHENSIVE DATABASE SEARCH"
echo "=========================================="

echo ""
echo "1. ALL .db files anywhere on system (last 60 days):"
find /home/sahilk1 -name "*.db" -mtime -60 -ls 2>/dev/null

echo ""
echo "2. Files modified in December 2025:"
find /home/sahilk1/TabletTracker -type f -newermt "2025-12-01" -ls 2>/dev/null

echo ""
echo "3. Files modified on Dec 5 specifically:"
find /home/sahilk1/TabletTracker -type f -newermt "2025-12-05" ! -newermt "2025-12-06" -ls 2>/dev/null

echo ""
echo "4. Check /tmp for any database files:"
find /tmp -name "*tablet*" -o -name "*tracker*" -o -name "*.db" 2>/dev/null | head -20

echo ""
echo "5. Hidden files in TabletTracker:"
ls -lah /home/sahilk1/TabletTracker/.*.db 2>/dev/null

echo ""
echo "6. Check app_refactored_backup if it exists:"
ls -lah /home/sahilk1/TabletTracker/app_refactored_backup/ 2>/dev/null

echo ""
echo "=========================================="
