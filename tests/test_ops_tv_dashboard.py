"""TV operations dashboard routes and snapshot API."""
import os
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


class TestOpsTvDashboard(unittest.TestCase):
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

    def test_ops_tv_page_requires_admin(self):
        anon = self.app.test_client()
        r = anon.get("/command-center/ops-tv", follow_redirects=False)
        self.assertIn(r.status_code, (302, 401))

    def test_ops_tv_page_loads(self):
        r = self.client.get("/command-center/ops-tv")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"id=\"mes-root\"", r.data)
        self.assertIn(b"mes-command-center.css", r.data)
        self.assertIn(b"js/mes/vendor/react.production.min.js", r.data)
        self.assertIn(b"js/mes/vendor/htm.umd.js", r.data)
        self.assertIn(b"command-center-app.js", r.data)
        self.assertIn(b"command-center/ops-tv/api/snapshot", r.data)
        self.assertIn(b"ops-tv-initial-data", r.data)
        self.assertIn(b'"kpis"', r.data)
        self.assertIn(b'"pill_board"', r.data)
        self.assertIn(b'"mes"', r.data)

    def test_ops_tv_snapshot_json(self):
        r = self.client.get("/command-center/ops-tv/api/snapshot")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("kpis", data)
        self.assertIn("machines", data)
        self.assertIn("activity", data)
        self.assertIn("chart_hourly_output", data)
        self.assertIn("flow", data)
        self.assertIn("pipeline", data["flow"])
        self.assertIn("bottleneck", data["flow"])
        self.assertIn("pill_board", data)
        self.assertIn("mes", data)
        for m in data.get("machines") or []:
            self.assertIn("rate_hist_uh", m)
            self.assertIn("perf_tier", m)
            break
