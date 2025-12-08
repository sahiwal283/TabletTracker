#!/bin/bash
#
# Automated Backup Scheduler
# Sets up cron jobs for automatic database backups
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

# Backup script paths
BACKUP_MANAGER="$PROJECT_DIR/database/backup_manager.py"
HEALTH_CHECK="$PROJECT_DIR/database/health_check.py"

# Make scripts executable
chmod +x "$BACKUP_MANAGER"
chmod +x "$HEALTH_CHECK"

# Function to add cron job
add_cron_job() {
    local schedule="$1"
    local command="$2"
    local description="$3"
    
    # Check if job already exists
    if crontab -l 2>/dev/null | grep -q "$command"; then
        echo "  ℹ  $description - already scheduled"
        return
    fi
    
    # Add job to crontab
    (crontab -l 2>/dev/null; echo "$schedule cd $PROJECT_DIR && $command >> $PROJECT_DIR/backups/backup.log 2>&1") | crontab -
    echo "  ✓ $description - scheduled"
}

echo "=" | tr '=' '=' | head -c 70 | tr '\n' '='
echo
echo "AUTOMATED BACKUP SCHEDULER"
echo "=" | tr '=' '=' | head -c 70 | tr '\n' '='
echo
echo

echo "Setting up automated backup schedule..."
echo

# Hourly backups (every hour)
add_cron_job "0 * * * *" "$PYTHON $BACKUP_MANAGER --hourly" "Hourly backups (every hour)"

# Daily backups (at 2:00 AM)
add_cron_job "0 2 * * *" "$PYTHON $BACKUP_MANAGER --daily" "Daily backups (2:00 AM)"

# Weekly backups (Sunday at 3:00 AM)
add_cron_job "0 3 * * 0" "$PYTHON $BACKUP_MANAGER --weekly" "Weekly backups (Sunday 3:00 AM)"

# Monthly backups (1st of month at 4:00 AM)
add_cron_job "0 4 1 * *" "$PYTHON $BACKUP_MANAGER --monthly" "Monthly backups (1st of month)"

# Yearly backups (January 1st at 5:00 AM)
add_cron_job "0 5 1 1 *" "$PYTHON $BACKUP_MANAGER --yearly" "Yearly backups (January 1st)"

# Health check (every 6 hours)
add_cron_job "0 */6 * * *" "$PYTHON $HEALTH_CHECK" "Health checks (every 6 hours)"

echo
echo "=" | tr '=' '=' | head -c 70 | tr '\n' '='
echo
echo "✅ BACKUP SCHEDULE CONFIGURED"
echo "=" | tr '=' '=' | head -c 70 | tr '\n' '='
echo
echo "Backup Schedule:"
echo "  • Hourly:  Every hour on the hour"
echo "  • Daily:   Every day at 2:00 AM"
echo "  • Weekly:  Every Sunday at 3:00 AM"
echo "  • Monthly: 1st of every month at 4:00 AM"
echo "  • Yearly:  January 1st at 5:00 AM"
echo "  • Health:  Every 6 hours"
echo
echo "Backup Location: $PROJECT_DIR/backups/"
echo "Log File: $PROJECT_DIR/backups/backup.log"
echo
echo "To view current cron jobs:"
echo "  crontab -l"
echo
echo "To manually run a backup:"
echo "  $PYTHON $BACKUP_MANAGER --daily"
echo
echo "To check backup status:"
echo "  $PYTHON $BACKUP_MANAGER --status"
echo
echo "To view available backups:"
echo "  $PYTHON $BACKUP_MANAGER --list"
echo
echo "=" | tr '=' '=' | head -c 70 | tr '\n' '='
echo

