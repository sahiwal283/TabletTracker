#!/bin/bash
#
# Quick Restore Script
# Quickly restore database from most recent backup
#

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Python executable (use virtual environment if available)
if [ -f "$PROJECT_DIR/venv/bin/python" ]; then
    PYTHON="$PROJECT_DIR/venv/bin/python3"
else
    PYTHON="python3"
fi

RESTORE_MANAGER="$PROJECT_DIR/database/restore_manager.py"

echo "=" | tr '=' '=' | head -c 70 | tr '\n' '='
echo
echo "QUICK DATABASE RESTORE"
echo "=" | tr '=' '=' | head -c 70 | tr '\n' '='
echo
echo

# Check if restore manager exists
if [ ! -f "$RESTORE_MANAGER" ]; then
    echo "❌ Restore manager not found: $RESTORE_MANAGER"
    exit 1
fi

# Run interactive restore
cd "$PROJECT_DIR"
$PYTHON "$RESTORE_MANAGER" --interactive

exit $?

