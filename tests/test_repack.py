"""
Unit tests for repack (tablet search) calculator and bag sort/allocation helpers.
"""
import unittest

from app.services.submission_calculator import calculate_repack_output_good
from app.services.repack_allocation_service import sort_bags_for_repack, allocate_repack_tablets


class TestRepackCalculator(unittest.TestCase):
    def test_output_good_displays_and_packs(self):
        sub = {"displays_made": 2, "packs_remaining": 3}
        self.assertEqual(calculate_repack_output_good(sub, 10, 12), 2 * 10 * 12 + 3 * 12)

    def test_output_good_ignores_loose_and_damaged_keys(self):
        sub = {
            "displays_made": 1,
            "packs_remaining": 0,
            "loose_tablets": 99,
            "cards_reopened": 50,
        }
        self.assertEqual(calculate_repack_output_good(sub, 5, 8), 5 * 8)


class TestRepackAllocation(unittest.TestCase):
    def test_sort_bags_damage_then_capacity_desc(self):
        bags = [
            {"bag_id": 1, "damage_metric": 0, "remaining_capacity": 100},
            {"bag_id": 2, "damage_metric": 5, "remaining_capacity": 50},
            {"bag_id": 3, "damage_metric": 5, "remaining_capacity": 200},
        ]
        ordered = sort_bags_for_repack(bags)
        self.assertEqual([b["bag_id"] for b in ordered], [3, 2, 1])

    def test_allocate_water_fills_ordered_bags(self):
        class Conn:
            def execute(self, *args, **kwargs):
                raise AssertionError("allocate_repack_tablets should not query when bags list is empty")

        bags = [
            {
                "bag_id": 10,
                "damage_metric": 0,
                "remaining_capacity": 25,
                "box_number": 1,
                "bag_number": 2,
                "receive_name": "PO-1-1",
            },
            {
                "bag_id": 11,
                "damage_metric": 0,
                "remaining_capacity": 30,
                "box_number": 1,
                "bag_number": 3,
                "receive_name": "PO-1-1",
            },
        ]

        def fake_load(conn, po_id, tablet_type_id):
            self.assertEqual(po_id, 99)
            self.assertEqual(tablet_type_id, 7)
            return bags

        import app.services.repack_allocation_service as ras

        orig = ras.load_bags_for_po_flavor
        ras.load_bags_for_po_flavor = fake_load
        try:
            payload, needs = allocate_repack_tablets(Conn(), 99, 7, 45)
        finally:
            ras.load_bags_for_po_flavor = orig

        self.assertFalse(needs)
        self.assertEqual(payload["overflow_tablets"], 0)
        allocs = [a for a in payload["allocations"] if not a.get("overflow")]
        # Same damage → larger remaining_capacity first: bag 11 takes 30, bag 10 takes 15.
        self.assertEqual(len(allocs), 2)
        self.assertEqual(allocs[0]["bag_id"], 11)
        self.assertEqual(allocs[0]["tablets"], 30)
        self.assertEqual(allocs[1]["bag_id"], 10)
        self.assertEqual(allocs[1]["tablets"], 15)

    def test_allocate_overflow_needs_review(self):
        class Conn:
            def execute(self, *args, **kwargs):
                raise AssertionError("unexpected query")

        bags = [
            {
                "bag_id": 20,
                "damage_metric": 0,
                "remaining_capacity": 10,
                "box_number": 1,
                "bag_number": 1,
                "receive_name": "X",
            },
        ]

        import app.services.repack_allocation_service as ras

        orig = ras.load_bags_for_po_flavor
        ras.load_bags_for_po_flavor = lambda c, p, t: bags
        try:
            payload, needs = allocate_repack_tablets(Conn(), 1, 1, 25)
        finally:
            ras.load_bags_for_po_flavor = orig

        self.assertTrue(needs)
        self.assertEqual(payload["overflow_tablets"], 15)
        overflow_rows = [a for a in payload["allocations"] if a.get("overflow")]
        self.assertEqual(len(overflow_rows), 1)
        self.assertEqual(overflow_rows[0]["tablets"], 15)


if __name__ == "__main__":
    unittest.main()
