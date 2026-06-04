import unittest

from analytics_service import build_model_training_event, discontinued_label
from model_adherence import map_client_to_model_profile, predict_method_adherence


class TestModelAdherence(unittest.TestCase):
    def test_maps_platform_fields_to_model_profile(self):
        profile = map_client_to_model_profile(
            {
                "country": "Kenya",
                "admin_area": "Siaya",
                "age": 22,
                "living_children": "1",
                "more_children": "2",
                "education_level": "Secondary & Above",
                "previous_method": "Injectables",
            },
            "Contraceptive implant",
        )
        self.assertEqual(profile["model_applicability"], "validated_geography")
        self.assertEqual(profile["candidate_method"], "Implants")
        self.assertEqual(profile["row"]["current_method_category"], "long_acting_reversible")
        self.assertEqual(profile["row"]["county"], "Siaya")

    def test_marks_out_of_distribution_geography(self):
        profile = map_client_to_model_profile({"country": "Kenya", "admin_area": "Nairobi"}, "Pills")
        self.assertEqual(profile["model_applicability"], "out_of_distribution")

    def test_predict_returns_unavailable_when_assets_missing(self):
        class Assets:
            loaded = False
            reason = "missing_artifacts:model"
            metadata = {"model_name": "lightgbm"}

        result = predict_method_adherence({"age": 25}, "Pills", assets=Assets())
        self.assertFalse(result["available"])
        self.assertEqual(result["adherence_risk_level"], "unknown")

    def test_discontinued_label_rules(self):
        self.assertEqual(discontinued_label("continuing"), 0)
        self.assertEqual(discontinued_label("switched"), 1)
        self.assertIsNone(discontinued_label("lost_to_followup"))

    def test_training_event_schema(self):
        event = build_model_training_event(
            phone="+254700000001",
            client={
                "country": "Kenya",
                "admin_area": "Siaya",
                "age": 30,
                "living_children": 2,
                "selected_method": "Contraceptive implant",
                "recommendation_packet": {"recommended_methods": [{"name": "Contraceptive implant"}]},
            },
            task={"id": "task-1", "status": "completed"},
            outcome={"outcome_type": "continuing", "continuation_status": "continuing"},
        )
        self.assertEqual(event["label_discontinued"], 0)
        self.assertEqual(event["label_status"], "labeled")
        self.assertEqual(event["confirmed_method"], "Contraceptive implant")
        self.assertEqual(event["recommended_methods"], ["Contraceptive implant"])


if __name__ == "__main__":
    unittest.main()
