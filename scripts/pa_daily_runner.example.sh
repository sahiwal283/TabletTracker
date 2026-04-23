#!/usr/bin/env bash
# Example: one PythonAnywhere scheduled task running multiple steps.
# Copy to e.g. ~/TabletTracker/scripts/pa_daily_runner.sh, chmod +x, and point
# "Scheduled tasks" at this file (or paste its body into the PA task).
#
# 1. Replace the placeholder with your real job(s).
# 2. The Telegram line runs with NO --if-due so it sends once when this script runs.
#    Schedule the task in PythonAnywhere at the UTC instant you want (e.g. 6:30 PM Eastern
#    converted to UTC; update when DST changes unless you use a host that runs more often).

set -euo pipefail
cd /home/sahilk1/TabletTracker || exit 1
# shellcheck source=/dev/null
source venv/bin/activate

# --- your existing daily job(s) ---
# python scripts/tracking_job.py

# --- Telegram daily summary (today through "now" in America/New_York) ---
python scripts/telegram_daily_report.py
