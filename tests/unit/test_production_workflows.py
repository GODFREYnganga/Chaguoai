import unittest
from uuid import uuid4

from analytics_service import build_analytics_summary, record_analytics_event
from audit_trail import fetch_audit_trail, record_audit_event
from method_selection import (
    create_referral,
    record_followup_outcome,
    select_method,
    update_referral_status,
)


class FakeSnap:
    def __init__(self, ref):
        self.reference = ref
        self.id = ref.id
        self.exists = ref.data is not None

    def to_dict(self):
        return dict(self.reference.data or {})


class FakeDoc:
    def __init__(self, id):
        self.id = id
        self.data = None
        self.children = {}

    def get(self):
        return FakeSnap(self)

    def set(self, data, merge=False):
        if merge and self.data:
            self.data.update(data)
        else:
            self.data = dict(data)

    def update(self, data):
        self.set(data, merge=True)

    def collection(self, name):
        self.children.setdefault(name, FakeCollection())
        return self.children[name]


class FakeCollection:
    def __init__(self):
        self.docs = {}

    def document(self, id=None):
        id = id or str(uuid4())
        self.docs.setdefault(id, FakeDoc(id))
        return self.docs[id]

    def add(self, data):
        doc = self.document()
        doc.set(data)
        return doc

    def stream(self):
        return [doc.get() for doc in self.docs.values()]

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self


class FakeDb:
    def __init__(self):
        self.collections = {}

    def collection(self, name):
        self.collections.setdefault(name, FakeCollection())
        return self.collections[name]


class TestProductionWorkflows(unittest.TestCase):
    def setUp(self):
        self.db = FakeDb()
        self.phone = "+254700000001"
        self.provider = "provider-1"
        self.client_ref = self.db.collection("contraceptive_users").document(self.phone)
        self.client_ref.set({
            "assigned_provider_id": self.provider,
            "name": "Amina",
            "recommendation_packet": {
                "recommended_methods": [{"name": "Contraceptive implant"}],
                "methods_not_recommended": [
                    {
                        "method_name": "Combined Patch",
                        "mec_category": 4,
                        "severity": "contraindicated",
                        "reason": "Severe hypertension",
                    }
                ],
            },
            "method_cards": [{"name": "Contraceptive implant"}],
        })

    def test_referral_lifecycle_records_status(self):
        referral = create_referral(
            db=self.db,
            phone=self.phone,
            provider_id=self.provider,
            method_name="Contraceptive implant",
            referral={"facility_name": "County Hospital", "referral_reason": "Requires insertion"},
        )
        self.assertEqual(referral["status"], "pending")
        updated = update_referral_status(
            db=self.db,
            phone=self.phone,
            provider_id=self.provider,
            referral_id=referral["id"],
            status="completed",
        )
        self.assertEqual(updated["status"], "completed")

    def test_structured_outcome_is_recorded(self):
        task = self.db.collection("followup_tasks").document("task-1")
        task.set({"phone": self.phone, "provider_id": self.provider, "method": "Implant", "status": "sent"})
        result = record_followup_outcome(
            db=self.db,
            task_id="task-1",
            provider_id=self.provider,
            outcome="switched",
            structured_outcome={"outcome_type": "switched", "switched_to_method": "Injectable"},
        )
        self.assertEqual(result["structured_outcome"]["outcome_type"], "switched")
        self.assertEqual(result["structured_outcome"]["switched_to_method"], "Injectable")

    def test_audit_trail_records_events(self):
        record_audit_event(db=self.db, phone=self.phone, actor=self.provider, action="outcome_recorded", metadata={"x": 1})
        events = fetch_audit_trail(db=self.db, phone=self.phone)
        self.assertEqual(events[0]["action"], "outcome_recorded")

    def test_analytics_summary_counts_events(self):
        record_analytics_event(self.db, "method_selected", {"provider_id": self.provider, "method": "Implant"})
        record_analytics_event(self.db, "referral_created", {"provider_id": self.provider, "facility_name": "Clinic"})
        summary = build_analytics_summary(self.db, provider_id=self.provider)
        self.assertEqual(summary["event_counts"]["method_selected"], 1)
        self.assertEqual(summary["method_selection_rates"]["Implant"], 1)

    def test_provider_override_requires_reason(self):
        with self.assertRaisesRegex(ValueError, "Clinical Override Required"):
            select_method(
                db=self.db,
                phone=self.phone,
                provider_id=self.provider,
                method_name="Combined Patch",
            )

    def test_safety_override_requires_acknowledgment(self):
        with self.assertRaisesRegex(ValueError, "High-Risk Clinical Decision"):
            select_method(
                db=self.db,
                phone=self.phone,
                provider_id=self.provider,
                method_name="Combined Patch",
                override_reason="Client preference",
            )


if __name__ == "__main__":
    unittest.main()
