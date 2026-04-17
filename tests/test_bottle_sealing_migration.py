"""Migration adds bottle_sealing_machine_count on warehouse_submissions."""
import os
import shutil
import sqlite3
import tempfile
import unittest

from app.models.migrations import MigrationRunner
from config import Config


class TestBottleSealingMigration(unittest.TestCase):
    def setUp(self):
        self._orig_db = Config.DATABASE_PATH
        fd, self._db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        shutil.copy(self._orig_db, self._db_path)
        Config.DATABASE_PATH = self._db_path

    def tearDown(self):
        Config.DATABASE_PATH = self._orig_db
        if os.path.exists(self._db_path):
            os.remove(self._db_path)

    def test_warehouse_submissions_has_bottle_sealing_machine_count(self):
        conn = sqlite3.connect(self._db_path)
        MigrationRunner(conn.cursor()).run_all()
        conn.commit()
        cols = [r[1] for r in conn.execute("PRAGMA table_info(warehouse_submissions)").fetchall()]
        conn.close()
        self.assertIn("bottle_sealing_machine_count", cols)


if __name__ == "__main__":
    unittest.main()
