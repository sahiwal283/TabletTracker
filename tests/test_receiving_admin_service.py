"""Unit tests for receiving admin service workflows."""
import sqlite3
import unittest

from app.services.receiving_admin_service import (
    publish_receiving,
    unpublish_receiving,
    assign_po_to_receiving,
    toggle_receiving_closed,
    toggle_bag_closed,
)


class TestReceivingAdminService(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE purchase_orders (
                id INTEGER PRIMARY KEY,
                po_number TEXT
            );
            CREATE TABLE receiving (
                id INTEGER PRIMARY KEY,
                po_id INTEGER,
                status TEXT,
                closed INTEGER DEFAULT 0
            );
            CREATE TABLE small_boxes (
                id INTEGER PRIMARY KEY,
                receiving_id INTEGER,
                box_number INTEGER
            );
            CREATE TABLE tablet_types (
                id INTEGER PRIMARY KEY,
                tablet_type_name TEXT
            );
            CREATE TABLE bags (
                id INTEGER PRIMARY KEY,
                small_box_id INTEGER,
                tablet_type_id INTEGER,
                bag_number INTEGER,
                status TEXT
            );
            CREATE TABLE warehouse_submissions (
                id INTEGER PRIMARY KEY,
                bag_id INTEGER
            );
            """
        )
        self.conn.execute("INSERT INTO purchase_orders (id, po_number) VALUES (1, 'PO-001')")
        self.conn.execute("INSERT INTO receiving (id, po_id, status, closed) VALUES (10, 1, 'draft', 0)")
        self.conn.execute("INSERT INTO small_boxes (id, receiving_id, box_number) VALUES (100, 10, 1)")
        self.conn.execute("INSERT INTO tablet_types (id, tablet_type_name) VALUES (5, 'Test Type')")
        self.conn.execute(
            "INSERT INTO bags (id, small_box_id, tablet_type_id, bag_number, status) VALUES (200, 100, 5, 2, 'Available')"
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_publish_and_unpublish_receive(self):
        published = publish_receiving(self.conn, 10)
        self.assertTrue(published["success"])
        self.assertEqual(published["status"], "published")

        unpublished = unpublish_receiving(self.conn, 10)
        self.assertTrue(unpublished["success"])
        self.assertEqual(unpublished["status"], "draft")

    def test_unpublish_blocked_when_submissions_exist(self):
        self.conn.execute("UPDATE receiving SET status = 'published' WHERE id = 10")
        self.conn.execute("INSERT INTO warehouse_submissions (id, bag_id) VALUES (1, 200)")
        self.conn.commit()
        result = unpublish_receiving(self.conn, 10)
        self.assertFalse(result["success"])
        self.assertEqual(result["status_code"], 400)

    def test_assign_po_role_guard(self):
        denied = assign_po_to_receiving(self.conn, 10, 1, "warehouse_staff")
        self.assertFalse(denied["success"])
        self.assertEqual(denied["status_code"], 403)

        ok = assign_po_to_receiving(self.conn, 10, 1, "manager")
        self.assertTrue(ok["success"])
        self.assertEqual(ok["po_number"], "PO-001")

    def test_toggle_receiving_and_bag_closed(self):
        toggled = toggle_receiving_closed(self.conn, 10, "manager", False)
        self.assertTrue(toggled["success"])
        self.assertTrue(toggled["closed"])
        bag = self.conn.execute("SELECT status FROM bags WHERE id = 200").fetchone()
        self.assertEqual(bag["status"], "Closed")

        bag_toggled = toggle_bag_closed(self.conn, 200, "manager", False)
        self.assertTrue(bag_toggled["success"])
        self.assertEqual(bag_toggled["status"], "Available")

