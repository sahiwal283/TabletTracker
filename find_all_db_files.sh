#!/bin/bash
echo "=========================================="
echo "Searching for ALL .db files on PythonAnywhere"
echo "=========================================="
echo ""

echo "1. Checking TabletTracker directory and subdirectories:"
find /home/sahilk1/TabletTracker -name "*.db" -ls 2>/dev/null

echo ""
echo "2. Checking home directory for any .db files:"
find /home/sahilk1 -maxdepth 3 -name "*.db" -ls 2>/dev/null

echo ""
echo "3. Checking for any files with 'tablet' or 'tracker' in name:"
find /home/sahilk1 -maxdepth 3 -name "*tablet*" -o -name "*tracker*" 2>/dev/null | grep -i "\.db"

echo ""
echo "4. Checking tmp directory:"
find /tmp -name "*tablet*.db" -o -name "*tracker*.db" 2>/dev/null

echo ""
echo "=========================================="

