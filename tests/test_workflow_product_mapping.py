"""Deferred product mapping for tablet-first workflow bags."""

import sqlite3
import unittest

from app.services.workflow_product_mapping import ensure_workflow_bag_product_for_flow


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE tablet_types (
            id INTEGER PRIMARY KEY,
            tablet_type_name TEXT,
            category TEXT
        );
        CREATE TABLE product_details (
            id INTEGER PRIMARY KEY,
            product_name TEXT,
            tablet_type_id INTEGER,
            is_bottle_product INTEGER DEFAULT 0,
            is_variety_pack INTEGER DEFAULT 0,
            category TEXT
        );
        CREATE TABLE product_allowed_tablet_types (
            id INTEGER PRIMARY KEY,
            product_details_id INTEGER NOT NULL,
            tablet_type_id INTEGER NOT NULL
        );
        CREATE TABLE bags (
            id INTEGER PRIMARY KEY,
            tablet_type_id INTEGER
        );
        CREATE TABLE workflow_bags (
            id INTEGER PRIMARY KEY,
            product_id INTEGER,
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
        INSERT INTO tablet_types (id, tablet_type_name, category) VALUES (1, 'Blue Raz', 'Hyroxi');
        INSERT INTO bags (id, tablet_type_id) VALUES (10, 1);
        INSERT INTO workflow_bags (id, product_id, inventory_bag_id) VALUES (100, NULL, 10);
        """
    )
    return conn


class TestWorkflowProductMapping(unittest.TestCase):
    def test_single_card_product_auto_maps(self):
        conn = _conn()
        try:
            conn.execute(
                "INSERT INTO product_details (id, product_name, tablet_type_id) VALUES (20, 'Blue Raz Cards', 1)"
            )
            conn.execute(
                "INSERT INTO product_allowed_tablet_types (product_details_id, tablet_type_id) VALUES (20, 1)"
            )
            status, body = ensure_workflow_bag_product_for_flow(
                conn,
                workflow_bag_id=100,
                production_flow="card",
                station_id=5,
            )
            self.assertEqual(status, "ok")
            self.assertTrue(body["mapped"])
            row = conn.execute("SELECT product_id FROM workflow_bags WHERE id = 100").fetchone()
            self.assertEqual(row["product_id"], 20)
            ev = conn.execute("SELECT event_type FROM workflow_events").fetchall()
            self.assertEqual([r["event_type"] for r in ev], ["PRODUCT_MAPPED"])
        finally:
            conn.close()

    def test_bottle_flow_ignores_card_product(self):
        conn = _conn()
        try:
            conn.execute(
                "INSERT INTO product_details (id, product_name, tablet_type_id) VALUES (20, 'Blue Raz Cards', 1)"
            )
            conn.execute(
                "INSERT INTO product_allowed_tablet_types (product_details_id, tablet_type_id) VALUES (20, 1)"
            )
            status, body = ensure_workflow_bag_product_for_flow(
                conn,
                workflow_bag_id=100,
                production_flow="bottle",
            )
            self.assertEqual(status, "reject")
            self.assertEqual(body["reason"], "no_product_mapping")
        finally:
            conn.close()

    def test_ambiguous_card_products_require_selection(self):
        conn = _conn()
        try:
            for pid, name in [(20, "Blue Raz 1ct"), (21, "Blue Raz 4ct")]:
                conn.execute(
                    "INSERT INTO product_details (id, product_name, tablet_type_id) VALUES (?, ?, 1)",
                    (pid, name),
                )
                conn.execute(
                    "INSERT INTO product_allowed_tablet_types (product_details_id, tablet_type_id) VALUES (?, 1)",
                    (pid,),
                )
            status, body = ensure_workflow_bag_product_for_flow(
                conn,
                workflow_bag_id=100,
                production_flow="card",
            )
            self.assertEqual(status, "reject")
            self.assertEqual(body["reason"], "ambiguous_product_mapping")
            self.assertEqual([c["product_id"] for c in body["candidates"]], [20, 21])

            status2, body2 = ensure_workflow_bag_product_for_flow(
                conn,
                workflow_bag_id=100,
                production_flow="card",
                selected_product_id=21,
            )
            self.assertEqual(status2, "ok")
            self.assertEqual(body2["product_id"], 21)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
