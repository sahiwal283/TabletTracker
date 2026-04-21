"""Send Telegram daily summary to configured chats."""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.services import telegram_bot_service as bot
from app.services import telegram_reporting_service as reports
from app.utils.db_utils import db_read_only
from config import Config


def main() -> int:
    parser = argparse.ArgumentParser(description="Send Telegram daily production summary.")
    parser.add_argument("--day", dest="day_iso", default=None, help="Report day in YYYY-MM-DD (America/New_York)")
    args = parser.parse_args()

    if not Config.TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN is not configured")
        return 1
    if not Config.TELEGRAM_ALLOWED_CHAT_IDS:
        print("TELEGRAM_ALLOWED_CHAT_IDS is empty")
        return 1

    with db_read_only() as conn:
        summary = reports.build_daily_summary(conn, day_iso=args.day_iso)
    text = bot.format_daily_summary(summary)

    for chat_id in Config.TELEGRAM_ALLOWED_CHAT_IDS:
        bot.telegram_send_message(chat_id, text)
        print(f"Sent daily report to chat {chat_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
