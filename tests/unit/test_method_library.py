import unittest
from datetime import datetime, timezone

from method_library import build_followup_dates, get_method_info, normalize_method_key


class TestMethodLibrary(unittest.TestCase):
    def test_alias_normalization(self):
        self.assertEqual(normalize_method_key("DMPA injection"), "injectable")
        self.assertEqual(normalize_method_key("Copper IUD"), "iud")

    def test_referral_required_for_implant(self):
        info = get_method_info("Jadelle implant")
        self.assertTrue(info["referral_required"])
        self.assertIn("trained provider", info["referral_reason"])

    def test_followup_dates(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        tasks = build_followup_dates("injectable", start)
        self.assertGreaterEqual(len(tasks), 2)
        self.assertEqual(tasks[0]["days_after_start"], 30)


if __name__ == "__main__":
    unittest.main()
