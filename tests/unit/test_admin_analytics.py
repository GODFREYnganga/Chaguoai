import unittest

from admin_analytics import build_admin_stats


class FakeDoc:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return dict(self._data)


class FakeCollection:
    def __init__(self, docs):
        self.docs = docs

    def stream(self):
        return iter(self.docs)

    def where(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self


class FakeDB:
    def __init__(self):
        self.users = FakeCollection([
            FakeDoc("+1", {"country": "Kenya", "registered_at": "2026-06-01T00:00:00+00:00"}),
            FakeDoc("+2", {"country": "Kenya", "registered_at": "2026-05-01T00:00:00+00:00"}),
            FakeDoc("+3", {"country": "Uganda", "registered_at": "2026-06-01T00:00:00+00:00"}),
        ])
        self.providers = FakeCollection([])
        self.empty = FakeCollection([])

    def collection(self, name):
        if name == "contraceptive_users":
            return self.users
        if name == "providers":
            return self.providers
        return self.empty

    def collection_group(self, name):
        return self.empty


class TestAdminAnalytics(unittest.TestCase):
    def test_geography_all_time_not_current_cohort_only(self):
        stats = build_admin_stats(
            FakeDB(),
            cohort="week",
            health={"overall": {"ok": True}},
        )
        self.assertEqual(stats["geography_all_time"]["by_country"]["Kenya"], 2)
        self.assertEqual(stats["geography_all_time"]["by_country"]["Uganda"], 1)
        self.assertEqual(stats["geography"]["by_country"]["Kenya"], 2)


if __name__ == "__main__":
    unittest.main()
