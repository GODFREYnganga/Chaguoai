import unittest
from datetime import datetime, timedelta, timezone

from care_plan import (
    build_client_timeline,
    transition_for_followup_sent,
    transition_for_no_response,
    transition_for_outcome,
)


class TestCarePlan(unittest.TestCase):
    def test_followup_sent_transition_sets_response_deadline(self):
        sent_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        update = transition_for_followup_sent("task-1", sent_at)
        self.assertEqual(update["care_plan_status"], "awaiting_response")
        self.assertEqual(update["active_followup_task_id"], "task-1")
        self.assertEqual(update["response_due_at"], sent_at + timedelta(hours=48))

    def test_no_response_transition_escalates(self):
        update = transition_for_no_response(2)
        self.assertEqual(update["care_plan_status"], "needs_chw_attention")
        self.assertEqual(update["no_response_count"], 3)

    def test_outcome_transition_maps_stopped(self):
        update = transition_for_outcome("stopped")
        self.assertEqual(update["care_plan_status"], "stopped")

    def test_timeline_is_client_centered(self):
        timeline = build_client_timeline(
            client={
                "triage_completed_at": "2026-01-01T00:00:00Z",
                "matched_method": "Implant",
                "selected_method": "Contraceptive implant",
                "selected_method_selected_at": "2026-01-02T00:00:00Z",
            },
            followups=[{"id": "f1", "status": "sent", "sent_at": "2026-01-03T00:00:00Z", "reason": "Check-in"}],
            side_effects=[{"at": "2026-01-04T00:00:00Z", "report": "spotting"}],
        )
        labels = [item["label"] for item in timeline]
        self.assertIn("Method Match completed", labels)
        self.assertIn("Client chose Contraceptive implant", labels)
        self.assertIn("Follow-up sent", labels)
        self.assertIn("Side effect reported", labels)


if __name__ == "__main__":
    unittest.main()
