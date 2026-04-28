"""Shared workflow bag assignment template context."""

import unittest

from app import create_app
from app.services.workflow_assign_form import build_assign_bag_context, parse_nonnegative_int


class TestWorkflowAssignContext(unittest.TestCase):
    def setUp(self):
        self.app = create_app()

    def test_defaults_match_assign_bag_form_contract(self):
        with self.app.test_request_context():
            ctx = build_assign_bag_context(products=[{"id": 1, "product_name": "Mint"}])

        self.assertEqual(ctx["products"], [{"id": 1, "product_name": "Mint"}])
        self.assertIsNone(ctx["ambiguous_matches"])
        self.assertIsNone(ctx["form_product_id"])
        self.assertIsNone(ctx["form_box_number"])
        self.assertIsNone(ctx["form_bag_number"])
        self.assertIsNone(ctx["form_card_scan_token"])
        self.assertIsNone(ctx["form_receipt_number"])
        self.assertFalse(ctx["form_hand_packed"])
        self.assertEqual(ctx["return_to"], "")
        self.assertEqual(ctx["restart_url"], "/workflow/staff/new-bag")
        self.assertFalse(ctx["products_load_failed"])

    def test_preserves_posted_values_for_disambiguation(self):
        with self.app.test_request_context():
            ctx = build_assign_bag_context(
                products=[],
                ambiguous_matches=[{"id": 7}],
                form_product_id=3,
                form_box_number=4,
                form_bag_number=5,
                form_card_scan_token="bag-card",
                form_receipt_number="PO-1-2-4-5",
                form_hand_packed=True,
                return_to="command_center",
                restart_url="/admin/workflow-qr",
                products_load_failed=True,
            )

        self.assertEqual(ctx["ambiguous_matches"], [{"id": 7}])
        self.assertEqual(ctx["form_product_id"], 3)
        self.assertEqual(ctx["form_box_number"], 4)
        self.assertEqual(ctx["form_bag_number"], 5)
        self.assertEqual(ctx["form_card_scan_token"], "bag-card")
        self.assertEqual(ctx["form_receipt_number"], "PO-1-2-4-5")
        self.assertTrue(ctx["form_hand_packed"])
        self.assertEqual(ctx["return_to"], "command_center")
        self.assertEqual(ctx["restart_url"], "/admin/workflow-qr")
        self.assertTrue(ctx["products_load_failed"])

    def test_parse_nonnegative_int(self):
        self.assertEqual(parse_nonnegative_int("0"), 0)
        self.assertEqual(parse_nonnegative_int("42"), 42)
        self.assertIsNone(parse_nonnegative_int(""))
        self.assertIsNone(parse_nonnegative_int(None))
        self.assertIsNone(parse_nonnegative_int("-1"))
        self.assertIsNone(parse_nonnegative_int("not-a-number"))
