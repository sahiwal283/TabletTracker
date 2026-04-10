"""
Integration test: POST /api/submissions/production-combined creates machine + packaged rows in one transaction.
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


class TestProductionCombined(unittest.TestCase):
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
                VALUES (1, 'Test Sealer A', 1, 1)
                """
            )
        conn.execute(
            "UPDATE tablet_types SET inventory_item_id = ? WHERE id = 1", ("zoho-inv-tt1",)
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

    def test_combined_creates_machine_and_packaged_rows(self):
        receipt = "TEST-COMBINED-FULL-001"
        body = {
            "product_id": 1,
            "count_date": "2026-03-30",
            "receipt_number": receipt,
            "machine_entries": [{"machine_id": 1, "machine_count": 2}],
            "displays_made": 1,
            "packs_remaining": 0,
            "damaged_tablets": 0,
            "employee_name": "Test Admin",
        }
        r = _csrf_post(self.client, "/api/submissions/production-combined", body)
        self.assertEqual(r.status_code, 200, r.get_json())
        j = r.get_json()
        self.assertTrue(j.get("success"))
        self.assertIn("machine", j)
        self.assertIn("packaged", j)

        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        m = conn.execute(
            """
            SELECT COUNT(*) AS c FROM warehouse_submissions
            WHERE receipt_number = ? AND submission_type = 'machine'
            """,
            (receipt,),
        ).fetchone()["c"]
        p = conn.execute(
            """
            SELECT COUNT(*) AS c FROM warehouse_submissions
            WHERE receipt_number = ? AND submission_type = 'packaged'
            """,
            (receipt,),
        ).fetchone()["c"]
        conn.close()
        self.assertGreaterEqual(m, 1)
        self.assertEqual(p, 1)

    def test_second_combined_same_receipt_fails_packaged_duplicate(self):
        receipt = "TEST-COMBINED-DUP-001"
        body = {
            "product_id": 1,
            "count_date": "2026-03-30",
            "receipt_number": receipt,
            "machine_entries": [{"machine_id": 1, "machine_count": 1}],
            "displays_made": 0,
            "packs_remaining": 0,
            "damaged_tablets": 0,
            "employee_name": "Test Admin",
        }
        r1 = _csrf_post(self.client, "/api/submissions/production-combined", body)
        self.assertEqual(r1.status_code, 200, r1.get_json())

        r2 = _csrf_post(self.client, "/api/submissions/production-combined", body)
        self.assertEqual(r2.status_code, 400)
        self.assertIn("error", r2.get_json())

    def test_combined_rejects_bag_end_before_start(self):
        receipt = "TEST-COMBINED-BAD-TIME-001"
        body = {
            "product_id": 1,
            "count_date": "2026-03-30",
            "receipt_number": receipt,
            "machine_entries": [{"machine_id": 1, "machine_count": 1}],
            "displays_made": 0,
            "packs_remaining": 0,
            "damaged_tablets": 0,
            "employee_name": "Test Admin",
            "bag_start_time": "2026-03-30T16:00",
            "bag_end_time": "2026-03-30T10:00",
        }
        r = _csrf_post(self.client, "/api/submissions/production-combined", body)
        self.assertEqual(r.status_code, 400, r.get_json())
        err = (r.get_json() or {}).get("error", "")
        self.assertIn("end", err.lower())
        self.assertIn("start", err.lower())
