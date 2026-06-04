import unittest

from method_selection import build_selection_client_message


class TestMethodSelection(unittest.TestCase):
    def test_selection_message_contains_method_and_followup(self):
        message = build_selection_client_message(
            client={"name": "Amina"},
            method_name="injectable",
            next_followup="2026-07-01",
        )
        self.assertIn("Amina", message)
        self.assertIn("Contraceptive injection", message)
        self.assertIn("2026-07-01", message)
        self.assertIn("Warning signs", message)

    def test_selection_message_contains_referral(self):
        message = build_selection_client_message(
            client={},
            method_name="implant",
            referral={"facility_name": "County Hospital"},
        )
        self.assertIn("County Hospital", message)
        self.assertIn("selected", message.lower())


if __name__ == "__main__":
    unittest.main()
