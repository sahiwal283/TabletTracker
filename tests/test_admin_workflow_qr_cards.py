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
        csrf = _form_csrf(self.client, "/admin/workflow-qr")
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
        self.assertTrue(str(row["scan_token"]).startswith("card-"))
        cid = row["id"]
        conn.close()

        csrf = _form_csrf(self.client, "/admin/workflow-qr")
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
        csrf = _form_csrf(self.client, "/admin/workflow-qr")
        r = self.client.post(
            "/admin/workflow-qr/add-card",
            data={
                "csrf_token": csrf,
                "label": "Custom",
                "scan_token": "my-bag-card-99",
            },
            follow_redirects=True,
        )
        self.assertEqual(r.status_code, 200)
        conn = sqlite3.connect(self._db_path)
        tok = conn.execute(
            "SELECT scan_token FROM qr_cards WHERE label = ?", ("Custom",)
        ).fetchone()[0]
        conn.close()
        self.assertEqual(tok, "my-bag-card-99")

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

        csrf = _form_csrf(self.client, "/admin/workflow-qr")
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


if __name__ == "__main__":
    unittest.main()
