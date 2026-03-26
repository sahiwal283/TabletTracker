"""Unit tests for submission query safety helpers."""
import unittest

from app.services.submission_query_service import build_safe_order_by


class TestSubmissionQueryService(unittest.TestCase):
    def test_build_safe_order_by_defaults(self):
        self.assertEqual(build_safe_order_by(), "ws.created_at DESC")

    def test_build_safe_order_by_valid_field_and_direction(self):
        self.assertEqual(
            build_safe_order_by("employee_name", "asc"),
            "ws.employee_name ASC"
        )

    def test_build_safe_order_by_rejects_unknown_values(self):
        self.assertEqual(
            build_safe_order_by("ws.created_at; DROP TABLE x", "sideways"),
            "ws.created_at DESC"
        )

