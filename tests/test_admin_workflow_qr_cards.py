"""Admin workflow QR: add/remove bag qr_cards."""
import os
import re
import sqlite3
import tempfile
import unittest

from app import create_app
from app.models import database as database_module
from app.models.migrations import MigrationRunner
from config import Config

CARD_TOOLS_PATH = "/admin/workflow-qr?tools=cards"
STATION_TOOLS_PATH = "/admin/workflow-qr?tools=stations"


def _admin_client(app):
    c = app.test_client()
    with c.session_transaction() as s:
        s["admin_authenticated"] = True
    return c


def _form_csrf(client, path):
    r = client.get(path)
    assert r.status_code == 200
    m = re.search(r'name="csrf_token" value="([^"]+)"', r.get_data(as_text=True))
    assert m, "csrf_token not found in page"
    return m.group(1)


class TestAdminWorkflowQrCards(unittest.TestCase):
    def setUp(self):
        self._orig_db = Config.DATABASE_PATH
        fd, self._db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        Config.DATABASE_PATH = self._db_path
        database_module._migrations_run = False
        os.environ.setdefault("SKIP_ZOHO_SERVICE_CHECK", "1")
        conn = sqlite3.connect(self._db_path)
        MigrationRunner(conn.cursor()).run_all()
        conn.commit()
        conn.close()
        self.app = create_app()
        self.client = _admin_client(self.app)

    def tearDown(self):
        Config.DATABASE_PATH = self._orig_db
        database_module._migrations_run = False
        if os.path.exists(self._db_path):
            os.remove(self._db_path)

    def test_add_card_auto_token_and_remove(self):
        csrf = _form_csrf(self.client, CARD_TOOLS_PATH)
        r = self.client.post(
            "/admin/workflow-qr/add-card",
            data={"csrf_token": csrf, "label": "Admin test card", "scan_token": ""},
            follow_redirects=True,
        )
        self.assertEqual(r.status_code, 200)

        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, scan_token FROM qr_cards WHERE label = ?",
            ("Admin test card",),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertTrue(str(row["scan_token"]).startswith("bag-"))
        cid = row["id"]
        conn.close()

        csrf = _form_csrf(self.client, CARD_TOOLS_PATH)
        r2 = self.client.post(
            "/admin/workflow-qr/remove-card",
            data={"csrf_token": csrf, "qr_card_id": cid},
            follow_redirects=True,
        )
        self.assertEqual(r2.status_code, 200)
        conn = sqlite3.connect(self._db_path)
        n = conn.execute("SELECT COUNT(*) FROM qr_cards WHERE id = ?", (cid,)).fetchone()[0]
        conn.close()
        self.assertEqual(n, 0)

    def test_add_card_custom_token(self):
        csrf = _form_csrf(self.client, CARD_TOOLS_PATH)
        r = self.client.post(
            "/admin/workflow-qr/add-card",
            data={
                "csrf_token": csrf,
                "label": "Custom",
                "scan_token": "bag-custom-test-99",
            },
            follow_redirects=True,
        )
        self.assertEqual(r.status_code, 200)
        conn = sqlite3.connect(self._db_path)
        tok = conn.execute(
            "SELECT scan_token FROM qr_cards WHERE label = ?", ("Custom",)
        ).fetchone()[0]
        conn.close()
        self.assertEqual(tok, "bag-custom-test-99")

    def test_add_card_manual_token_without_bag_prefix(self):
        csrf = _form_csrf(self.client, CARD_TOOLS_PATH)
        r = self.client.post(
            "/admin/workflow-qr/add-card",
            data={
                "csrf_token": csrf,
                "label": "Manual token",
                "scan_token": "test-card-1",
            },
            follow_redirects=True,
        )
        self.assertEqual(r.status_code, 200)
        conn = sqlite3.connect(self._db_path)
        tok = conn.execute(
            "SELECT scan_token FROM qr_cards WHERE label = ?", ("Manual token",)
        ).fetchone()[0]
        conn.close()
        self.assertEqual(tok, "test-card-1")

    def test_add_card_normalizes_unicode_hyphen_in_token(self):
        csrf = _form_csrf(self.client, CARD_TOOLS_PATH)
        r = self.client.post(
            "/admin/workflow-qr/add-card",
            data={
                "csrf_token": csrf,
                "label": "Unicode dash",
                # U+2011 non-breaking hyphen (common from word processors)
                "scan_token": "test\u2011card\u2011uni",
            },
            follow_redirects=True,
        )
        self.assertEqual(r.status_code, 200)
        conn = sqlite3.connect(self._db_path)
        tok = conn.execute(
            "SELECT scan_token FROM qr_cards WHERE label = ?", ("Unicode dash",)
        ).fetchone()[0]
        conn.close()
        self.assertEqual(tok, "test-card-uni")

    def test_add_card_invalid_scan_token_shows_error_and_skips_insert(self):
        csrf = _form_csrf(self.client, CARD_TOOLS_PATH)
        r = self.client.post(
            "/admin/workflow-qr/add-card",
            data={
                "csrf_token": csrf,
                "label": "Should not exist",
                "scan_token": "bad token spaces",
            },
            follow_redirects=True,
        )
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn("Scan token is not valid", html)
        conn = sqlite3.connect(self._db_path)
        n = conn.execute(
            "SELECT COUNT(*) FROM qr_cards WHERE label = ?", ("Should not exist",)
        ).fetchone()[0]
        conn.close()
        self.assertEqual(n, 0)

    def test_remove_rejects_assigned_card(self):
        conn = sqlite3.connect(self._db_path)
        cur = conn.execute(
            "INSERT INTO workflow_bags (created_at, box_number, bag_number) VALUES (?,?,?)",
            (0, "1", "1"),
        )
        bag_id = cur.lastrowid
        conn.execute(
            """
            INSERT INTO qr_cards (label, scan_token, status, assigned_workflow_bag_id)
            VALUES ('Busy', 'busy-token-x', 'assigned', ?)
            """,
            (bag_id,),
        )
        cid = conn.execute("SELECT id FROM qr_cards WHERE scan_token = 'busy-token-x'").fetchone()[0]
        conn.commit()
        conn.close()

        csrf = _form_csrf(self.client, CARD_TOOLS_PATH)
        r = self.client.post(
            "/admin/workflow-qr/remove-card",
            data={"csrf_token": csrf, "qr_card_id": cid},
            follow_redirects=True,
        )
        self.assertEqual(r.status_code, 200)
        conn = sqlite3.connect(self._db_path)
        n = conn.execute("SELECT COUNT(*) FROM qr_cards WHERE id = ?", (cid,)).fetchone()[0]
        conn.close()
        self.assertEqual(n, 1)

    def test_edit_station_scan_token(self):
        conn = sqlite3.connect(self._db_path)
        sid = conn.execute("SELECT id FROM workflow_stations LIMIT 1").fetchone()[0]
        conn.close()
        csrf = _form_csrf(self.client, STATION_TOOLS_PATH)
        r = self.client.post(
            "/admin/workflow-qr/edit-station-token",
            data={
                "csrf_token": csrf,
                "station_id": sid,
                "station_scan_token": "seal-renamed-integration-test",
            },
            follow_redirects=True,
        )
        self.assertEqual(r.status_code, 200)
        conn = sqlite3.connect(self._db_path)
        tok = conn.execute(
            "SELECT station_scan_token FROM workflow_stations WHERE id = ?", (sid,)
        ).fetchone()[0]
        conn.close()
        self.assertEqual(tok, "seal-renamed-integration-test")

    def test_workflow_qr_page_shows_bag_name_column(self):
        r = self.client.get(CARD_TOOLS_PATH)
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn("Bag name", html)


if __name__ == "__main__":
    unittest.main()
