"""Send Telegram daily summary to configured chats."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.services import telegram_bot_service as bot
from app.services import telegram_reporting_service as reports
from app.utils.db_utils import db_read_only
from config import Config

_NY = ZoneInfo("America/New_York")


def _schedule_matches_now(now_ny: datetime, hhmm: str) -> bool:
    parts = (hhmm or "").strip().split(":")
    if len(parts) != 2:
        return False
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return now_ny.hour == h and now_ny.minute == m


def main() -> int:
    parser = argparse.ArgumentParser(description="Send Telegram daily production summary.")
    parser.add_argument(
        "--day",
        dest="day_iso",
        default=None,
        help="Report day in YYYY-MM-DD (America/New_York). Default: today.",
    )
    parser.add_argument(
        "--full-day",
        action="store_true",
        help="Use full calendar day for today (default is through-now for today).",
    )
    parser.add_argument(
        "--if-due",
        action="store_true",
        help=(
            "Only send when current America/New_York clock time matches "
            "TELEGRAM_DAILY_REPORT_TIME (HH:MM). Requires a scheduler that runs "
            "often (e.g. every minute). Not usable alone on a single daily "
            "PythonAnywhere task — chain a no-flag run instead (see docs/DEPLOYMENT.md)."
        ),
    )
    args = parser.parse_args()

    if not Config.TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN is not configured")
        return 1
    if not Config.TELEGRAM_ALLOWED_CHAT_IDS:
        print("TELEGRAM_ALLOWED_CHAT_IDS is empty")
        return 1

    if args.if_due:
        now_ny = datetime.now(_NY)
        if not _schedule_matches_now(now_ny, Config.TELEGRAM_DAILY_REPORT_TIME):
            print(
                "Not scheduled time (America/New_York); "
                f"now={now_ny.strftime('%H:%M')} want={Config.TELEGRAM_DAILY_REPORT_TIME}. Skipping."
            )
            return 0

    with db_read_only() as conn:
        summary = reports.build_daily_summary(
            conn, day_iso=args.day_iso, full_day=args.full_day
        )
    text = bot.format_daily_summary(summary)

    for chat_id in Config.TELEGRAM_ALLOWED_CHAT_IDS:
        bot.telegram_send_message(chat_id, text)
        print(f"Sent daily report to chat {chat_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
