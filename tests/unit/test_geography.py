"""Unit tests for analytics-only geography normalization."""

import unittest

from geography import (
    MATCH_ALIAS,
    MATCH_EXACT,
    MATCH_FUZZY,
    MATCH_UNMATCHED,
    dial_code_for_country,
    normalize_country,
    normalize_admin_area,
    is_valid_location_input,
    strip_analytics_fields,
    admin_area_label,
)


class TestGeography(unittest.TestCase):
    def test_exact_country(self):
        r = normalize_country("Kenya")
        self.assertEqual(r.canonical, "Kenya")
        self.assertEqual(r.confidence, MATCH_EXACT)
        self.assertFalse(r.needs_confirmation)

    def test_alias(self):
        r = normalize_country("ivory coast")
        self.assertEqual(r.canonical, "Cote d'Ivoire")
        self.assertEqual(r.confidence, MATCH_ALIAS)

    def test_fuzzy_typo(self):
        r = normalize_country("keny")
        self.assertEqual(r.canonical, "Kenya")
        self.assertEqual(r.confidence, MATCH_FUZZY)
        self.assertTrue(r.needs_confirmation)

    def test_legacy_index(self):
        from geography import AFRICAN_COUNTRIES
        kenya_idx = str(AFRICAN_COUNTRIES.index("Kenya") + 1)
        r = normalize_country(kenya_idx)
        self.assertEqual(r.canonical, "Kenya")
        self.assertEqual(r.confidence, MATCH_EXACT)

    def test_unmatched(self):
        r = normalize_country("Atlantis")
        self.assertEqual(r.confidence, MATCH_UNMATCHED)

    def test_junk_invalid(self):
        self.assertFalse(is_valid_location_input("x"))

    def test_admin_area_title(self):
        self.assertEqual(normalize_admin_area("nairobi"), "Nairobi")

    def test_strip_analytics(self):
        data = {"age": 25, "country": "Kenya", "admin_area": "Nairobi"}
        clinical = strip_analytics_fields(data)
        self.assertNotIn("country", clinical)
        self.assertEqual(clinical["age"], 25)

    def test_admin_label_kenya(self):
        self.assertEqual(admin_area_label("Kenya"), "county")

    def test_dial_code_for_country(self):
        self.assertEqual(dial_code_for_country("Uganda"), "+256")
        self.assertEqual(dial_code_for_country("kenya"), "+254")


if __name__ == "__main__":
    unittest.main()
