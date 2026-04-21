"""Telegram bot helpers: auth, parsing, formatting, and API calls."""

from __future__ import annotations

from typing import Dict, Optional

import requests
from flask import current_app

from config import Config


def extract_message(update: Dict) -> Optional[Dict]:
    if not isinstance(update, dict):
        return None
    return update.get("message") or update.get("edited_message")


def parse_command(text: str) -> tuple[str, str]:
    raw = (text or "").strip()
    if not raw:
        return "", ""
    parts = raw.split(maxsplit=1)
    cmd = parts[0].lower()
    args = parts[1].strip() if len(parts) > 1 else ""
    if "@" in cmd:
        cmd = cmd.split("@", 1)[0]
    return cmd, args


def is_message_allowed(message: Dict) -> bool:
    chat = message.get("chat") or {}
    frm = message.get("from") or {}
    chat_id = chat.get("id")
    user_id = frm.get("id")

    allowed_chat_ids = set(Config.TELEGRAM_ALLOWED_CHAT_IDS or [])
    allowed_user_ids = set(Config.TELEGRAM_ALLOWED_USER_IDS or [])

    if allowed_chat_ids and chat_id not in allowed_chat_ids:
        return False
    if allowed_user_ids and user_id not in allowed_user_ids:
        return False
    return bool(allowed_chat_ids or allowed_user_ids)


def telegram_send_message(chat_id: int, text: str) -> None:
    token = Config.TELEGRAM_BOT_TOKEN
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    response = requests.post(url, json=payload, timeout=10)
    if response.status_code >= 400:
        current_app.logger.error("telegram_send_message failed: %s %s", response.status_code, response.text)
        response.raise_for_status()


def format_daily_summary(summary: Dict) -> str:
    lines = [
        f"Daily production summary ({summary['day']}, America/New_York)",
        f"Total displays made: {summary['total_displays_made']}",
        f"Total display-equivalent: {summary['total_display_equivalent']}",
        "",
        "By product:",
    ]
    products = summary.get("products") or []
    if not products:
        lines.append("- No production submissions found.")
        return "\n".join(lines)
    for p in products:
        lines.append(
            "- {name}: displays={disp}, display-equivalent={eq}, tablets={tabs}".format(
                name=p["product_name"],
                disp=p["displays_made"],
                eq=p["display_equivalent"],
                tabs=p["tablets_total"],
            )
        )
    return "\n".join(lines)


def format_station_status(station_kind: str, station_row: Optional[Dict]) -> str:
    if not station_row:
        return f"No claimed bag currently found for {station_kind} station."
    return (
        f"{station_kind.title()} station currently has workflow bag "
        f"#{station_row['workflow_bag_id']} (station: {station_row.get('station_label') or station_row.get('station_id')})."
    )


def format_counts_today(counts: Dict) -> str:
    return f"Bags blistered on {counts['day']} (America/New_York): {counts['bags_blistered']}"


def help_text() -> str:
    return (
        "Available commands:\n"
        "/help - show commands\n"
        "/daily [YYYY-MM-DD] - daily production summary\n"
        "/status blister - current blister station bag\n"
        "/status sealing - current sealing station bag\n"
        "/status packaging - current packaging station bag\n"
        "/counts today - number of bags blistered today"
    )
