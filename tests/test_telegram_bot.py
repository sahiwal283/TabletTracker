"""Telegram bot webhook and reporting service tests."""

import os
import sqlite3
import tempfile
import unittest
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app import create_app
from app.services import telegram_reporting_service as trs

_NY = ZoneInfo("America/New_York")


class TestTelegramBot(unittest.TestCase):
    def setUp(self):
        self.db_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_tmp.close()
        os.environ["DATABASE_PATH"] = self.db_tmp.name
        self.app = create_app()
        self.client = self.app.test_client()

        with self.app.app_context():
            conn = sqlite3.connect(self.db_tmp.name)
            conn.row_factory = sqlite3.Row
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS workflow_stations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    station_scan_token TEXT NOT NULL UNIQUE,
                    station_kind TEXT,
                    label TEXT
                );
                CREATE TABLE IF NOT EXISTS workflow_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    occurred_at INTEGER NOT NULL,
                    workflow_bag_id INTEGER NOT NULL,
                    station_id INTEGER,
                    user_id INTEGER,
                    device_id TEXT
                );
                """
            )
            conn.commit()
            conn.close()

    def tearDown(self):
        try:
            os.unlink(self.db_tmp.name)
        except OSError:
            pass

    def test_webhook_rejects_non_whitelisted_chat(self):
        with patch("config.Config.TELEGRAM_BOT_TOKEN", "abc"), patch(
            "config.Config.TELEGRAM_ALLOWED_CHAT_IDS", [111]
        ), patch("config.Config.TELEGRAM_ALLOWED_USER_IDS", []):
            resp = self.client.post(
                "/api/telegram/webhook/abc",
                json={"message": {"chat": {"id": 222}, "from": {"id": 333}, "text": "/help"}},
            )
            self.assertEqual(resp.status_code, 403)

    def test_webhook_help_command(self):
        with patch("config.Config.TELEGRAM_BOT_TOKEN", "abc"), patch(
            "config.Config.TELEGRAM_ALLOWED_CHAT_IDS", [111]
        ), patch("config.Config.TELEGRAM_ALLOWED_USER_IDS", []), patch(
            "app.services.telegram_bot_service.telegram_send_message"
        ) as send_mock:
            resp = self.client.post(
                "/api/telegram/webhook/abc",
                json={"message": {"chat": {"id": 111}, "from": {"id": 333}, "text": "/help"}},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(send_mock.called)

    def test_webhook_counts_today_command(self):
        with patch("config.Config.TELEGRAM_BOT_TOKEN", "abc"), patch(
            "config.Config.TELEGRAM_ALLOWED_CHAT_IDS", [111]
        ), patch("config.Config.TELEGRAM_ALLOWED_USER_IDS", []), patch(
            "app.services.telegram_reporting_service.count_bags_blistered_today",
            return_value={"day": "2026-04-21", "bags_blistered": 4},
        ), patch(
            "app.services.telegram_bot_service.telegram_send_message"
        ) as send_mock:
            resp = self.client.post(
                "/api/telegram/webhook/abc",
                json={"message": {"chat": {"id": 111}, "from": {"id": 333}, "text": "/counts today"}},
            )
            self.assertEqual(resp.status_code, 200)
            send_mock.assert_called_once()
            self.assertIn("Bags blistered on 2026-04-21", send_mock.call_args.args[1])

    def test_webhook_status_command(self):
        with patch("config.Config.TELEGRAM_BOT_TOKEN", "abc"), patch(
            "config.Config.TELEGRAM_ALLOWED_CHAT_IDS", [111]
        ), patch("config.Config.TELEGRAM_ALLOWED_USER_IDS", []), patch(
            "app.services.telegram_reporting_service.get_station_current_bag",
            return_value={"workflow_bag_id": 123, "station_label": "BL-1", "station_id": 7},
        ), patch(
            "app.services.telegram_bot_service.telegram_send_message"
        ) as send_mock:
            resp = self.client.post(
                "/api/telegram/webhook/abc",
                json={"message": {"chat": {"id": 111}, "from": {"id": 333}, "text": "/status blister"}},
            )
            self.assertEqual(resp.status_code, 200)
            send_mock.assert_called_once()
            self.assertIn("#123", send_mock.call_args.args[1])

    def test_webhook_status_sealing_command(self):
        with patch("config.Config.TELEGRAM_BOT_TOKEN", "abc"), patch(
            "config.Config.TELEGRAM_ALLOWED_CHAT_IDS", [111]
        ), patch("config.Config.TELEGRAM_ALLOWED_USER_IDS", []), patch(
            "app.services.telegram_reporting_service.get_station_current_bag",
            return_value={"workflow_bag_id": 456, "station_label": "SL-1", "station_id": 8},
        ), patch(
            "app.services.telegram_bot_service.telegram_send_message"
        ) as send_mock:
            resp = self.client.post(
                "/api/telegram/webhook/abc",
                json={"message": {"chat": {"id": 111}, "from": {"id": 333}, "text": "/status sealing"}},
            )
            self.assertEqual(resp.status_code, 200)
            send_mock.assert_called_once()
            self.assertIn("#456", send_mock.call_args.args[1])

    def test_count_bags_blistered_today_uses_ny_window(self):
        conn = sqlite3.connect(self.db_tmp.name)
        conn.row_factory = sqlite3.Row
        conn.execute(
            "INSERT INTO workflow_stations (station_scan_token, station_kind, label) VALUES ('s1', 'blister', 'B1')"
        )
        station_id = conn.execute("SELECT id FROM workflow_stations LIMIT 1").fetchone()["id"]

        in_day = int(datetime(2026, 4, 21, 10, 0, tzinfo=_NY).timestamp() * 1000)
        prev_day = int(datetime(2026, 4, 20, 23, 30, tzinfo=_NY).timestamp() * 1000)
        conn.execute(
            "INSERT INTO workflow_events (event_type, payload, occurred_at, workflow_bag_id, station_id) VALUES (?, '{}', ?, 1, ?)",
            ("BLISTER_COMPLETE", in_day, station_id),
        )
        conn.execute(
            "INSERT INTO workflow_events (event_type, payload, occurred_at, workflow_bag_id, station_id) VALUES (?, '{}', ?, 2, ?)",
            ("BLISTER_COMPLETE", prev_day, station_id),
        )
        conn.commit()

        counts = trs.count_bags_blistered_today(conn, day_iso="2026-04-21")
        self.assertEqual(counts["bags_blistered"], 1)
        conn.close()

    def test_submission_day_match_uses_created_at_ny_fallback(self):
        sub = {
            "submission_date": None,
            "created_at": "2026-04-22 02:30:00",  # 2026-04-21 22:30 in New York
            "filter_date": "2026-04-22",
        }
        self.assertTrue(trs._is_submission_on_target_day(sub, date(2026, 4, 21)))


if __name__ == "__main__":
    unittest.main()
