"""Unit tests for submissions view query helpers."""
import unittest

from app.services.submissions_view_service import (
    append_submission_common_filters,
    append_submission_archive_tab_filters,
    append_submission_sort,
)


class TestSubmissionsViewService(unittest.TestCase):
    def test_append_common_filters(self):
        query = "SELECT * FROM t WHERE 1=1"
        params = []
        query, params = append_submission_common_filters(
            query,
            params,
            {
                'po_id': 10,
                'item_id': 'INV-1',
                'date_from': '2026-01-01',
                'date_to': '2026-01-31',
                'tablet_type_id': 2,
                'submission_type': 'machine',
                'receipt_number': '123-',
            },
        )
        self.assertIn('ws.assigned_po_id = ?', query)
        self.assertIn('tt.inventory_item_id = ?', query)
        self.assertIn('ws.receipt_number LIKE ?', query)
        self.assertEqual(len(params), 7)
        self.assertEqual(params[-1], '%123-%')

    def test_append_archive_tab_filters(self):
        query = append_submission_archive_tab_filters("Q", False, 'packaged_machine')
        self.assertIn('po.closed IS NULL OR po.closed = FALSE', query)
        self.assertIn("IN ('packaged', 'machine', 'repack')", query)

    def test_append_archive_tab_filters_relax_po_for_receipt_search(self):
        query = append_submission_archive_tab_filters(
            "Q", False, 'packaged_machine', relax_po_closed_for_receipt_search=True
        )
        self.assertNotIn('po.closed IS NULL OR po.closed = FALSE', query)

    def test_append_sort_receipt(self):
        query = append_submission_sort("Q", 'receipt_number', 'desc')
        self.assertIn('CASE WHEN ws.receipt_number IS NULL THEN 1 ELSE 0 END', query)
        self.assertIn('CAST(SUBSTR(ws.receipt_number', query)

