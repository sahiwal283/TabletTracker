
"""Workflow subsystem tests (SQLite temp file)."""
import os
import sqlite3
import tempfile
import unittest

# Ensure DATABASE_PATH before importing app modules that read Config at import time
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_PATH"] = _tmp.name


def _bootstrap(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = OFF;
        CREATE TABLE IF NOT EXISTS workflow_stations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            station_scan_token TEXT NOT NULL UNIQUE,
            label TEXT NOT NULL,
            station_code TEXT
        );
        CREATE TABLE IF NOT EXISTS workflow_bags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at INTEGER NOT NULL,
            product_id INTEGER,
            box_number TEXT,
            bag_number TEXT,
            receipt_number TEXT,
            inventory_bag_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS qr_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT,
            scan_token TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'idle',
            assigned_workflow_bag_id INTEGER REFERENCES workflow_bags(id)
        );
        CREATE TABLE IF NOT EXISTS workflow_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            occurred_at INTEGER NOT NULL,
            workflow_bag_id INTEGER NOT NULL REFERENCES workflow_bags(id),
            station_id INTEGER REFERENCES workflow_stations(id),
            user_id INTEGER,
            device_id TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_workflow_events_one_bag_finalized
        ON workflow_events(workflow_bag_id)
        WHERE event_type = 'BAG_FINALIZED';
        """
    )
    conn.execute(
        "INSERT INTO workflow_stations (station_scan_token, label) VALUES ('st1','S1')"
    )
    for i in range(3):
        conn.execute(
            "INSERT INTO qr_cards (label, scan_token, status) VALUES (?,?, 'idle')",
            (f"C{i}", f"tok{i}"),
        )
    conn.commit()


class TestWorkflowCore(unittest.TestCase):
    def setUp(self):
        path = os.environ["DATABASE_PATH"]
        try:
            os.unlink(path)
        except OSError:
            pass
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        _bootstrap(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_finalize_happy_path(self):
        from app.services.workflow_append import append_workflow_event
        from app.services.workflow_finalize import create_workflow_bag_with_card, try_finalize
        from app.services.workflow_read import load_events_for_bag

        bag_id, card_id = create_workflow_bag_with_card(self.conn, product_id=None, box_number="1", bag_number="1", receipt_number=None, user_id=None)
        append_workflow_event(self.conn, "BLISTER_COMPLETE", {"count_total": 10}, bag_id)
        append_workflow_event(self.conn, "SEALING_COMPLETE", {"station_id": 1, "count_total": 10}, bag_id)
        append_workflow_event(self.conn, "PACKAGING_SNAPSHOT", {"display_count": 1, "reason": "x"}, bag_id)
        self.conn.commit()

        st, body = try_finalize(self.conn, bag_id, station_id=1)
        self.assertEqual(st, "ok")
        self.assertFalse(body.get("idempotent_duplicate"))
        ev = load_events_for_bag(self.conn, bag_id)
        self.assertTrue(any(e["event_type"] == "BAG_FINALIZED" for e in ev))
        row = self.conn.execute("SELECT status, assigned_workflow_bag_id FROM qr_cards WHERE id = ?", (card_id,)).fetchone()
        self.assertEqual(row["status"], "idle")
        self.assertIsNone(row["assigned_workflow_bag_id"])

    def test_finalize_idempotent_duplicate(self):
        from app.services.workflow_append import append_workflow_event
        from app.services.workflow_finalize import create_workflow_bag_with_card, try_finalize

        bag_id, _ = create_workflow_bag_with_card(self.conn, product_id=None, box_number="1", bag_number="2", receipt_number=None, user_id=None)
        append_workflow_event(self.conn, "BLISTER_COMPLETE", {"count_total": 1}, bag_id)
        append_workflow_event(self.conn, "SEALING_COMPLETE", {"station_id": 1, "count_total": 1}, bag_id)
        append_workflow_event(self.conn, "PACKAGING_SNAPSHOT", {"display_count": 1, "reason": "x"}, bag_id)
        self.conn.commit()
        st1, _ = try_finalize(self.conn, bag_id, station_id=1)
        self.assertEqual(st1, "ok")
        st2, body2 = try_finalize(self.conn, bag_id, station_id=1)
        self.assertEqual(st2, "duplicate")
        self.assertTrue(body2.get("idempotent_duplicate"))

    def test_finalize_hand_packed_bypasses_blister(self):
        from app.services.workflow_append import append_workflow_event
        from app.services.workflow_finalize import create_workflow_bag_with_card, try_finalize

        bag_id, card_id = create_workflow_bag_with_card(
            self.conn,
            product_id=None,
            box_number="1",
            bag_number="22",
            receipt_number=None,
            user_id=None,
            hand_packed=True,
        )
        append_workflow_event(
            self.conn, "SEALING_COMPLETE", {"station_id": 1, "count_total": 10}, bag_id
        )
        append_workflow_event(
            self.conn, "PACKAGING_SNAPSHOT", {"display_count": 1, "reason": "x"}, bag_id
        )
        self.conn.commit()

        st, body = try_finalize(self.conn, bag_id, station_id=1)
        self.assertEqual(st, "ok")
        self.assertFalse(body.get("idempotent_duplicate"))
        row = self.conn.execute(
            "SELECT status, assigned_workflow_bag_id FROM qr_cards WHERE id = ?",
            (card_id,),
        ).fetchone()
        self.assertEqual(row["status"], "idle")
        self.assertIsNone(row["assigned_workflow_bag_id"])

    def test_payload_reject_unknown_key(self):
        from app.services.workflow_append import append_workflow_event
        from app.services.workflow_finalize import create_workflow_bag_with_card
        from flask import Flask

        bag_id, _ = create_workflow_bag_with_card(self.conn, product_id=None, box_number="1", bag_number="3", receipt_number=None, user_id=None)
        self.conn.commit()
        app = Flask(__name__)
        app.config["DEBUG"] = True
        app.config["TESTING"] = True
        with app.app_context():
            with self.assertRaises(ValueError):
                append_workflow_event(self.conn, "BLISTER_COMPLETE", {"count_total": 1, "oops": 1}, bag_id)

    def test_floor_bag_verification_denormalized(self):
        from app.services.workflow_read import floor_bag_verification

        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS product_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_name TEXT
            );
            INSERT INTO product_details (id, product_name) VALUES (501, 'Test Product A');
            INSERT INTO workflow_bags (id, created_at, product_id, box_number, bag_number, receipt_number)
            VALUES (501, 1, 501, '2', '9', 'PO-77-2');
            """
        )
        self.conn.commit()
        v = floor_bag_verification(self.conn, 501)
        self.assertEqual(v.get("product_name"), "Test Product A")
        self.assertEqual(v.get("box_display"), "Box 2")
        self.assertEqual(v.get("bag_display"), "Bag 9")
        self.assertEqual(v.get("shipment_label"), "PO-77-2")
        self.assertEqual(v.get("receipt_number"), "PO-77-2")
        self.assertIsNone(v.get("po_number"))

    def test_production_day(self):
        from app.services.workflow_read import production_day_for_event_ms
        from datetime import date

        # 2026-01-15 05:00 UTC -> still previous calendar day in NY
        ms = int(1_738_012_800_000)  # arbitrary fixed ms
        d = production_day_for_event_ms(ms)
        self.assertIsInstance(d, date)


if __name__ == "__main__":
    unittest.main()
