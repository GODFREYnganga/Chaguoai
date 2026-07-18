"""Unit tests for profile-grounded WhatsApp chat helpers."""

import unittest

from whatsapp_chat_utils import (
    build_chat_clarification_reply,
    is_vague_chat_question,
    user_has_clinical_profile,
)


class TestWhatsappChatProfile(unittest.TestCase):
    def test_profile_detected_after_method_match(self):
        user = {
            "stage": "MAIN_MENU",
            "method_match_status": "completed",
            "matched_method": "Implant is a good fit",
            "age": 28,
        }
        self.assertTrue(user_has_clinical_profile(user))

    def test_profile_not_detected_for_new_user(self):
        self.assertFalse(user_has_clinical_profile({"stage": "AWAITING_Q1_NAME"}))

    def test_vague_question_detection(self):
        self.assertTrue(is_vague_chat_question("help"))
        self.assertTrue(is_vague_chat_question("I have a question"))
        self.assertFalse(is_vague_chat_question("Can the implant cause heavy bleeding?"))

    def test_clarification_mentions_recommendation(self):
        reply = build_chat_clarification_reply(
            {"name": "Amina", "matched_method": "*Implant* is recommended"},
            "english",
        )
        self.assertIn("Implant", reply)
        self.assertIn("Amina", reply)


if __name__ == "__main__":
    unittest.main()
