"""Tests for bag stage-yield (running totals) and aggregate reporting."""
import sqlite3
import unittest

from app.services.bag_check_totals import compute_bag_check_totals
from app.services.reporting_analytics_service import aggregate_stage_yield


class TestBagStageYield(unittest.TestCase):
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
                tablets_per_package INTEGER
            );
            CREATE TABLE purchase_orders (id INTEGER PRIMARY KEY);
            CREATE TABLE receiving (id INTEGER PRIMARY KEY, po_id INTEGER);
            CREATE TABLE small_boxes (id INTEGER PRIMARY KEY, receiving_id INTEGER, box_number INTEGER);
            CREATE TABLE bags (
                id INTEGER PRIMARY KEY,
                small_box_id INTEGER,
                tablet_type_id INTEGER,
                bag_number INTEGER,
                bag_label_count INTEGER,
                pill_count INTEGER
            );
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
                receipt_number TEXT,
                displays_made INTEGER,
                packs_remaining INTEGER,
                tablets_pressed_into_cards INTEGER,
                loose_tablets INTEGER,
                machine_id INTEGER,
                created_at TEXT
            );
            """
        )
        self.conn.execute("INSERT INTO purchase_orders (id) VALUES (55)")
        self.conn.execute("INSERT INTO tablet_types (id, inventory_item_id) VALUES (1, 'INV-1')")
        self.conn.execute(
            "INSERT INTO product_details (id, tablet_type_id, product_name, packages_per_display, tablets_per_package) "
            "VALUES (1, 1, 'Prod A', 5, 4)"
        )
        self.conn.execute("INSERT INTO receiving (id, po_id) VALUES (1, 55)")
        self.conn.execute("INSERT INTO small_boxes (id, receiving_id, box_number) VALUES (1, 1, 3)")
        self.conn.execute(
            "INSERT INTO bags (id, small_box_id, tablet_type_id, bag_number, bag_label_count, pill_count) "
            "VALUES (1, 1, 1, 2, 10000, 10000)"
        )
        # Blister: 1 cut -> 2 blisters * 4 tpp = 8; 10 cards sealed * 4 = 40; packaged 1 display *5*4 = 20 (so seal > pack, no anomaly)
        self.conn.execute("INSERT INTO machines (id, machine_name, machine_role) VALUES (10, 'DPP', 'blister')")
        self.conn.execute("INSERT INTO machines (id, machine_name, machine_role) VALUES (20, 'Seal1', 'sealing')")
        self.conn.execute(
            "INSERT INTO warehouse_submissions (id, bag_id, inventory_item_id, bag_number, box_number, assigned_po_id, "
            "submission_type, product_name, displays_made, packs_remaining, machine_id, created_at) "
            "VALUES (1, 1, 'INV-1', 2, 3, 55, 'machine', 'Prod A', 1, 0, 10, '2026-04-22 10:00:00')"
        )
        self.conn.execute(
            "INSERT INTO warehouse_submissions (id, bag_id, inventory_item_id, bag_number, box_number, assigned_po_id, "
            "submission_type, product_name, displays_made, packs_remaining, machine_id, created_at) "
            "VALUES (2, 1, 'INV-1', 2, 3, 55, 'machine', 'Prod A', 0, 10, 20, '2026-04-22 10:10:00')"
        )
        self.conn.execute(
            "INSERT INTO warehouse_submissions (id, bag_id, inventory_item_id, bag_number, box_number, assigned_po_id, "
            "submission_type, product_name, displays_made, packs_remaining, loose_tablets, created_at) "
            "VALUES (3, 1, 'INV-1', 2, 3, 55, 'packaged', 'Prod A', 1, 0, 0, '2026-04-22 10:20:00')"
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_compute_bag_stage_yields(self):
        m = compute_bag_check_totals(self.conn, 1)
        self.assertEqual(m["blisters_from_blister_counter"], 2)
        self.assertEqual(m["cards_from_sealing_counter"], 10)
        # 1 display * 5 = 5 cards packed
        self.assertEqual(m["cards_in_packaged_output"], 5)
        self.assertEqual(m["machine_blister_tablets_total"], 8)
        self.assertEqual(m["machine_sealing_tablets_total"], 40)
        self.assertEqual(m["packaged_tablets_total"], 20)
        self.assertTrue(m["pipeline_stages_present"]["blisters"])
        self.assertTrue(m["pipeline_stages_present"]["sealing"])
        self.assertTrue(m["pipeline_stages_present"]["packaged"])
        self.assertIsNotNone(m["stage_transition_losses_tablets"]["sealing_to_packaged"])
        self.assertIsNotNone(m["stage_transition_losses_cards"]["sealing_to_packaged"])
        # primary machine ids
        self.assertEqual(m["primary_blister_machine_id"], 10)
        self.assertEqual(m["primary_sealing_machine_id"], 20)

    def test_aggregate_stage_yield_in_window(self):
        out = aggregate_stage_yield(
            self.conn, "2026-04-20", "2026-04-30", tablet_type_id=1, machine_id=None
        )
        self.assertTrue(out["success"])
        t = out["tablets"]["sealing_to_packaged"]
        self.assertEqual(t["n"], 1)
        self.assertIsNotNone(t["weighted_mean"])


if __name__ == "__main__":
    unittest.main()
