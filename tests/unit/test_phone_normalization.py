"""Unit tests for country-aware phone normalization."""

import unittest

from geography import dial_code_for_country
from phone_utils import format_client_phone, format_to_e164


class TestPhoneNormalization(unittest.TestCase):
    def test_kenya_local_number(self):
        self.assertEqual(format_to_e164("0712345678"), "+254712345678")
        self.assertEqual(format_client_phone("0712345678", country="Kenya"), "+254712345678")

    def test_uganda_local_number(self):
        self.assertEqual(format_client_phone("0712345678", country="Uganda"), "+256712345678")

    def test_nigeria_local_number(self):
        self.assertEqual(format_client_phone("08031234567", country="Nigeria"), "+2348031234567")

    def test_explicit_international_preserved(self):
        self.assertEqual(format_to_e164("+256712345678"), "+256712345678")
        self.assertEqual(format_client_phone("+233201234567"), "+233201234567")

    def test_dial_code_for_country(self):
        self.assertEqual(dial_code_for_country("Kenya"), "+254")
        self.assertEqual(dial_code_for_country("Uganda"), "+256")
        self.assertEqual(dial_code_for_country("Nigeria"), "+234")
        self.assertEqual(dial_code_for_country(None), "+254")
        self.assertEqual(dial_code_for_country("Atlantis"), "+254")


if __name__ == "__main__":
    unittest.main()
