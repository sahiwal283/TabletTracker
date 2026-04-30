
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
        CREATE TABLE IF NOT EXISTS product_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT,
            is_bottle_product INTEGER DEFAULT 0,
            is_variety_pack INTEGER DEFAULT 0
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

    def test_finalize_bottle_path_requires_bottle_steps(self):
        from app.services.workflow_append import append_workflow_event
        from app.services.workflow_finalize import create_workflow_bag_with_card, try_finalize

        self.conn.execute(
            "INSERT INTO product_details (id, product_name, is_bottle_product) VALUES (701, 'Bottle Product', 1)"
        )
        self.conn.commit()
        bag_id, card_id = create_workflow_bag_with_card(
            self.conn,
            product_id=701,
            box_number="1",
            bag_number="23",
            receipt_number=None,
            user_id=None,
        )
        append_workflow_event(
            self.conn, "BOTTLE_HANDPACK_COMPLETE", {"count_total": 100, "qa_checked": True}, bag_id
        )
        append_workflow_event(
            self.conn, "BOTTLE_CAP_SEAL_COMPLETE", {"station_id": 1, "count_total": 96}, bag_id
        )
        append_workflow_event(
            self.conn, "BOTTLE_STICKER_COMPLETE", {"station_id": 1, "count_total": 94}, bag_id
        )
        append_workflow_event(
            self.conn, "PACKAGING_SNAPSHOT", {"display_count": 4, "reason": "x"}, bag_id
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

    def test_finalize_bottle_rejects_card_only_steps(self):
        from app.services.workflow_append import append_workflow_event
        from app.services.workflow_finalize import create_workflow_bag_with_card, try_finalize

        self.conn.execute(
            "INSERT INTO product_details (id, product_name, is_bottle_product) VALUES (702, 'Bottle Product B', 1)"
        )
        self.conn.commit()
        bag_id, _ = create_workflow_bag_with_card(
            self.conn,
            product_id=702,
            box_number="1",
            bag_number="24",
            receipt_number=None,
            user_id=None,
        )
        append_workflow_event(self.conn, "BLISTER_COMPLETE", {"count_total": 10}, bag_id)
        append_workflow_event(self.conn, "SEALING_COMPLETE", {"station_id": 1, "count_total": 10}, bag_id)
        append_workflow_event(
            self.conn, "PACKAGING_SNAPSHOT", {"display_count": 1, "reason": "x"}, bag_id
        )
        self.conn.commit()

        st, body = try_finalize(self.conn, bag_id, station_id=1)
        self.assertEqual(st, "reject")
        self.assertIn("missing_bottle_handpack", body["details"]["reasons"])

    def test_finalize_variety_keeps_scanned_source_cards_with_bags(self):
        from app.services.workflow_append import append_workflow_event
        from app.services.workflow_finalize import create_workflow_bag_with_card, try_finalize

        self.conn.execute(
            "INSERT INTO product_details (id, product_name, is_bottle_product) VALUES (703, 'Variety Bottle', 1)"
        )
        self.conn.commit()
        main_id, main_card_id = create_workflow_bag_with_card(
            self.conn,
            product_id=703,
            box_number="1",
            bag_number="25",
            receipt_number=None,
            user_id=None,
        )
        source_id, source_card_id = create_workflow_bag_with_card(
            self.conn,
            product_id=703,
            box_number="1",
            bag_number="26",
            receipt_number=None,
            user_id=None,
        )
        append_workflow_event(
            self.conn,
            "BOTTLE_HANDPACK_COMPLETE",
            {
                "count_total": 100,
                "qa_checked": True,
                "source_workflow_bag_ids": [main_id, source_id],
            },
            main_id,
        )
        append_workflow_event(
            self.conn, "BOTTLE_CAP_SEAL_COMPLETE", {"station_id": 1, "count_total": 96}, main_id
        )
        append_workflow_event(
            self.conn, "BOTTLE_STICKER_COMPLETE", {"station_id": 1, "count_total": 94}, main_id
        )
        append_workflow_event(
            self.conn, "PACKAGING_SNAPSHOT", {"display_count": 4, "reason": "x"}, main_id
        )
        self.conn.commit()

        st, _body = try_finalize(self.conn, main_id, station_id=1)
        self.assertEqual(st, "ok")
        rows = self.conn.execute(
            """
            SELECT id, status, assigned_workflow_bag_id
            FROM qr_cards
            WHERE id IN (?, ?)
            ORDER BY id
            """,
            (main_card_id, source_card_id),
        ).fetchall()
        self.assertEqual(
            [(r["status"], r["assigned_workflow_bag_id"]) for r in rows],
            [("idle", None), ("assigned", source_id)],
        )
        ev = self.conn.execute(
            """
            SELECT payload
            FROM workflow_events
            WHERE workflow_bag_id = ? AND event_type = 'CARD_FORCE_RELEASED'
            """,
            (source_id,),
        ).fetchone()
        self.assertIsNone(ev)

    def test_assign_variety_pack_run_to_card_with_source_bag_cards(self):
        from app.services.workflow_finalize import (
            assign_variety_pack_run_to_card,
            create_workflow_bag_with_card,
        )

        self.conn.execute(
            """
            INSERT INTO product_details (id, product_name, is_bottle_product, is_variety_pack)
            VALUES (704, 'Variety Bottle Run', 0, 1), (707, 'Flavor Source', 0, 0)
            """
        )
        self.conn.commit()
        source_bag_id, source_card_id = create_workflow_bag_with_card(
            self.conn,
            product_id=707,
            box_number="2",
            bag_number="9",
            receipt_number="SRC",
            user_id=None,
            inventory_bag_id=123,
        )

        bag_id, card_id = assign_variety_pack_run_to_card(
            self.conn,
            product_id=704,
            user_id=None,
            card_scan_token="tok1",
            receipt_number_override="VAR-RUN-1",
            source_card_tokens="tok0",
        )
        self.conn.commit()
        wb = self.conn.execute(
            "SELECT product_id, inventory_bag_id, receipt_number FROM workflow_bags WHERE id = ?",
            (bag_id,),
        ).fetchone()
        card = self.conn.execute(
            "SELECT status, assigned_workflow_bag_id FROM qr_cards WHERE id = ?",
            (card_id,),
        ).fetchone()
        self.assertEqual(wb["product_id"], 704)
        self.assertIsNone(wb["inventory_bag_id"])
        self.assertEqual(wb["receipt_number"], "VAR-RUN-1")
        self.assertEqual(card["status"], "assigned")
        self.assertEqual(card["assigned_workflow_bag_id"], bag_id)
        ev = self.conn.execute(
            """
            SELECT payload
            FROM workflow_events
            WHERE workflow_bag_id = ? AND event_type = 'VARIETY_SOURCES_ASSIGNED'
            """,
            (bag_id,),
        ).fetchone()
        self.assertIsNotNone(ev)
        import json

        payload = json.loads(ev["payload"])
        self.assertEqual(payload["source_qr_card_ids"], [source_card_id])
        self.assertEqual(payload["source_workflow_bag_ids"], [source_bag_id])
        self.assertEqual(payload["source_inventory_bag_ids"], [123])

    def test_active_variety_parent_locks_source_bag_until_finalized(self):
        from app.blueprints.workflow_floor import _active_variety_parent_for_source_bag
        from app.services.workflow_append import append_workflow_event
        from app.services.workflow_finalize import create_workflow_bag_with_card, try_finalize

        self.conn.execute(
            """
            INSERT INTO product_details (id, product_name, is_bottle_product, is_variety_pack)
            VALUES (705, 'Variety Parent', 1, 1), (706, 'Flavor Bag Product', 0, 0)
            """
        )
        self.conn.commit()
        parent_id, _ = create_workflow_bag_with_card(
            self.conn,
            product_id=705,
            box_number=None,
            bag_number=None,
            receipt_number="VAR-LOCK",
            user_id=None,
        )
        source_id, _ = create_workflow_bag_with_card(
            self.conn,
            product_id=706,
            box_number="1",
            bag_number="27",
            receipt_number=None,
            user_id=None,
        )
        append_workflow_event(
            self.conn,
            "VARIETY_SOURCES_ASSIGNED",
            {"source_workflow_bag_ids": [source_id], "source_inventory_bag_ids": [456]},
            parent_id,
        )
        self.conn.commit()

        locked = _active_variety_parent_for_source_bag(self.conn, source_id)
        self.assertIsNotNone(locked)
        self.assertEqual(locked["parent_workflow_bag_id"], parent_id)
        self.assertEqual(locked["parent_label"], "VAR-LOCK")

        append_workflow_event(
            self.conn, "BOTTLE_HANDPACK_COMPLETE", {"count_total": 100, "qa_checked": True}, parent_id
        )
        append_workflow_event(
            self.conn, "BOTTLE_CAP_SEAL_COMPLETE", {"station_id": 1, "count_total": 96}, parent_id
        )
        append_workflow_event(
            self.conn, "BOTTLE_STICKER_COMPLETE", {"station_id": 1, "count_total": 94}, parent_id
        )
        append_workflow_event(
            self.conn, "PACKAGING_SNAPSHOT", {"display_count": 4, "reason": "x"}, parent_id
        )
        self.conn.commit()
        st, _body = try_finalize(self.conn, parent_id, station_id=1)
        self.assertEqual(st, "ok")
        self.assertIsNone(_active_variety_parent_for_source_bag(self.conn, source_id))

    def test_blister_material_change_requires_resume(self):
        from app.blueprints.workflow_floor import _station_facts_payload
        from app.services.workflow_append import append_workflow_event
        from app.services.workflow_finalize import create_workflow_bag_with_card

        bag_id, _ = create_workflow_bag_with_card(
            self.conn,
            product_id=None,
            box_number="1",
            bag_number="31",
            receipt_number=None,
            user_id=None,
        )
        append_workflow_event(
            self.conn,
            "BAG_CLAIMED",
            {"station_id": 1, "station_kind": "blister", "note": "claimed"},
            bag_id,
            station_id=1,
        )
        append_workflow_event(
            self.conn,
            "BLISTER_COMPLETE",
            {
                "count_total": 22,
                "reason": "material_change",
                "pause_reason": "material_change",
                "metadata": {
                    "paused": True,
                    "reason": "material_change",
                    "material_type": "foil",
                },
            },
            bag_id,
            station_id=1,
        )
        facts = _station_facts_payload(self.conn, bag_id, 1)
        self.assertTrue(facts["resume_required"])
        self.assertEqual(facts["pause_details"]["reason"], "material_change")
        self.assertEqual(facts["pause_details"]["material_type"], "foil")
        row = self.conn.execute(
            """
            SELECT json_extract(payload, '$.reason') AS reason,
                   json_extract(payload, '$.pause_reason') AS pause_reason
            FROM workflow_events
            WHERE workflow_bag_id = ? AND event_type = 'BLISTER_COMPLETE'
            """,
            (bag_id,),
        ).fetchone()
        self.assertEqual(row["reason"], "material_change")
        self.assertEqual(row["pause_reason"], "material_change")

        append_workflow_event(
            self.conn,
            "STATION_RESUMED",
            {"station_id": 1, "station_kind": "blister", "note": "resumed"},
            bag_id,
            station_id=1,
        )
        facts = _station_facts_payload(self.conn, bag_id, 1)
        self.assertFalse(facts["resume_required"])
        self.assertIsNone(facts["pause_details"])

    def test_out_of_packaging_hold_releases_occupancy_without_resume_lock(self):
        from app.blueprints.workflow_floor import (
            _occupancy_lane_finished_at_station,
            _station_facts_payload,
        )
        from app.services.workflow_append import append_workflow_event
        from app.services.workflow_finalize import create_workflow_bag_with_card

        bag_id, _ = create_workflow_bag_with_card(
            self.conn,
            product_id=None,
            box_number="1",
            bag_number="32",
            receipt_number=None,
            user_id=None,
        )
        append_workflow_event(
            self.conn,
            "BAG_CLAIMED",
            {"station_id": 1, "station_kind": "sealing", "note": "claimed"},
            bag_id,
            station_id=1,
        )
        append_workflow_event(
            self.conn,
            "SEALING_COMPLETE",
            {
                "station_id": 1,
                "count_total": 53,
                "employee_name": "Juan",
                "metadata": {"paused": True, "reason": "out_of_packaging"},
            },
            bag_id,
            station_id=1,
        )
        facts = _station_facts_payload(self.conn, bag_id, 1)
        self.assertFalse(facts["resume_required"])
        self.assertIsNone(facts["pause_details"])
        self.assertEqual((facts.get("hold_details") or {}).get("reason"), "out_of_packaging")
        self.assertTrue(
            _occupancy_lane_finished_at_station(
                self.conn,
                station_id=1,
                workflow_bag_id=bag_id,
                station_kind="sealing",
            )
        )

    def test_packaging_out_of_packaging_hold_does_not_require_resume(self):
        from app.blueprints.workflow_floor import (
            _occupancy_lane_finished_at_station,
            _station_facts_payload,
        )
        from app.services.workflow_append import append_workflow_event
        from app.services.workflow_finalize import create_workflow_bag_with_card

        bag_id, _ = create_workflow_bag_with_card(
            self.conn,
            product_id=None,
            box_number="1",
            bag_number="33",
            receipt_number=None,
            user_id=None,
        )
        append_workflow_event(
            self.conn,
            "BAG_CLAIMED",
            {"station_id": 1, "station_kind": "packaging", "note": "claimed"},
            bag_id,
            station_id=1,
        )
        append_workflow_event(
            self.conn,
            "PACKAGING_SNAPSHOT",
            {
                "case_count": 1,
                "loose_display_count": 2,
                "packs_remaining": 0,
                "cards_reopened": 0,
                "reason": "out_of_packaging",
                "employee_name": "Packer",
            },
            bag_id,
            station_id=1,
        )
        facts = _station_facts_payload(self.conn, bag_id, 1)
        self.assertFalse(facts["resume_required"])
        self.assertIsNone(facts["pause_details"])
        self.assertEqual((facts.get("hold_details") or {}).get("reason"), "out_of_packaging")
        self.assertTrue(
            _occupancy_lane_finished_at_station(
                self.conn,
                station_id=1,
                workflow_bag_id=bag_id,
                station_kind="packaging",
            )
        )

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
