"""Tests for shared submission context helpers."""
import sqlite3
import unittest

from app.services.submission_context_service import (
    normalize_optional_text,
    resolve_submission_employee_name,
)


class TestSubmissionContextService(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE employees (id INTEGER PRIMARY KEY, full_name TEXT)")
        self.conn.execute("INSERT INTO employees (id, full_name) VALUES (1, 'Test Employee')")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_normalize_optional_text(self):
        self.assertEqual(normalize_optional_text("  abc "), "abc")
        self.assertEqual(normalize_optional_text(123), "123")
        self.assertIsNone(normalize_optional_text("   "))
        self.assertIsNone(normalize_optional_text(None))

    def test_resolve_prefers_submitted_name(self):
        result = resolve_submission_employee_name(self.conn, "  Line Worker  ", None, False)
        self.assertTrue(result["success"])
        self.assertEqual(result["employee_name"], "Line Worker")

    def test_resolve_uses_admin_fallback(self):
        result = resolve_submission_employee_name(self.conn, None, None, True)
        self.assertTrue(result["success"])
        self.assertEqual(result["employee_name"], "Admin")

    def test_resolve_uses_session_employee(self):
        result = resolve_submission_employee_name(self.conn, None, 1, False)
        self.assertTrue(result["success"])
        self.assertEqual(result["employee_name"], "Test Employee")

    def test_resolve_missing_employee(self):
        result = resolve_submission_employee_name(self.conn, None, 999, False)
        self.assertFalse(result["success"])
        self.assertEqual(result["status_code"], 400)

