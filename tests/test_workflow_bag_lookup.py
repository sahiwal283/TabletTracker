"""workflow_bag_lookup: flavor + box + bag resolution for QR assignment."""
import sqlite3
import unittest

from app.services.workflow_bag_lookup import find_unassigned_inventory_bags_by_flavor_box_bag


class TestWorkflowBagLookup(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE purchase_orders (id INTEGER PRIMARY KEY, po_number TEXT);
            CREATE TABLE receiving (
                id INTEGER PRIMARY KEY,
                po_id INTEGER,
                closed INTEGER DEFAULT 0,
                status TEXT DEFAULT 'published',
                received_date TEXT,
                FOREIGN KEY (po_id) REFERENCES purchase_orders(id)
            );
            CREATE TABLE small_boxes (
                id INTEGER PRIMARY KEY,
                receiving_id INTEGER NOT NULL,
                box_number INTEGER,
                FOREIGN KEY (receiving_id) REFERENCES receiving(id)
            );
            CREATE TABLE bags (
                id INTEGER PRIMARY KEY,
                small_box_id INTEGER NOT NULL,
                bag_number INTEGER NOT NULL,
                tablet_type_id INTEGER NOT NULL,
                status TEXT DEFAULT 'Available',
                reserved_for_bottles INTEGER DEFAULT 0,
                FOREIGN KEY (small_box_id) REFERENCES small_boxes(id)
            );
            CREATE TABLE tablet_types (id INTEGER PRIMARY KEY, tablet_type_name TEXT);
            CREATE TABLE workflow_bags (
                id INTEGER PRIMARY KEY,
                inventory_bag_id INTEGER REFERENCES bags(id)
            );
            CREATE TABLE qr_cards (
                id INTEGER PRIMARY KEY,
                scan_token TEXT,
                status TEXT,
                assigned_workflow_bag_id INTEGER REFERENCES workflow_bags(id)
            );
            INSERT INTO tablet_types (id, tablet_type_name) VALUES (1, 'T1');
            INSERT INTO receiving (id, closed, status, received_date) VALUES (1, 0, 'published', '2026-01-01');
            INSERT INTO small_boxes (id, receiving_id, box_number) VALUES (1, 1, 2);
            INSERT INTO bags (id, small_box_id, bag_number, tablet_type_id) VALUES (10, 1, 3, 1);
            """
        )

    def tearDown(self):
        self.conn.close()

    def test_single_match(self):
        rows = find_unassigned_inventory_bags_by_flavor_box_bag(
            self.conn, tablet_type_id=1, box_number=2, bag_number=3
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], 10)

    def test_includes_linked_bag_when_card_released(self):
        self.conn.execute(
            "INSERT INTO workflow_bags (id, inventory_bag_id) VALUES (100, 10)"
        )
        self.conn.commit()
        rows = find_unassigned_inventory_bags_by_flavor_box_bag(
            self.conn, tablet_type_id=1, box_number=2, bag_number=3
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], 10)

    def test_excludes_active_assigned_card_link(self):
        self.conn.execute(
            "INSERT INTO workflow_bags (id, inventory_bag_id) VALUES (100, 10)"
        )
        self.conn.execute(
            """
            INSERT INTO qr_cards (id, scan_token, status, assigned_workflow_bag_id)
            VALUES (1, 'bag-1', 'assigned', 100)
            """
        )
        self.conn.commit()
        rows = find_unassigned_inventory_bags_by_flavor_box_bag(
            self.conn, tablet_type_id=1, box_number=2, bag_number=3
        )
        self.assertEqual(len(rows), 0)

    def test_includes_reserved_for_bottles_bag(self):
        self.conn.execute(
            "UPDATE bags SET reserved_for_bottles = 1 WHERE id = 10"
        )
        self.conn.commit()
        rows = find_unassigned_inventory_bags_by_flavor_box_bag(
            self.conn, tablet_type_id=1, box_number=2, bag_number=3
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], 10)


if __name__ == "__main__":
    unittest.main()
