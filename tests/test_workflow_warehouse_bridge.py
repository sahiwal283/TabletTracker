"""workflow_warehouse_bridge: packaged submission upsert from QR packaging."""
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app.services import workflow_constants as WC
from app.services.workflow_warehouse_bridge import (
    _station_session_start_occurred_at_ms,
    sync_if_packaging_snapshot,
    upsert_bottle_from_workflow_packaging,
    upsert_machine_from_workflow_scan,
    upsert_packaged_from_workflow_packaging,
    workflow_machine_lane_receipt_number,
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
    cards_reopened INTEGER,
    submission_date TEXT,
    admin_notes TEXT,
    submission_type TEXT DEFAULT 'packaged',
    bag_id INTEGER,
    assigned_po_id INTEGER,
    needs_review INTEGER DEFAULT 0,
    receipt_number TEXT,
    bottles_made INTEGER DEFAULT 0,
    bottle_sealing_machine_count INTEGER,
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

    def test_upsert_uses_custom_receipt_base_when_set(self):
        wid = self._wf_bag_id
        self.conn.execute(
            "UPDATE workflow_bags SET receipt_number = ? WHERE id = ?",
            ("PO-RECV-1001", wid),
        )
        self.conn.commit()
        r = upsert_packaged_from_workflow_packaging(self.conn, wid, displays_made=2)
        self.assertTrue(r.get("ok"))
        self.assertEqual(r.get("receipt_number"), "PO-RECV-1001")

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

    def test_packaging_snapshot_case_fields_sync_total_displays(self):
        wid = self._wf_bag_id
        self.conn.execute("UPDATE product_details SET displays_per_case = 12 WHERE id = 1")
        self.conn.commit()
        r = sync_if_packaging_snapshot(
            self.conn,
            wid,
            WC.EVENT_PACKAGING_SNAPSHOT,
            {
                "case_count": 3,
                "loose_display_count": 5,
                "packs_remaining": 2,
                "reason": "final_submit",
            },
            station_row={"id": 1},
        )
        self.assertTrue(r.get("ok"))
        row = self.conn.execute(
            "SELECT displays_made, packs_remaining FROM warehouse_submissions WHERE id = ?",
            (r["warehouse_submission_id"],),
        ).fetchone()
        self.assertEqual(row["displays_made"], 41)
        self.assertEqual(row["packs_remaining"], 2)

    def test_bottle_packaging_upserts_bottle_submission(self):
        self.conn.execute(
            """
            INSERT INTO product_details (
                product_name, tablet_type_id, packages_per_display, tablets_per_package,
                tablets_per_bottle, bottles_per_display, is_bottle_product
            )
            VALUES ('Bottle P', 1, 0, 1, 30, 12, 1)
            """
        )
        pid = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.execute(
            """
            INSERT INTO workflow_bags (created_at, product_id, box_number, bag_number, inventory_bag_id)
            VALUES (1700000000000, ?, 1, 2, 1)
            """,
            (pid,),
        )
        wid = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                occurred_at INTEGER NOT NULL,
                workflow_bag_id INTEGER NOT NULL,
                station_id INTEGER
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO workflow_events (event_type, payload, occurred_at, workflow_bag_id, station_id)
            VALUES (?, ?, 1700000000001, ?, 1)
            """,
            (WC.EVENT_BOTTLE_CAP_SEAL_COMPLETE, '{"count_total": 95}', wid),
        )
        self.conn.commit()

        r = upsert_bottle_from_workflow_packaging(
            self.conn,
            wid,
            displays_made=7,
            bottles_remaining=3,
            station_row={"id": 1},
            employee_name="QR",
        )
        self.assertTrue(r.get("ok"))
        row = self.conn.execute(
            """
            SELECT submission_type, bottles_made, displays_made, packs_remaining,
                   bottle_sealing_machine_count
            FROM warehouse_submissions
            WHERE id = ?
            """,
            (r["warehouse_submission_id"],),
        ).fetchone()
        self.assertEqual(row["submission_type"], "bottle")
        self.assertEqual(row["bottles_made"], 87)
        self.assertEqual(row["displays_made"], 7)
        self.assertEqual(row["packs_remaining"], 3)
        self.assertEqual(row["bottle_sealing_machine_count"], 95)

    def test_per_event_packaging_appends_distinct_receipts(self):
        wid = self._wf_bag_id
        r1 = upsert_packaged_from_workflow_packaging(
            self.conn, wid, displays_made=1, event_id=101
        )
        r2 = upsert_packaged_from_workflow_packaging(
            self.conn, wid, displays_made=2, event_id=102
        )
        self.assertTrue(r1.get("ok"))
        self.assertTrue(r2.get("ok"))
        self.conn.commit()
        n = self.conn.execute(
            "SELECT COUNT(*) FROM warehouse_submissions WHERE submission_type = 'packaged'",
        ).fetchone()[0]
        self.assertEqual(n, 2)
        self.assertEqual(
            workflow_packaged_receipt_number(wid, 101),
            r1.get("receipt_number"),
        )
        self.assertEqual(
            workflow_packaged_receipt_number(wid, 102),
            r2.get("receipt_number"),
        )

    def test_manual_receipt_keeps_same_packaging_receipt_for_events(self):
        wid = self._wf_bag_id
        self.conn.execute(
            "UPDATE workflow_bags SET receipt_number = ? WHERE id = ?",
            ("R-555", wid),
        )
        self.conn.commit()
        r1 = upsert_packaged_from_workflow_packaging(
            self.conn, wid, displays_made=1, event_id=201
        )
        r2 = upsert_packaged_from_workflow_packaging(
            self.conn, wid, displays_made=2, event_id=202
        )
        self.assertTrue(r1.get("ok"))
        self.assertTrue(r2.get("ok"))
        self.assertEqual("R-555", r1.get("receipt_number"))
        self.assertEqual("R-555", r2.get("receipt_number"))

    def test_packaged_stores_employee_name(self):
        wid = self._wf_bag_id
        r = upsert_packaged_from_workflow_packaging(
            self.conn, wid, displays_made=2, employee_name="claudia"
        )
        self.assertTrue(r.get("ok"))
        self.conn.commit()
        receipt = workflow_packaged_receipt_number(wid)
        row = self.conn.execute(
            "SELECT employee_name FROM warehouse_submissions WHERE receipt_number = ?",
            (receipt,),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["employee_name"], "claudia")


class TestWorkflowSessionStartTiming(unittest.TestCase):
    """Bag session start for bridge timing: latest of claim or resume at/before sync."""

    def test_session_start_is_latest_claim_or_resume(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE workflow_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                occurred_at INTEGER NOT NULL,
                workflow_bag_id INTEGER NOT NULL,
                station_id INTEGER,
                payload TEXT
            )
            """
        )
        wid = 1
        sid = 10
        conn.execute(
            """
            INSERT INTO workflow_events (event_type, occurred_at, workflow_bag_id, station_id, payload)
            VALUES (?, 1000, ?, ?, '{}')
            """,
            (WC.EVENT_BAG_CLAIMED, wid, sid),
        )
        conn.execute(
            """
            INSERT INTO workflow_events (event_type, occurred_at, workflow_bag_id, station_id, payload)
            VALUES (?, 2000, ?, ?, '{}')
            """,
            (WC.EVENT_STATION_RESUMED, wid, sid),
        )
        t = _station_session_start_occurred_at_ms(conn, wid, sid, 3000)
        self.assertEqual(t, 2000)
        t2 = _station_session_start_occurred_at_ms(conn, wid, sid, 1500)
        self.assertEqual(t2, 1000)


class TestWorkflowWarehouseMachineBridge(unittest.TestCase):
    """Sealing/blister bridge wiring (execute_machine_submission is mocked)."""

    def setUp(self):
        self._path = tempfile.mkstemp(suffix=".db")[1]
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.executescript(_MINIMAL_SCHEMA)
        conn.executescript(
            """
            CREATE TABLE machines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                machine_name TEXT NOT NULL,
                cards_per_turn INTEGER NOT NULL DEFAULT 1,
                machine_role TEXT NOT NULL DEFAULT 'sealing',
                is_active INTEGER DEFAULT 1
            );
            CREATE TABLE machine_counts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tablet_type_id INTEGER,
                machine_id INTEGER,
                machine_count INTEGER NOT NULL,
                employee_name TEXT NOT NULL,
                count_date TEXT,
                box_number INTEGER,
                bag_number INTEGER
            );
            CREATE TABLE po_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                po_id INTEGER NOT NULL,
                inventory_item_id TEXT,
                quantity_ordered INTEGER DEFAULT 0,
                good_count INTEGER DEFAULT 0,
                damaged_count INTEGER DEFAULT 0,
                machine_good_count INTEGER DEFAULT 0,
                machine_damaged_count INTEGER DEFAULT 0
            );
            ALTER TABLE purchase_orders ADD COLUMN ordered_quantity INTEGER DEFAULT 0;
            ALTER TABLE purchase_orders ADD COLUMN current_good_count INTEGER DEFAULT 0;
            ALTER TABLE purchase_orders ADD COLUMN current_damaged_count INTEGER DEFAULT 0;
            ALTER TABLE purchase_orders ADD COLUMN remaining_quantity INTEGER DEFAULT 0;
            ALTER TABLE purchase_orders ADD COLUMN machine_good_count INTEGER DEFAULT 0;
            ALTER TABLE purchase_orders ADD COLUMN machine_damaged_count INTEGER DEFAULT 0;
            ALTER TABLE purchase_orders ADD COLUMN updated_at TEXT;
            ALTER TABLE warehouse_submissions ADD COLUMN machine_id INTEGER;
            ALTER TABLE warehouse_submissions ADD COLUMN tablets_pressed_into_cards INTEGER DEFAULT 0;
            ALTER TABLE warehouse_submissions ADD COLUMN bag_start_time TEXT;
            """
        )
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
        conn.execute("INSERT INTO po_lines (po_id, inventory_item_id, quantity_ordered) VALUES (?, 'inv-x', 10000)", (poid,))
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
        conn.execute(
            "INSERT INTO machines (machine_name, cards_per_turn, machine_role) VALUES ('Sealer', 1, 'sealing')"
        )
        self._machine_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
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

    @patch("app.services.workflow_warehouse_bridge.execute_machine_submission")
    def test_sealing_calls_execute_with_workflow_receipt(self, m_exec):
        m_exec.return_value = {"success": True}
        wid = self._wf_bag_id
        st = {"id": 1, "machine_id": self._machine_id, "station_kind": "sealing"}
        r = upsert_machine_from_workflow_scan(
            self.conn,
            wid,
            count_total=2,
            station_row=st,
            lane="seal",
            expected_machine_role="sealing",
        )
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(
            m_exec.call_args[0][1].get("receipt_number"),
            workflow_machine_lane_receipt_number(wid, "seal"),
        )
        self.assertEqual(m_exec.call_args[0][3][0]["machine_count"], 2)

    @patch("app.services.workflow_warehouse_bridge.execute_machine_submission")
    def test_sealing_per_event_distinct_receipt(self, m_exec):
        m_exec.return_value = {"success": True}
        wid = self._wf_bag_id
        st = {"id": 1, "machine_id": self._machine_id, "station_kind": "sealing"}
        r = upsert_machine_from_workflow_scan(
            self.conn,
            wid,
            count_total=3,
            station_row=st,
            lane="seal",
            expected_machine_role="sealing",
            event_id=77,
        )
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(
            m_exec.call_args[0][1].get("receipt_number"),
            workflow_machine_lane_receipt_number(wid, "seal", 77),
        )

    @patch("app.services.workflow_warehouse_bridge.execute_machine_submission")
    def test_clear_count_deletes_without_execute(self, m_exec):
        wid = self._wf_bag_id
        receipt = workflow_machine_lane_receipt_number(wid, "seal")
        self.conn.execute(
            """
            INSERT INTO warehouse_submissions (
                employee_name, product_name, inventory_item_id, box_number, bag_number,
                displays_made, packs_remaining, tablets_pressed_into_cards, submission_date,
                submission_type, bag_id, assigned_po_id, needs_review, machine_id,
                receipt_number
            ) VALUES ('QR workflow', 'P', 'inv-x', 1, 2, 1, 1, 10, '2026-01-01',
                'machine', 1, 1, 0, ?, ?)
            """,
            (self._machine_id, receipt),
        )
        self.conn.execute(
            """
            INSERT INTO machine_counts (tablet_type_id, machine_id, machine_count, employee_name, count_date, box_number, bag_number)
            VALUES (1, ?, 1, 'QR workflow', '2026-01-01', 1, 2)
            """,
            (self._machine_id,),
        )
        self.conn.execute(
            "UPDATE po_lines SET machine_good_count = 10 WHERE id = 1",
        )
        st = {"id": 1, "machine_id": self._machine_id, "station_kind": "sealing"}
        r = upsert_machine_from_workflow_scan(
            self.conn,
            wid,
            count_total=0,
            station_row=st,
            lane="seal",
            expected_machine_role="sealing",
        )
        self.assertTrue(r.get("ok"), r)
        self.assertTrue(r.get("cleared"))
        m_exec.assert_not_called()
        n = self.conn.execute(
            "SELECT COUNT(*) FROM warehouse_submissions WHERE receipt_number = ?",
            (receipt,),
        ).fetchone()[0]
        self.assertEqual(n, 0)

    @patch("app.services.workflow_warehouse_bridge.execute_machine_submission")
    def test_manual_receipt_keeps_same_machine_receipt_for_events(self, m_exec):
        m_exec.return_value = {"success": True}
        wid = self._wf_bag_id
        self.conn.execute(
            "UPDATE workflow_bags SET receipt_number = ? WHERE id = ?",
            ("R-777", wid),
        )
        self.conn.commit()
        st = {"id": 1, "machine_id": self._machine_id, "station_kind": "sealing"}
        r = upsert_machine_from_workflow_scan(
            self.conn,
            wid,
            count_total=3,
            station_row=st,
            lane="seal",
            expected_machine_role="sealing",
            event_id=77,
        )
        self.assertTrue(r.get("ok"), r)
        self.assertEqual("R-777", m_exec.call_args[0][1].get("receipt_number"))

    @patch("app.services.workflow_warehouse_bridge.execute_machine_submission")
    def test_blister_handpack_rest_sets_needs_review(self, m_exec):
        wid = self._wf_bag_id
        self.conn.execute(
            "INSERT INTO machines (machine_name, cards_per_turn, machine_role) VALUES ('Blister', 1, 'blister')"
        )
        blister_machine_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        st = {"id": 1, "machine_id": blister_machine_id, "station_kind": "blister"}
        def _mock_exec(conn, data, employee_name, entries):
            conn.execute(
                """
                INSERT INTO warehouse_submissions (
                    employee_name, product_name, inventory_item_id, box_number, bag_number,
                    displays_made, packs_remaining, tablets_pressed_into_cards, submission_date,
                    submission_type, bag_id, assigned_po_id, needs_review, machine_id,
                    receipt_number
                ) VALUES (?, 'P', 'inv-x', ?, ?, ?, 0, 10, '2026-01-01',
                    'machine', 1, 1, 0, ?, ?)
                """,
                (
                    employee_name,
                    data.get("box_number"),
                    data.get("bag_number"),
                    int(entries[0]["machine_count"]),
                    int(data.get("machine_id")),
                    data.get("receipt_number"),
                ),
            )
            return {"success": True}

        m_exec.side_effect = _mock_exec
        r = upsert_machine_from_workflow_scan(
            self.conn,
            wid,
            count_total=3,
            station_row=st,
            lane="blister",
            expected_machine_role="blister",
            handpack_rest=True,
        )
        self.assertTrue(r.get("ok"), r)
        self.assertTrue(r.get("handpack_rest"))
        reviewed = self.conn.execute(
            """
            SELECT COALESCE(needs_review, 0) AS needs_review
            FROM warehouse_submissions
            WHERE receipt_number = ? AND submission_type = 'machine' AND machine_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (workflow_machine_lane_receipt_number(wid, "blister"), blister_machine_id),
        ).fetchone()
        self.assertIsNotNone(reviewed)
        self.assertEqual(int(reviewed["needs_review"] or 0), 1)


if __name__ == "__main__":
    unittest.main()
