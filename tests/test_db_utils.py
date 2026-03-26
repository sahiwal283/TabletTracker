"""Unit tests for db utility safety defaults."""
import os
import sqlite3
import tempfile
import unittest

from app.utils import db_utils
from config import Config


class TestDbUtils(unittest.TestCase):
    def test_get_db_enables_foreign_keys(self):
        fd, tmp_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        original_path = Config.DATABASE_PATH
        try:
            Config.DATABASE_PATH = tmp_path
            conn = db_utils.get_db()
            row = conn.execute("PRAGMA foreign_keys").fetchone()
            conn.close()
            self.assertEqual(row[0], 1)
        finally:
            Config.DATABASE_PATH = original_path
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

