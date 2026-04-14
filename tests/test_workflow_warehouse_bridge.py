"""workflow_warehouse_bridge: packaged submission upsert from QR packaging."""
import os
import sqlite3
import tempfile
import unittest

from app.services.workflow_warehouse_bridge import (
    upsert_packaged_from_workflow_packaging,
    workflow_packaged_receipt_number,
)

_MINIMAL_SCHEMA = """
PRAGMA foreign_keys=OFF;
CREATE TABLE tablet_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tablet_type_name TEXT,
    inventory_item_id TEXT
);
CREATE TABLE product_details (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name TEXT,
    tablet_type_id INTEGER,
    packages_per_display INTEGER,
    tablets_per_package INTEGER,
    is_variety_pack INTEGER DEFAULT 0
);
CREATE TABLE purchase_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    po_number TEXT,
    closed INTEGER DEFAULT 0
);
CREATE TABLE receiving (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    po_id INTEGER,
    receive_name TEXT,
    received_date TEXT
);
CREATE TABLE small_boxes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    receiving_id INTEGER,
    box_number INTEGER
);
CREATE TABLE bags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    small_box_id INTEGER,
    bag_number INTEGER,
    bag_label_count INTEGER,
    tablet_type_id INTEGER,
    status TEXT,
    po_id INTEGER
);
CREATE TABLE workflow_bags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at INTEGER NOT NULL,
    product_id INTEGER,
    box_number INTEGER,
    bag_number INTEGER,
    receipt_number TEXT,
    inventory_bag_id INTEGER REFERENCES bags(id)
);
CREATE TABLE warehouse_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_name TEXT,
    product_name TEXT,
    inventory_item_id TEXT,
    box_number INTEGER,
    bag_number INTEGER,
    bag_label_count INTEGER,
    displays_made INTEGER,
    packs_remaining INTEGER,
    loose_tablets INTEGER,
    damaged_tablets INTEGER,
    submission_date TEXT,
    admin_notes TEXT,
    submission_type TEXT DEFAULT 'packaged',
    bag_id INTEGER,
    assigned_po_id INTEGER,
    needs_review INTEGER DEFAULT 0,
    receipt_number TEXT,
    bag_end_time TEXT
);
"""


class TestWorkflowWarehouseBridge(unittest.TestCase):
    def setUp(self):
        self._path = tempfile.mkstemp(suffix=".db")[1]
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.executescript(_MINIMAL_SCHEMA)
        conn.execute(
            "INSERT INTO tablet_types (tablet_type_name, inventory_item_id) VALUES ('T', 'inv-x')"
        )
        tid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """
            INSERT INTO product_details (product_name, tablet_type_id, packages_per_display, tablets_per_package)
            VALUES ('P', ?, 12, 10)
            """,
            (tid,),
        )
        pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO purchase_orders (po_number, closed) VALUES ('PO1', 0)"
        )
        poid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO receiving (po_id, receive_name, received_date) VALUES (?, 'R', '2026-01-01')",
            (poid,),
        )
        rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO small_boxes (receiving_id, box_number) VALUES (?, 1)", (rid,))
        sbid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """
            INSERT INTO bags (small_box_id, bag_number, bag_label_count, tablet_type_id, status, po_id)
            VALUES (?, 2, 5000, ?, 'Available', ?)
            """,
            (sbid, tid, poid),
        )
        bid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """
            INSERT INTO workflow_bags (created_at, product_id, box_number, bag_number, inventory_bag_id)
            VALUES (1700000000000, ?, 1, 2, ?)
            """,
            (pid, bid),
        )
        self._wf_bag_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()
        self.conn = sqlite3.connect(self._path)
        self.conn.row_factory = sqlite3.Row

    def tearDown(self):
        self.conn.close()
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def test_upsert_creates_packaged_submission(self):
        wid = self._wf_bag_id
        r = upsert_packaged_from_workflow_packaging(
            self.conn, wid, displays_made=3
        )
        self.assertTrue(r.get("ok"))
        self.conn.commit()
        receipt = workflow_packaged_receipt_number(wid)
        row = self.conn.execute(
            """
            SELECT displays_made, bag_id, assigned_po_id, submission_type, receipt_number
            FROM warehouse_submissions WHERE receipt_number = ?
            """,
            (receipt,),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["displays_made"], 3)
        self.assertIsNotNone(row["bag_id"])
        self.assertEqual(row["assigned_po_id"], 1)
        self.assertEqual(row["submission_type"], "packaged")

    def test_upsert_replaces_previous(self):
        wid = self._wf_bag_id
        upsert_packaged_from_workflow_packaging(self.conn, wid, displays_made=1)
        self.conn.commit()
        upsert_packaged_from_workflow_packaging(self.conn, wid, displays_made=4)
        self.conn.commit()
        receipt = workflow_packaged_receipt_number(wid)
        n = self.conn.execute(
            "SELECT COUNT(*) FROM warehouse_submissions WHERE receipt_number = ?",
            (receipt,),
        ).fetchone()[0]
        self.assertEqual(n, 1)
        dm = self.conn.execute(
            "SELECT displays_made FROM warehouse_submissions WHERE receipt_number = ?",
            (receipt,),
        ).fetchone()[0]
        self.assertEqual(dm, 4)


if __name__ == "__main__":
    unittest.main()
