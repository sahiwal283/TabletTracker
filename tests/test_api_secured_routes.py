"""Regression tests for auth on previously open API and page routes."""

import os
import tempfile
import unittest
from unittest.mock import patch

from app import create_app
from config import Config


class TestApiSecuredRoutes(unittest.TestCase):
    def setUp(self):
        self._orig_db = Config.DATABASE_PATH
        fd, self._db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        Config.DATABASE_PATH = self._db_path
        os.environ.setdefault("SKIP_ZOHO_SERVICE_CHECK", "1")
        self.app = create_app()
        self.client = self.app.test_client()

    def tearDown(self):
        Config.DATABASE_PATH = self._orig_db
        if os.path.exists(self._db_path):
            os.remove(self._db_path)

    def test_po_tracking_requires_shipping_session(self):
        r = self.client.get("/api/po_tracking/1")
        self.assertEqual(r.status_code, 401)

    def test_find_org_id_requires_admin(self):
        r = self.client.get("/api/find_org_id")
        self.assertEqual(r.status_code, 403)


class TestTelegramWebhookAuth(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()

    def test_webhook_accepts_header_secret_without_path(self):
        with patch("config.Config.TELEGRAM_BOT_TOKEN", "abc"), patch(
            "config.Config.TELEGRAM_WEBHOOK_SECRET", "supersecret"
        ), patch("config.Config.TELEGRAM_ALLOWED_CHAT_IDS", [111]), patch(
            "config.Config.TELEGRAM_ALLOWED_USER_IDS", []
        ), patch("app.services.telegram_bot_service.telegram_send_message") as send_mock:
            resp = self.client.post(
                "/api/telegram/webhook",
                headers={"X-Telegram-Bot-Api-Secret-Token": "supersecret"},
                json={"message": {"chat": {"id": 111}, "from": {"id": 333}, "text": "/help"}},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(send_mock.called)

    def test_webhook_rejects_wrong_header_when_secret_configured(self):
        with patch("config.Config.TELEGRAM_BOT_TOKEN", "abc"), patch(
            "config.Config.TELEGRAM_WEBHOOK_SECRET", "supersecret"
        ):
            resp = self.client.post(
                "/api/telegram/webhook",
                headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
                json={},
            )
            self.assertEqual(resp.status_code, 403)
