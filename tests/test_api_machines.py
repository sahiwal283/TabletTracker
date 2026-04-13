"""
Integration tests for machine role API behavior.
"""
import os
import shutil
import sqlite3
import tempfile
import unittest

from app import create_app
from app.models import database as database_module
from app.models.migrations import MigrationRunner
from config import Config


def _csrf_post(client, path, json_body):
    token_resp = client.get("/api/csrf-token")
    token = token_resp.get_json()["csrf_token"]
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


class TestApiMachines(unittest.TestCase):
    def setUp(self):
        self._orig_db = Config.DATABASE_PATH
        fd, self._db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        shutil.copy(self._orig_db, self._db_path)
        Config.DATABASE_PATH = self._db_path
        database_module._migrations_run = False

        os.environ.setdefault("SKIP_ZOHO_SERVICE_CHECK", "1")
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
        MigrationRunner(conn.cursor()).run_all()
        conn.execute("UPDATE machines SET is_active = 0")
        conn.execute(
            """
            INSERT INTO machines (machine_name, cards_per_turn, machine_role, is_active)
            VALUES
                ('Test Sealer A', 1, 'sealing', 1),
                ('Test Blister A', 1, 'blister', 1)
            """
        )
        conn.commit()
        conn.close()

        self.app = create_app()
        self.client = _admin_client(self.app)

    def tearDown(self):
        Config.DATABASE_PATH = self._orig_db
        database_module._migrations_run = False
        if os.path.exists(self._db_path):
            os.remove(self._db_path)

    def test_get_machines_can_filter_by_role(self):
        all_resp = self.client.get("/api/machines")
        self.assertEqual(all_resp.status_code, 200)
        all_data = all_resp.get_json()
        self.assertTrue(any((m.get("machine_role") == "sealing") for m in all_data.get("machines", [])))
        self.assertTrue(any((m.get("machine_role") == "blister") for m in all_data.get("machines", [])))

        sealing_resp = self.client.get("/api/machines?role=sealing")
        self.assertEqual(sealing_resp.status_code, 200)
        sealing_data = sealing_resp.get_json()
        self.assertGreaterEqual(len(sealing_data.get("machines", [])), 1)
        self.assertTrue(all((m.get("machine_role") == "sealing") for m in sealing_data.get("machines", [])))

        blister_resp = self.client.get("/api/machines?role=blister")
        self.assertEqual(blister_resp.status_code, 200)
        blister_data = blister_resp.get_json()
        self.assertGreaterEqual(len(blister_data.get("machines", [])), 1)
        self.assertTrue(all((m.get("machine_role") == "blister") for m in blister_data.get("machines", [])))

    def test_create_machine_rejects_invalid_role(self):
        resp = _csrf_post(
            self.client,
            "/api/machines",
            {
                "machine_name": "Bad Role Machine",
                "cards_per_turn": 1,
                "machine_role": "invalid-role",
            },
        )
        self.assertEqual(resp.status_code, 400)
        payload = resp.get_json() or {}
        self.assertIn("role", (payload.get("error") or "").lower())


if __name__ == "__main__":
    unittest.main()
