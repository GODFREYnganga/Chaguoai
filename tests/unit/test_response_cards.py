import unittest

from response_cards import (
    build_fallback_method_cards,
    method_cards_to_text,
    parse_method_cards,
    response_has_method_cards,
)


class TestResponseCards(unittest.TestCase):
    def test_parse_rich_card(self):
        text = """[METHOD_CARD]
NAME: Contraceptive implant
CATEGORY: Implant
SUMMARY: Long acting option.
WHY_IT_FITS: MEC category 1.
HOW_IT_WORKS: Releases hormone.
HOW_TO_USE: Provider inserts it.
COMMON_SIDE_EFFECTS: Irregular bleeding.
DURATION_OR_REVISIT: Several years.
REFERRAL_REQUIRED: Yes
REFERRAL_REASON: Needs insertion.
FOLLOW_UP_SCHEDULE: Day 14, Day 90.
CITATIONS: S1, S2
[/METHOD_CARD]"""
        cards = parse_method_cards(text)
        self.assertTrue(response_has_method_cards(text))
        self.assertEqual(cards[0]["name"], "Contraceptive implant")
        self.assertEqual(cards[0]["category"], "Implant")
        self.assertTrue(cards[0]["referral_required"])
        self.assertIn("S1", cards[0]["citations"])

    def test_fallback_cards_from_mec_text(self):
        mec = """METHODS SAFE TO RECOMMEND (Category 1 or 2)
- LNG-IUD (Hormonal IUD / Mirena) (Category 1: No restriction)
- Implant — LNG (Jadelle/Sino-implant) (Category 1: No restriction)

METHODS REQUIRING PROVIDER JUDGMENT"""
        cards = build_fallback_method_cards(mec_text=mec, citations=[{"id": "S1"}])
        text = method_cards_to_text(cards, [{"id": "S1", "document": "Guideline"}])
        self.assertGreaterEqual(len(cards), 2)
        self.assertTrue(response_has_method_cards(text))
        self.assertTrue(cards[0]["referral_required"])


if __name__ == "__main__":
    unittest.main()
