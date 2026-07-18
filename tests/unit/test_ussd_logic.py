"""Unit tests for USSD state machine (no live Redis/Gemini)."""

import sys
import unittest
from unittest.mock import MagicMock, patch

if "firebase_admin" not in sys.modules:
    _mock_firestore = MagicMock()
    _mock_firestore.SERVER_TIMESTAMP = "SERVER_TIMESTAMP"
    _mock_fb = MagicMock()
    _mock_fb.firestore = _mock_firestore
    sys.modules["firebase_admin"] = _mock_fb

from ussd_logic import (
    LANG_BY_CHOICE,
    _finish_method_match,
    _resolve_lang_choice,
    handle_ussd_request,
    process_method_match,
)
from ussd_strings import ussd_text


class _FakeDoc:
    def __init__(self, data=None, exists=True):
        self._data = data or {}
        self.exists = exists

    def to_dict(self):
        return dict(self._data)


class _FakeCollection:
    def __init__(self, store: dict, path: str = ""):
        self._store = store
        self._path = path

    def document(self, doc_id: str):
        key = f"{self._path}/{doc_id}".strip("/")
        return _FakeDocumentRef(self._store, key)

    def add(self, payload):
        self._store.setdefault(self._path, []).append(payload)


class _FakeDocumentRef:
    def __init__(self, store: dict, key: str):
        self._store = store
        self._key = key

    def get(self):
        data = self._store.get(self._key)
        if data is None:
            return _FakeDoc(exists=False)
        return _FakeDoc(data=data, exists=True)

    def set(self, payload, merge=False):
        if merge and self._key in self._store:
            current = dict(self._store[self._key])
            current.update(payload)
            self._store[self._key] = current
        else:
            self._store[self._key] = dict(payload)

    def collection(self, name: str):
        return _FakeCollection(self._store, f"{self._key}/{name}")


class _FakeDB:
    def __init__(self):
        self._store = {}

    def collection(self, name: str):
        return _FakeCollection(self._store, name)


def _full_method_match_answers():
    """Geo + 13 clinical answers (minimal valid path, no q3a/q9a branches)."""
    return [
        "Kenya",
        "Nairobi",
        "25",
        "1",
        "2",
        "0",
        "3",
        "7",
        "2",
        "2",
        "2",
        "1",
        "1",
        "2",
        "2",
        "5",
    ]


class TestUssdStrings(unittest.TestCase):
    def test_four_languages_supported(self):
        self.assertEqual(len(LANG_BY_CHOICE), 4)
        for lang in LANG_BY_CHOICE.values():
            self.assertTrue(ussd_text(lang, "welcome").startswith("CON"))

    def test_resolve_lang_choice(self):
        self.assertEqual(_resolve_lang_choice("3"), "french")
        self.assertEqual(_resolve_lang_choice("4"), "portuguese")
        self.assertIsNone(_resolve_lang_choice("9"))


class TestUssdHandleRequest(unittest.TestCase):
    def setUp(self):
        self.db = _FakeDB()
        self.phone = "+254700000099"

    def test_language_menu_on_first_dial(self):
        resp = handle_ussd_request("s1", "*123#", self.phone, "", db=self.db)
        self.assertIn("Francais", resp)
        self.assertIn("Portuguese", resp)

    def test_language_selection_english(self):
        resp = handle_ussd_request("s1", "*123#", self.phone, "1", db=self.db)
        self.assertIn("Method Match", resp)

    def test_language_selection_french(self):
        resp = handle_ussd_request("s1", "*123#", self.phone, "3", db=self.db)
        self.assertIn("Effets secondaires", resp)

    @patch("ussd_logic._enqueue_ussd_method_match", return_value=True)
    def test_method_match_queues_on_completion(self, mock_enqueue):
        self.db._store[f"contraceptive_users/{self.phone}"] = {"language": "english"}
        text = "1*" + "*".join(_full_method_match_answers())
        resp = handle_ussd_request("s1", "*123#", self.phone, text, db=self.db)
        self.assertTrue(resp.startswith("END"))
        self.assertIn("being prepared", resp)
        mock_enqueue.assert_called_once()

    def test_check_method_still_processing(self):
        self.db._store[f"contraceptive_users/{self.phone}"] = {
            "language": "english",
            "method_match_status": "queued",
            "method_match_pending": True,
        }
        resp = handle_ussd_request("s1", "*123#", self.phone, "3", db=self.db)
        self.assertIn("still being prepared", resp)

    def test_check_method_shows_completed_match(self):
        self.db._store[f"contraceptive_users/{self.phone}"] = {
            "language": "english",
            "method_match_status": "completed",
            "matched_method": "Safe options: Implant, Pills",
        }
        resp = handle_ussd_request("s1", "*123#", self.phone, "3", db=self.db)
        self.assertIn("Implant", resp)

    def test_invalid_menu_choice(self):
        self.db._store[f"contraceptive_users/{self.phone}"] = {"language": "english"}
        resp = handle_ussd_request("s1", "*123#", self.phone, "9", db=self.db)
        self.assertIn("Invalid", resp)


class TestUssdFinishMethodMatch(unittest.TestCase):
    @patch("ussd_logic._enqueue_ussd_method_match", return_value=True)
    def test_finish_sets_queued_status(self, _mock_enqueue):
        db = _FakeDB()
        phone = "+254711111111"
        responses = {
            "age": "30",
            "country": "Kenya",
            "country_raw": "Kenya",
            "country_match_confidence": "exact",
            "admin_area": "Nairobi",
            "admin_area_raw": "Nairobi",
            "admin_area_type": "county",
            "prefer_not": "5",
        }
        resp = _finish_method_match(phone, "swahili", responses, db)
        self.assertIn("hifadhiwa", resp.lower())
        stored = db._store.get(f"contraceptive_users/{phone}", {})
        self.assertEqual(stored.get("method_match_status"), "queued")

    @patch("ussd_logic._enqueue_ussd_method_match", return_value=False)
    def test_finish_fast_mec_when_no_redis(self, _mock_enqueue):
        import types

        db = _FakeDB()
        phone = "+254722222222"
        responses = {
            "age": "28",
            "country": "Kenya",
            "country_raw": "Kenya",
            "country_match_confidence": "exact",
            "admin_area": "Nairobi",
            "admin_area_raw": "Nairobi",
            "admin_area_type": "county",
            "prefer_not": "5",
        }
        fake_cp = types.SimpleNamespace(
            generate_ussd_fast_mec_summary=MagicMock(return_value=("Safe options: Pills", "mec"))
        )
        fake_mc = types.SimpleNamespace(
            classify_method_category_primary=MagicMock(return_value="pills")
        )
        with patch.dict(sys.modules, {"clinical_pipeline": fake_cp, "method_categories": fake_mc}):
            resp = _finish_method_match(phone, "english", responses, db)
        self.assertIn("Safe options", resp)
        stored = db._store.get(f"contraceptive_users/{phone}", {})
        self.assertEqual(stored.get("method_match_status"), "completed")


if __name__ == "__main__":
    unittest.main()
