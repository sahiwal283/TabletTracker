"""Tests for submission details service bag payloads."""
import sqlite3
import unittest

from app.services.submission_details_service import get_bag_submissions_payload


class TestSubmissionDetailsService(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE tablet_types (id INTEGER PRIMARY KEY, inventory_item_id TEXT);
            CREATE TABLE product_details (
                id INTEGER PRIMARY KEY,
                tablet_type_id INTEGER,
                product_name TEXT,
                packages_per_display INTEGER,
                tablets_per_package INTEGER,
                tablets_per_bottle INTEGER,
                bottles_per_display INTEGER,
                is_bottle_product INTEGER DEFAULT 0
            );
            CREATE TABLE receiving (id INTEGER PRIMARY KEY, po_id INTEGER);
            CREATE TABLE small_boxes (id INTEGER PRIMARY KEY, receiving_id INTEGER, box_number INTEGER);
            CREATE TABLE bags (id INTEGER PRIMARY KEY, small_box_id INTEGER, tablet_type_id INTEGER, bag_number INTEGER);
            CREATE TABLE machines (
                id INTEGER PRIMARY KEY,
                machine_name TEXT,
                machine_role TEXT DEFAULT 'sealing'
            );
            CREATE TABLE warehouse_submissions (
                id INTEGER PRIMARY KEY,
                employee_name TEXT,
                bag_id INTEGER,
                inventory_item_id TEXT,
                bag_number INTEGER,
                box_number INTEGER,
                assigned_po_id INTEGER,
                submission_type TEXT,
                product_name TEXT,
                displays_made INTEGER,
                packs_remaining INTEGER,
                tablets_pressed_into_cards INTEGER,
                loose_tablets INTEGER,
                bottles_made INTEGER,
                machine_id INTEGER,
                submission_date TEXT,
                created_at TEXT
            );
            CREATE TABLE submission_bag_deductions (
                id INTEGER PRIMARY KEY,
                submission_id INTEGER,
                bag_id INTEGER,
                tablets_deducted INTEGER,
                created_at TEXT
            );
            """
        )
        self.conn.execute("INSERT INTO tablet_types (id, inventory_item_id) VALUES (1, 'INV-1')")
        self.conn.execute(
            "INSERT INTO product_details (id, tablet_type_id, product_name, packages_per_display, tablets_per_package, tablets_per_bottle, bottles_per_display) VALUES (1, 1, 'Prod A', 2, 10, 5, 2)"
        )
        self.conn.execute("INSERT INTO receiving (id, po_id) VALUES (1, 55)")
        self.conn.execute("INSERT INTO small_boxes (id, receiving_id, box_number) VALUES (1, 1, 3)")
        self.conn.execute("INSERT INTO bags (id, small_box_id, tablet_type_id, bag_number) VALUES (7, 1, 1, 2)")

        self.conn.execute(
            "INSERT INTO warehouse_submissions (id, bag_id, inventory_item_id, bag_number, box_number, assigned_po_id, submission_type, product_name, displays_made, packs_remaining, created_at) VALUES (101, 7, 'INV-1', 2, 3, 55, 'packaged', 'Prod A', 1, 2, '2026-01-01')"
        )
        self.conn.execute(
            "INSERT INTO warehouse_submissions (id, bag_id, inventory_item_id, bag_number, box_number, assigned_po_id, submission_type, product_name, bottles_made, displays_made, packs_remaining, created_at) VALUES (102, 7, 'INV-1', 2, 3, 55, 'bottle', 'Prod A', 3, 1, 1, '2026-01-02')"
        )
        self.conn.execute(
            "INSERT INTO submission_bag_deductions (id, submission_id, bag_id, tablets_deducted, created_at) VALUES (1, 102, 7, 12, '2026-01-02')"
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_returns_bag_payload_and_totals(self):
        payload = get_bag_submissions_payload(self.conn, 7)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["bag"]["po_id"], 55)
        self.assertEqual(len(payload["submissions"]), 2)
        # packaged: (1*2*10) + (2*10) = 40
        packaged = [s for s in payload["submissions"] if s["id"] == 101][0]
        self.assertEqual(packaged["total_tablets"], 40)
        bottle = [s for s in payload["submissions"] if s["id"] == 102][0]
        self.assertEqual(bottle["total_tablets"], 12)
        self.assertEqual(len(payload["variety_pack_deductions"]), 1)

    def test_not_found(self):
        payload = get_bag_submissions_payload(self.conn, 999)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["status_code"], 404)

