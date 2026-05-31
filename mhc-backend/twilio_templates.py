"""
Twilio WhatsApp Content Template registry.

Twilio requires separate approved templates for each button/list row count.
A 3-button quick-reply template FAILS when you only send 2 options — which is
why Q3/Q8/Q9/Q12 (Yes/No) had no buttons while Q5 (3 options) worked.

Configure one SID per size in .env (see mhc-docs/twilio_content_templates.md).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class TwilioTemplateRegistry:
    quick_reply_2: str | None = None
    quick_reply_3: str | None = None
    list_picker_4: str | None = None
    list_picker_5: str | None = None
    list_picker_7: str | None = None
    # Legacy single-SID fallbacks (may not work for all question sizes)
    quick_reply_legacy: str | None = None
    list_picker_legacy: str | None = None

    @classmethod
    def from_env(cls) -> "TwilioTemplateRegistry":
        return cls(
            quick_reply_2=os.environ.get("TWILIO_CONTENT_QUICK_REPLY_2_SID"),
            quick_reply_3=os.environ.get("TWILIO_CONTENT_QUICK_REPLY_3_SID")
            or os.environ.get("TWILIO_CONTENT_QUICK_REPLY_SID"),
            list_picker_4=os.environ.get("TWILIO_CONTENT_LIST_PICKER_4_SID"),
            list_picker_5=os.environ.get("TWILIO_CONTENT_LIST_PICKER_5_SID")
            or os.environ.get("TWILIO_CONTENT_LIST_PICKER_SID"),
            list_picker_7=os.environ.get("TWILIO_CONTENT_LIST_PICKER_7_SID"),
            quick_reply_legacy=os.environ.get("TWILIO_CONTENT_QUICK_REPLY_SID"),
            list_picker_legacy=os.environ.get("TWILIO_CONTENT_LIST_PICKER_SID"),
        )

    def resolve(self, option_count: int) -> tuple[str | None, str, int]:
        """
        Pick the best Content SID for a given number of options.

        Returns (content_sid, mode, template_slots) where mode is
        'quick_reply' or 'list_picker', and template_slots is how many
        option rows the template expects (must match variables sent).
        """
        count = max(1, min(int(option_count), 10))

        if count == 2 and self.quick_reply_2:
            return self.quick_reply_2, "quick_reply", 2
        if count == 3 and self.quick_reply_3:
            return self.quick_reply_3, "quick_reply", 3
        if count == 4 and self.list_picker_4:
            return self.list_picker_4, "list_picker", 4
        if count == 5 and self.list_picker_5:
            return self.list_picker_5, "list_picker", 5
        if count in (6, 7) and self.list_picker_7:
            return self.list_picker_7, "list_picker", 7

        # Fallbacks — may fail if slot count does not match; logged at send time
        if count <= 3 and self.quick_reply_legacy:
            return self.quick_reply_legacy, "quick_reply", 3
        if self.list_picker_legacy:
            slots = {4: 4, 5: 5, 6: 7, 7: 7}.get(count, count)
            return self.list_picker_legacy, "list_picker", slots

        return None, "list_picker", count

    def status_report(self) -> dict[str, str]:
        return {
            "quick_reply_2": "set" if self.quick_reply_2 else "missing",
            "quick_reply_3": "set" if self.quick_reply_3 else "missing",
            "list_picker_4": "set" if self.list_picker_4 else "missing",
            "list_picker_5": "set" if self.list_picker_5 else "missing",
            "list_picker_7": "set" if self.list_picker_7 else "missing",
        }

    def missing_for_survey(self) -> list[str]:
        """Templates required for the full Method Match + menu flow."""
        required = []
        if not self.quick_reply_2:
            required.append("TWILIO_CONTENT_QUICK_REPLY_2_SID (Q3, Q8, Q9, Q12 Yes/No)")
        if not self.quick_reply_3:
            required.append("TWILIO_CONTENT_QUICK_REPLY_3_SID (Q2, Q5, Q7, Q10, Q11)")
        if not self.list_picker_4:
            required.append("TWILIO_CONTENT_LIST_PICKER_4_SID (Q4 children, language menu, Q9a)")
        if not self.list_picker_5:
            required.append("TWILIO_CONTENT_LIST_PICKER_5_SID (main menu, Q13 methods)")
        if not self.list_picker_7:
            required.append("TWILIO_CONTENT_LIST_PICKER_7_SID (Q6 health conditions)")
        return required
