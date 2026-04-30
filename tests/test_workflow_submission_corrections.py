import os
import sqlite3
import tempfile
import unittest

from app.services import workflow_constants as WC
from app.services.workflow_append import append_workflow_event
from app.services.workflow_submission_corrections import apply_qr_submission_correction
from app.services.workflow_warehouse_bridge import sync_if_packaging_snapshot


_SCHEMA = """
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
    tablets_per_bottle INTEGER,
    bottles_per_display INTEGER,
    displays_per_case INTEGER,
    is_bottle_product INTEGER DEFAULT 0,
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
CREATE TABLE workflow_stations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_scan_token TEXT,
    label TEXT,
    station_kind TEXT,
    machine_id INTEGER
);
CREATE TABLE machines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_name TEXT,
    machine_role TEXT
);
CREATE TABLE workflow_bags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at INTEGER NOT NULL,
    product_id INTEGER,
    box_number INTEGER,
    bag_number INTEGER,
    receipt_number TEXT,
    inventory_bag_id INTEGER
);
CREATE TABLE workflow_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    occurred_at INTEGER NOT NULL,
    workflow_bag_id INTEGER NOT NULL,
    station_id INTEGER,
    user_id INTEGER,
    device_id TEXT
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
    cards_reopened INTEGER,
    submission_date TEXT,
    admin_notes TEXT,
    submission_type TEXT DEFAULT 'packaged',
    bag_id INTEGER,
    assigned_po_id INTEGER,
    needs_review INTEGER DEFAULT 0,
    receipt_number TEXT,
    bag_start_time TEXT,
    bag_end_time TEXT,
    machine_id INTEGER,
    case_count INTEGER DEFAULT 0,
    loose_display_count INTEGER DEFAULT 0
);
CREATE TABLE submission_bag_deductions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id INTEGER,
    bag_id INTEGER,
    tablets_deducted INTEGER
);
"""


class TestWorkflowSubmissionCorrections(unittest.TestCase):
    def setUp(self):
        self._path = tempfile.mkstemp(suffix=".db")[1]
        self.conn = sqlite3.connect(self._path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.execute(
            "INSERT INTO tablet_types (tablet_type_name, inventory_item_id) VALUES ('T', 'inv-x')"
        )
        tid = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.execute(
            """
            INSERT INTO product_details (
                product_name, tablet_type_id, packages_per_display,
                tablets_per_package, displays_per_case
            ) VALUES ('P', ?, 12, 10, 24)
            """,
            (tid,),
        )
        pid = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.execute("INSERT INTO purchase_orders (po_number) VALUES ('PO1')")
        poid = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.execute(
            "INSERT INTO receiving (po_id, receive_name, received_date) VALUES (?, 'R', '2026-01-01')",
            (poid,),
        )
        rid = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.execute("INSERT INTO small_boxes (receiving_id, box_number) VALUES (?, 1)", (rid,))
        sbid = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.execute(
            """
            INSERT INTO bags (small_box_id, bag_number, bag_label_count, tablet_type_id, status, po_id)
            VALUES (?, 2, 5000, ?, 'Available', ?)
            """,
            (sbid, tid, poid),
        )
        bid = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.execute(
            "INSERT INTO workflow_stations (station_scan_token, label, station_kind) VALUES ('packaging-x', 'Packaging', 'packaging')"
        )
        self.station_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.execute(
            """
            INSERT INTO workflow_bags (created_at, product_id, box_number, bag_number, inventory_bag_id)
            VALUES (1700000000000, ?, 1, 2, ?)
            """,
            (pid, bid),
        )
        self.workflow_bag_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def test_packaging_edit_appends_correction_and_resyncs_row(self):
        event_id = append_workflow_event(
            self.conn,
            WC.EVENT_PACKAGING_SNAPSHOT,
            {
                "display_count": 5,
                "packs_remaining": 1,
                "cards_reopened": 0,
                "reason": "final_submit",
                "employee_name": "QR",
            },
            self.workflow_bag_id,
            station_id=self.station_id,
        )
        sync = sync_if_packaging_snapshot(
            self.conn,
            self.workflow_bag_id,
            WC.EVENT_PACKAGING_SNAPSHOT,
            {
                "display_count": 5,
                "packs_remaining": 1,
                "cards_reopened": 0,
                "reason": "final_submit",
                "employee_name": "QR",
            },
            station_row={"id": self.station_id},
            event_id=event_id,
        )
        self.assertTrue(sync.get("ok"))
        sub_id = sync["warehouse_submission_id"]

        result = apply_qr_submission_correction(
            self.conn,
            sub_id,
            {
                "displays_made": 7,
                "packs_remaining": 2,
                "cards_reopened": 1,
                "admin_notes": "Corrected typo",
            },
            corrected_by="Manager",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["target_event_id"], event_id)

        correction_count = self.conn.execute(
            "SELECT COUNT(*) FROM workflow_events WHERE event_type = ?",
            (WC.EVENT_SUBMISSION_CORRECTED,),
        ).fetchone()[0]
        self.assertEqual(correction_count, 1)

        rows = self.conn.execute(
            """
            SELECT displays_made, packs_remaining, cards_reopened, receipt_number
            FROM warehouse_submissions
            WHERE submission_type = 'packaged'
            """
        ).fetchall()
        self.assertEqual(len(rows), 1)
        row = dict(rows[0])
        self.assertEqual(row["displays_made"], 7)
        self.assertEqual(row["packs_remaining"], 2)
        self.assertEqual(row["cards_reopened"], 1)
        self.assertEqual(row["receipt_number"], f"WORKFLOW-{self.workflow_bag_id}-pkg-e{event_id}")


if __name__ == "__main__":
    unittest.main()
