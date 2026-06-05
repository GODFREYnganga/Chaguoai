"""
Client-facing messages after a CHW and client choose a method.
"""

from __future__ import annotations

from typing import Any

from method_library import get_method_info


def compose_selection_message(
    *,
    client_name: str = "",
    method_name: str,
    referral: dict[str, Any] | None = None,
    next_followup: Any = None,
) -> str:
    info = get_method_info(method_name)
    greeting = f"Habari {client_name}," if client_name else "Habari,"
    lines = [
        greeting,
        f"You and your CHW selected: {info['display_name']}.",
        f"How it works: {info['how_it_works']}",
        f"How to use/start: {info['how_to_use']}",
        f"Common side effects: {info['common_side_effects']}",
        f"Warning signs: {info['warning_signs']}",
    ]

    if referral:
        facility = referral.get("facility_name")
        when = referral.get("appointment_at") or referral.get("appointment_text")
        referral_line = "Referral: please visit"
        if facility:
            referral_line += f" {facility}"
        if when:
            referral_line += f" ({when})"
        referral_line += "."
        lines.append(referral_line)

    if next_followup:
        lines.append(f"Follow-up: your CHW will check in around {next_followup}.")
    else:
        schedule = info.get("follow_up_schedule") or []
        if schedule:
            first = schedule[0]
            lines.append(f"Follow-up: your CHW will check in after about {first.get('days_after_start')} days.")

    lines.append("Reply with any concern, especially heavy bleeding, severe pain, chest pain, shortness of breath, or pregnancy concern.")
    return "\n\n".join(lines)


def compose_followup_reminder(*, client_name: str = "", method_name: str, reason: str) -> str:
    info = get_method_info(method_name)
    greeting = f"Habari {client_name}," if client_name else "Habari,"
    return (
        f"{greeting}\n\n"
        f"This is your ChaguoAI follow-up for {info['display_name']}.\n"
        f"Reason: {reason}\n\n"
        "How are you feeling with the method? Reply with any side effect, missed dose, bleeding concern, or question."
    )
