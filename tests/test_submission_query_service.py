"""Unit tests for submission query safety helpers."""
import unittest

from app.services.submission_query_service import build_safe_order_by, longest_common_hyphen_prefix


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

    def test_longest_common_hyphen_prefix_same_shipment(self):
        self.assertEqual(
            longest_common_hyphen_prefix(
                ["PO-00195-3-18-1", "PO-00195-3-20-6"]
            ),
            "PO-00195-3",
        )

    def test_longest_common_hyphen_prefix_same_po_only(self):
        self.assertEqual(
            longest_common_hyphen_prefix(
                ["PO-00195-3-1-1", "PO-00195-4-1-1"]
            ),
            "PO-00195",
        )

    def test_longest_common_hyphen_prefix_single(self):
        self.assertEqual(
            longest_common_hyphen_prefix(["PO-00195-3-7-1"]),
            "PO-00195-3-7-1",
        )

