"""Unit tests for Zoho item weight parsing (no network)."""
import unittest

from app.services.zoho_service import parse_zoho_item_weight_grams


class TestParseZohoItemWeightGrams(unittest.TestCase):
    def test_top_level_grams(self):
        self.assertAlmostEqual(
            parse_zoho_item_weight_grams({'item': {'weight': '0.51', 'weight_unit': 'g'}}),
            0.51,
        )

    def test_package_details_fallback(self):
        """Zoho UI/API often stores weight under package_details."""
        self.assertAlmostEqual(
            parse_zoho_item_weight_grams(
                {'item': {'name': 'X', 'package_details': {'weight': 0.51, 'weight_unit': 'g'}}}
            ),
            0.51,
        )

    def test_package_details_overrides_empty_top_weight(self):
        self.assertAlmostEqual(
            parse_zoho_item_weight_grams(
                {'item': {'weight': '', 'package_details': {'weight': '1', 'weight_unit': 'kg'}}}
            ),
            1000.0,
        )

    def test_missing_weight(self):
        self.assertIsNone(parse_zoho_item_weight_grams({'item': {}}))
        self.assertIsNone(parse_zoho_item_weight_grams({'item': {'package_details': {}}}))


if __name__ == '__main__':
    unittest.main()
