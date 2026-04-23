"""Telegram webhook endpoints."""

from __future__ import annotations

from flask import Blueprint, jsonify, request, current_app

from config import Config
from app.services import telegram_bot_service as bot
from app.services import telegram_reporting_service as reports
from app.utils.db_utils import db_read_only

bp = Blueprint("api_telegram", __name__)


@bp.route("/api/telegram/webhook/<token>", methods=["POST"])
def telegram_webhook(token: str):
    if not Config.TELEGRAM_BOT_TOKEN:
        return jsonify({"ok": False, "error": "telegram_not_configured"}), 503
    if token != Config.TELEGRAM_BOT_TOKEN:
        return jsonify({"ok": False, "error": "invalid_token"}), 403

    payload = request.get_json(silent=True) or {}
    message = bot.extract_message(payload)
    if not message:
        return jsonify({"ok": True, "ignored": "no_message"})

    if not bot.is_message_allowed(message):
        return jsonify({"ok": False, "error": "unauthorized_chat_or_user"}), 403

    chat_id = (message.get("chat") or {}).get("id")
    text = message.get("text") or ""
    cmd, args = bot.parse_command(text)
    if not cmd:
        bot.telegram_send_message(chat_id, bot.help_text())
        return jsonify({"ok": True})

    try:
        if cmd in ("/start", "/help"):
            reply = bot.help_text()
        elif cmd == "/daily":
            day_iso, full_day = bot.parse_daily_command_args(args)
            with db_read_only() as conn:
                summary = reports.build_daily_summary(conn, day_iso=day_iso, full_day=full_day)
            reply = bot.format_daily_summary(summary)
        elif cmd == "/status":
            station_kind = (args or "").strip().lower()
            if station_kind not in ("blister", "sealing", "packaging"):
                reply = "Usage: /status blister OR /status sealing OR /status packaging"
            else:
                with db_read_only() as conn:
                    station = reports.get_station_current_bag(conn, station_kind)
                reply = bot.format_station_status(station_kind, station)
        elif cmd == "/counts":
            arg = (args or "").strip().lower()
            if arg != "today":
                reply = "Usage: /counts today"
            else:
                with db_read_only() as conn:
                    counts = reports.count_bags_blistered_today(conn)
                reply = bot.format_counts_today(counts)
        else:
            reply = "Unknown command.\n\n" + bot.help_text()
        bot.telegram_send_message(chat_id, reply)
    except Exception as exc:
        current_app.logger.error("telegram_webhook command failed: %s", exc, exc_info=True)
        return jsonify({"ok": False, "error": "command_failed"}), 500

    return jsonify({"ok": True})
