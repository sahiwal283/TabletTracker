"""
Integration tests: shared receipt across two sealing machines, by-receipt API, duplicate rules.

Uses a temp copy of the project SQLite DB with patched Config.DATABASE_PATH.
"""
import os
import shutil
import sqlite3
import tempfile
import unittest

from app import create_app
from app.models import database as database_module
from config import Config


def _csrf_post(client, path, json_body):
    tr = client.get("/api/csrf-token")
    token = tr.get_json()["csrf_token"]
    return client.post(
        path,
        json=json_body,
        headers={"X-CSRFToken": token, "Content-Type": "application/json"},
    )


def _admin_client(app):
    c = app.test_client()
    with c.session_transaction() as s:
        s["admin_authenticated"] = True
    return c


class TestSharedReceipt(unittest.TestCase):
    """Two machine rows per receipt (distinct machine_id); by-receipt lookup."""

    def setUp(self):
        self._orig_db = Config.DATABASE_PATH
        fd, self._db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        shutil.copy(self._orig_db, self._db_path)
        Config.DATABASE_PATH = self._db_path
        database_module._migrations_run = False

        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS machines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                machine_name TEXT UNIQUE NOT NULL,
                cards_per_turn INTEGER NOT NULL DEFAULT 1,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur = conn.execute("SELECT COUNT(*) AS c FROM machines")
        if cur.fetchone()["c"] == 0:
            conn.execute(
                """
                INSERT INTO machines (id, machine_name, cards_per_turn, is_active)
                VALUES (1, 'Test Sealer A', 1, 1), (2, 'Test Sealer B', 1, 1)
                """
            )
        conn.execute(
            "UPDATE tablet_types SET inventory_item_id = ? WHERE id = 1", ("zoho-inv-tt1",)
        )
        conn.execute(
            "UPDATE tablet_types SET inventory_item_id = ? WHERE id = 2", ("zoho-inv-tt2",)
        )
        conn.commit()
        conn.close()

        from app.models.migrations import MigrationRunner

        conn = sqlite3.connect(self._db_path)
        MigrationRunner(conn.cursor()).run_all()
        conn.commit()
        conn.close()

        os.environ.setdefault("SKIP_ZOHO_SERVICE_CHECK", "1")
        self.app = create_app()
        self.client = _admin_client(self.app)

    def tearDown(self):
        Config.DATABASE_PATH = self._orig_db
        database_module._migrations_run = False
        if os.path.exists(self._db_path):
            os.remove(self._db_path)

    def test_two_machine_posts_same_receipt_different_machines(self):
        receipt = "TEST-SR-DUAL-001"
        r1 = _csrf_post(
            self.client,
            "/api/submissions/machine-count",
            {
                "product_id": 1,
                "machine_count": 1,
                "count_date": "2026-03-30",
                "receipt_number": receipt,
                "machine_id": 1,
            },
        )
        self.assertEqual(r1.status_code, 200, r1.get_json())
        self.assertTrue(r1.get_json().get("success"))

        r2 = _csrf_post(
            self.client,
            "/api/submissions/machine-count",
            {
                "product_id": 1,
                "machine_count": 2,
                "count_date": "2026-03-30",
                "receipt_number": receipt,
                "machine_id": 2,
            },
        )
        self.assertEqual(r2.status_code, 200, r2.get_json())
        self.assertTrue(r2.get_json().get("success"))

    def test_machine_entries_batch_single_post_two_machines(self):
        """One POST with machine_entries creates two submission rows (same receipt)."""
        receipt = "TEST-SR-BATCH-001"
        r = _csrf_post(
            self.client,
            "/api/submissions/machine-count",
            {
                "product_id": 1,
                "count_date": "2026-03-30",
                "receipt_number": receipt,
                "machine_entries": [
                    {"machine_id": 1, "machine_count": 1},
                    {"machine_id": 2, "machine_count": 2},
                ],
            },
        )
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertTrue(r.get_json().get("success"))
        gr = self.client.get(f"/api/machine-count/by-receipt?receipt={receipt}")
        data = gr.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("machine_count_total"), 2)
        self.assertEqual(len(data.get("machine_counts") or []), 2)

    def test_machine_entries_duplicate_machine_in_payload_rejected(self):
        receipt = "TEST-SR-BATCH-DUP-001"
        r = _csrf_post(
            self.client,
            "/api/submissions/machine-count",
            {
                "product_id": 1,
                "count_date": "2026-03-30",
                "receipt_number": receipt,
                "machine_entries": [
                    {"machine_id": 1, "machine_count": 1},
                    {"machine_id": 1, "machine_count": 2},
                ],
            },
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("error", r.get_json())

    def test_duplicate_same_machine_same_receipt_rejected(self):
        receipt = "TEST-SR-DUP-001"
        body = {
            "product_id": 1,
            "machine_count": 1,
            "count_date": "2026-03-30",
            "receipt_number": receipt,
            "machine_id": 1,
        }
        r1 = _csrf_post(self.client, "/api/submissions/machine-count", body)
        self.assertEqual(r1.status_code, 200, r1.get_json())
        r2 = _csrf_post(self.client, "/api/submissions/machine-count", body)
        self.assertEqual(r2.status_code, 400)
        self.assertIn("error", r2.get_json())

    def test_by_receipt_returns_two_rows(self):
        receipt = "TEST-SR-BYREC-001"
        _csrf_post(
            self.client,
            "/api/submissions/machine-count",
            {
                "product_id": 1,
                "machine_count": 1,
                "count_date": "2026-03-30",
                "receipt_number": receipt,
                "machine_id": 1,
            },
        )
        _csrf_post(
            self.client,
            "/api/submissions/machine-count",
            {
                "product_id": 1,
                "machine_count": 1,
                "count_date": "2026-03-30",
                "receipt_number": receipt,
                "machine_id": 2,
            },
        )
        gr = self.client.get(f"/api/machine-count/by-receipt?receipt={receipt}")
        self.assertEqual(gr.status_code, 200)
        data = gr.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("machine_count_total"), 2)
        self.assertEqual(len(data.get("machine_counts") or []), 2)
        self.assertIn("machine_count", data)

    def test_by_receipt_inconsistent_product(self):
        receipt = "TEST-SR-BAD-001"
        r1 = _csrf_post(
            self.client,
            "/api/submissions/machine-count",
            {
                "product_id": 1,
                "machine_count": 1,
                "count_date": "2026-03-30",
                "receipt_number": receipt,
                "machine_id": 1,
            },
        )
        self.assertEqual(r1.status_code, 200, r1.get_json())
        r2 = _csrf_post(
            self.client,
            "/api/submissions/machine-count",
            {
                "product_id": 4,
                "machine_count": 1,
                "count_date": "2026-03-30",
                "receipt_number": receipt,
                "machine_id": 2,
            },
        )
        self.assertEqual(r2.status_code, 400, r2.get_json())
        err = (r2.get_json() or {}).get("error", "")
        self.assertIn("Receipt chain", err)
        self.assertIn("same finished product", err)


if __name__ == "__main__":
    unittest.main()
