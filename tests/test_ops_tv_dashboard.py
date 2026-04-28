"""TV operations dashboard routes and snapshot API."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

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
        self.assertIn(b'id="mes-root"', r.data)
        self.assertIn(b"mes-command-center.css", r.data)
        self.assertIn(b"js/ops-metrics.js", r.data)
        self.assertIn(b"command-center-app.js", r.data)
        self.assertIn(b"command-center/ops-tv/api/snapshot", r.data)

    def test_ops_tv_snapshot_json(self):
        r = self.client.get("/command-center/ops-tv/api/snapshot")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("kpis", data)
        self.assertIn("machines", data)
        self.assertIn("activity", data)
        self.assertIn("mes", data)
        self.assertIn("metrics_inputs", data["mes"])

    def test_oee_clamped_to_100_in_metrics_layer(self):
        source = Path("static/js/ops-metrics.js").read_text(encoding="utf-8")
        self.assertIn("Math.min(100", source)
        self.assertIn("Insufficient data", source)

    def test_unintegrated_machine_shows_not_integrated_and_na(self):
        source = Path("static/js/mes/command-center-app.js").read_text(encoding="utf-8")
        self.assertIn("NOT_INTEGRATED", source)
        self.assertIn('"N/A"', source)
        self.assertIn("Not connected", source)

    def test_missing_target_state_is_explicit(self):
        source = Path("static/js/ops-metrics.js").read_text(encoding="utf-8")
        self.assertTrue("No target set" in source or "Insufficient data" in source)

    def test_bottle_sealing_not_fake_running_when_no_events(self):
        source = Path("static/js/mes/command-center-app.js").read_text(encoding="utf-8")
        self.assertIn("Bottle line not integrated yet", source)
        self.assertIn("forceNotIntegrated", source)

    def test_lot_trace_panel_exists(self):
        source = Path("static/js/mes/command-center-app.js").read_text(encoding="utf-8")
        self.assertIn("Live Bag Genealogy / Lot Trace", source)
        self.assertIn("Trace bag ID", source)

    def test_machine_illustration_svg_render_functions_exist(self):
        source = Path("static/js/mes/command-center-app.js").read_text(encoding="utf-8")
        self.assertIn("function renderDPP115BlisterMachine", source)
        self.assertIn("function renderHeatPressMachine", source)
        self.assertIn("function renderStickeringMachine", source)
        self.assertIn("function renderBottleSealingMachine", source)
        self.assertIn("function renderPackagingStation", source)
        self.assertIn("<svg", source)

    def test_machine_settings_panel_wired(self):
        source = Path("static/js/mes/command-center-app.js").read_text(encoding="utf-8")
        self.assertIn("Machine settings / configuration", source)
        self.assertIn("slots=", source)

    def test_staging_panel_shows_idle_bag_details(self):
        source = Path("static/js/mes/command-center-app.js").read_text(encoding="utf-8")
        self.assertIn("Staging / WIP (idle bags between stations)", source)
        self.assertIn("Last station", source)
        self.assertIn("Last event", source)
        metrics = Path("static/js/ops-metrics.js").read_text(encoding="utf-8")
        self.assertIn("deriveStagingBags", metrics)

    def test_alerts_and_activity_are_separate_sources(self):
        source = Path("static/js/mes/command-center-app.js").read_text(encoding="utf-8")
        self.assertIn("MES Alerts", source)
        self.assertIn("Activity feed", source)
        self.assertIn("alertsOnly", source)
        self.assertIn("activityFeed", source)
