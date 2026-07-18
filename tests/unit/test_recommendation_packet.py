import unittest

from recommendation_packet import (
    build_recommendation_packet,
    build_methods_not_recommended,
    detect_missing_information,
)


MEC_TEXT = """
METHODS SAFE TO RECOMMEND (Category 1 or 2):
  - Implant — LNG (Jadelle/Sino-implant) (Category 1: No restriction)
  - Injectable DMPA (Category 2: Generally acceptable)

METHODS REQUIRING PROVIDER JUDGMENT (Category 3 — do not recommend directly):
  - Combined Oral Contraceptive: Hypertension

ABSOLUTELY CONTRAINDICATED (Category 4 — never recommend):
  - Combined Patch: Severe hypertension
"""


class TestRecommendationPacket(unittest.TestCase):
    def test_packet_has_required_sections_and_actions(self):
        packet = build_recommendation_packet(
            client={"name": "Joan", "age": 28, "health_conditions": "1", "prefer_not_to_use": "Pills"},
            recommendation_text="",
            mec_text=MEC_TEXT,
            citations=[{"id": "S1", "document": "Guideline"}],
        )
        self.assertIn("client_snapshot", packet)
        self.assertIn("risk_flags", packet)
        self.assertIn("recommended_methods", packet)
        self.assertGreaterEqual(len(packet["recommended_methods"]), 1)
        for method in packet["recommended_methods"]:
            self.assertEqual(
                method["actions"],
                ["ask_question", "view_side_effects", "confirm_client_choice", "refer", "send_instructions"],
            )
            self.assertIn("confidence", method)
            self.assertIn("confidence_reasons", method["confidence"])
        self.assertIn("confidence_reasons", packet["recommendation_confidence"])

    def test_missing_information_detection(self):
        missing = detect_missing_information({"age": 25})
        labels = {item["label"] for item in missing}
        self.assertIn("Smoking status unknown", labels)
        self.assertIn("Pregnancy status uncertain", labels)

    def test_methods_not_recommended(self):
        excluded = build_methods_not_recommended(MEC_TEXT)
        self.assertTrue(any(item["severity"] == "contraindicated" for item in excluded))
        self.assertTrue(any(item["mec_category"] == 3 for item in excluded))


if __name__ == "__main__":
    unittest.main()
