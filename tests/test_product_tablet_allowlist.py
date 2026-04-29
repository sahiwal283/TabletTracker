"""product_allowed_tablet_types and receipt chain helpers."""
import sqlite3
import unittest

from app.models.migrations import MigrationRunner
from app.services.product_tablet_allowlist import (
    allowed_tablet_type_ids_for_product,
    inventory_item_id_for_bag_tablet,
    product_allows_tablet_type,
    sync_product_allowed_tablets,
)
from app.services.receipt_product_chain import receipt_chain_key
from app.services.production_submission_helpers import ProductionSubmissionError
from app.services.receipt_product_chain import assert_receipt_product_chain


class TestReceiptChainKey(unittest.TestCase):
    def test_strips_workflow_suffixes(self):
        self.assertEqual(receipt_chain_key("PO-1-2-3-seal"), "PO-1-2-3")
        self.assertEqual(receipt_chain_key("PO-1-2-3-blister-e12"), "PO-1-2-3")
        self.assertEqual(receipt_chain_key("PO-1-2-3-pkg-e5"), "PO-1-2-3")
        self.assertEqual(receipt_chain_key("R-99"), "R-99")


class TestProductTabletAllowlist(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE tablet_types (
                id INTEGER PRIMARY KEY,
                tablet_type_name TEXT,
                inventory_item_id TEXT
            );
            CREATE TABLE product_details (
                id INTEGER PRIMARY KEY,
                product_name TEXT,
                tablet_type_id INTEGER,
                is_variety_pack INTEGER DEFAULT 0,
                variety_pack_contents TEXT
            );
            """
        )
        MigrationRunner(self.conn.cursor())._migrate_product_allowed_tablet_types()
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_sync_and_allowlist(self):
        self.conn.execute(
            "INSERT INTO tablet_types (id, tablet_type_name, inventory_item_id) VALUES (1, 'A', 'ia'), (2, 'B', 'ib')"
        )
        self.conn.execute(
            "INSERT INTO product_details (id, product_name, tablet_type_id) VALUES (10, 'Prod', 1)"
        )
        sync_product_allowed_tablets(
            self.conn,
            product_details_id=10,
            primary_tablet_type_id=1,
            extra_tablet_type_ids=[2],
        )
        self.conn.commit()
        self.assertEqual(allowed_tablet_type_ids_for_product(self.conn, 10), [1, 2])
        self.assertTrue(product_allows_tablet_type(self.conn, 10, 2))
        self.assertFalse(product_allows_tablet_type(self.conn, 10, 99))

    def test_inventory_item_id_for_bag(self):
        self.conn.execute("INSERT INTO tablet_types (id, inventory_item_id) VALUES (5, 'zoho-5')")
        self.conn.execute("CREATE TABLE bags (id INTEGER PRIMARY KEY, tablet_type_id INTEGER)")
        self.conn.execute("INSERT INTO bags (id, tablet_type_id) VALUES (100, 5)")
        self.conn.commit()
        self.assertEqual(inventory_item_id_for_bag_tablet(self.conn, 100), "zoho-5")

    def test_variety_pack_contents_allow_all_flavors(self):
        self.conn.execute(
            "INSERT INTO tablet_types (id, tablet_type_name, inventory_item_id) VALUES (1, 'A', 'ia'), (2, 'B', 'ib')"
        )
        self.conn.execute(
            """
            INSERT INTO product_details (id, product_name, tablet_type_id, is_variety_pack, variety_pack_contents)
            VALUES (20, 'Variety', NULL, 1, ?)
            """,
            ('[{"tablet_type_id": 2, "tablets_per_bottle": 5}, {"tablet_type_id": 1, "tablets_per_bottle": 5}]',),
        )
        self.conn.commit()
        self.assertEqual(allowed_tablet_type_ids_for_product(self.conn, 20), [2, 1])
        self.assertTrue(product_allows_tablet_type(self.conn, 20, 1))

    def test_assert_receipt_product_chain(self):
        self.conn.execute(
            "CREATE TABLE warehouse_submissions (id INTEGER PRIMARY KEY, receipt_number TEXT, product_name TEXT)"
        )
        self.conn.execute(
            "INSERT INTO warehouse_submissions (receipt_number, product_name) VALUES ('R-seal', 'Alpha')"
        )
        self.conn.commit()
        with self.assertRaises(ProductionSubmissionError):
            assert_receipt_product_chain(self.conn, receipt_number="R-blister", product_name="Beta")


if __name__ == "__main__":
    unittest.main()
