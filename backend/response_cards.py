"""
Parse and validate [METHOD_CARD] blocks returned by the clinical LLM.

The frontend renders cards, but backend parsing is needed for method selection,
tests, and storing structured options with citations.
"""

from __future__ import annotations

import re
from typing import Any

from method_library import get_method_info

CARD_RE = re.compile(r"\[\s*METHOD_CARD\s*\]([\s\S]*?)\[\s*\/\s*METHOD_CARD\s*\]", re.IGNORECASE)

CARD_FIELDS = [
    "NAME",
    "CATEGORY",
    "SUMMARY",
    "WHY_IT_FITS",
    "HOW_IT_WORKS",
    "HOW_TO_USE",
    "COMMON_SIDE_EFFECTS",
    "DURATION_OR_REVISIT",
    "REFERRAL_REQUIRED",
    "REFERRAL_REASON",
    "FOLLOW_UP_SCHEDULE",
    "CITATIONS",
    # Backward compatibility with previous prompt.
    "DETAILS",
]


def parse_card_field(content: str, field: str) -> str:
    fields_pattern = "|".join(re.escape(f) for f in CARD_FIELDS)
    match = re.search(
        rf"(?:^|\n)\s*{re.escape(field)}\s*:\s*([\s\S]*?)(?=\n\s*(?:{fields_pattern})\s*:|\Z)",
        content,
        re.IGNORECASE,
    )
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1).strip())


def parse_bool(value: str) -> bool:
    return str(value or "").strip().lower() in {"true", "yes", "y", "1", "required"}


def parse_method_cards(text: str) -> list[dict[str, Any]]:
    cards = []
    for idx, match in enumerate(CARD_RE.finditer(str(text or "")), start=1):
        content = match.group(1).strip()
        name = parse_card_field(content, "NAME") or f"Method option {idx}"
        library = get_method_info(name)
        details = parse_card_field(content, "DETAILS")
        card = {
            "index": idx,
            "name": name,
            "category": parse_card_field(content, "CATEGORY") or library.get("category") or name,
            "summary": parse_card_field(content, "SUMMARY") or details or library.get("how_it_works", ""),
            "why_it_fits": parse_card_field(content, "WHY_IT_FITS") or details,
            "how_it_works": parse_card_field(content, "HOW_IT_WORKS") or library.get("how_it_works", ""),
            "how_to_use": parse_card_field(content, "HOW_TO_USE") or library.get("how_to_use", ""),
            "common_side_effects": parse_card_field(content, "COMMON_SIDE_EFFECTS") or library.get("common_side_effects", ""),
            "duration_or_revisit": parse_card_field(content, "DURATION_OR_REVISIT") or library.get("duration_or_revisit", ""),
            "referral_required": parse_bool(parse_card_field(content, "REFERRAL_REQUIRED")) or bool(library.get("referral_required")),
            "referral_reason": parse_card_field(content, "REFERRAL_REASON") or library.get("referral_reason", ""),
            "follow_up_schedule": parse_card_field(content, "FOLLOW_UP_SCHEDULE") or _library_followup_text(library),
            "citations": parse_card_field(content, "CITATIONS"),
            "library": library,
        }
        cards.append(card)
    return cards


def _library_followup_text(library: dict[str, Any]) -> str:
    parts = []
    for item in library.get("follow_up_schedule", []):
        days = item.get("days_after_start")
        reason = item.get("reason", "Follow-up support")
        parts.append(f"Day {days}: {reason}")
    return "; ".join(parts)


def response_has_method_cards(text: str) -> bool:
    return bool(CARD_RE.search(str(text or "")))


def extract_safe_method_names(mec_text: str, limit: int = 3) -> list[str]:
    """Pull likely safe methods from the MEC safe section for fallback cards."""
    text = str(mec_text or "")
    safe_section = text
    marker = "METHODS SAFE TO RECOMMEND"
    if marker in text:
        safe_section = text.split(marker, 1)[1]
    for stop in ("METHODS REQUIRING PROVIDER JUDGMENT", "ABSOLUTELY CONTRAINDICATED", "INSTRUCTION TO LLM"):
        if stop in safe_section:
            safe_section = safe_section.split(stop, 1)[0]

    names: list[str] = []
    for line in safe_section.splitlines():
        line = line.strip(" -•\t")
        if not line:
            continue
        name = line.split("(", 1)[0].strip()
        if not name or name.lower().startswith("category"):
            continue
        if name not in names:
            names.append(name)
        if len(names) >= limit:
            break
    return names


def build_fallback_method_cards(
    *,
    mec_text: str,
    citations: list[dict] | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Build deterministic cards when the LLM ignores card formatting."""
    source_ids = ", ".join(c.get("id", "") for c in (citations or []) if c.get("id")) or "LIB1, LIB2"
    cards = []
    for idx, method_name in enumerate(extract_safe_method_names(mec_text, limit=limit), start=1):
        library = get_method_info(method_name)
        cards.append({
            "index": idx,
            "name": library.get("display_name") or method_name,
            "category": library.get("category") or method_name,
            "summary": f"{library.get('display_name') or method_name} is listed as medically allowable for this client profile.",
            "why_it_fits": "The WHO MEC assessment placed this method in the safe-to-recommend group for the information collected.",
            "how_it_works": library.get("how_it_works", ""),
            "how_to_use": library.get("how_to_use", ""),
            "common_side_effects": library.get("common_side_effects", ""),
            "duration_or_revisit": library.get("duration_or_revisit", ""),
            "referral_required": bool(library.get("referral_required")),
            "referral_reason": library.get("referral_reason", ""),
            "follow_up_schedule": _library_followup_text(library),
            "citations": source_ids,
            "library": library,
            "fallback_generated": True,
        })
    return cards


def method_cards_to_text(cards: list[dict[str, Any]], citations: list[dict] | None = None) -> str:
    """Serialize structured cards back into [METHOD_CARD] text for legacy renderers."""
    blocks = []
    for card in cards:
        blocks.append(
            "[METHOD_CARD]\n"
            f"NAME: {card.get('name', '')}\n"
            f"CATEGORY: {card.get('category', '')}\n"
            f"SUMMARY: {card.get('summary', '')}\n"
            f"WHY_IT_FITS: {card.get('why_it_fits', '')}\n"
            f"HOW_IT_WORKS: {card.get('how_it_works', '')}\n"
            f"HOW_TO_USE: {card.get('how_to_use', '')}\n"
            f"COMMON_SIDE_EFFECTS: {card.get('common_side_effects', '')}\n"
            f"DURATION_OR_REVISIT: {card.get('duration_or_revisit', '')}\n"
            f"REFERRAL_REQUIRED: {'Yes' if card.get('referral_required') else 'No'}\n"
            f"REFERRAL_REASON: {card.get('referral_reason') or 'None'}\n"
            f"FOLLOW_UP_SCHEDULE: {card.get('follow_up_schedule', '')}\n"
            f"CITATIONS: {card.get('citations', '')}\n"
            "[/METHOD_CARD]"
        )
    if citations:
        lines = ["[CITATIONS]"]
        for c in citations:
            lines.append(
                f"{c.get('id')}: {c.get('document')} "
                f"(page {c.get('page') or 'unknown'}, section {c.get('section') or c.get('chapter') or 'unknown'})"
            )
        lines.append("[/CITATIONS]")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def resolve_method_cards(
    recommendation: str,
    mec_text: str = "",
    citations: list[dict] | None = None,
    limit: int = 3,
) -> tuple[list[dict[str, Any]], str]:
    """
    Always return method cards for provider UI.
    Parses LLM output; if missing, builds cards from MEC safe list.
    """
    cards = parse_method_cards(recommendation)
    if cards:
        return cards, recommendation
    fallback = build_fallback_method_cards(mec_text=mec_text, citations=citations, limit=limit)
    text = method_cards_to_text(fallback, citations)
    intro = (
        "ChaguoAI could not read structured cards from the AI response, "
        "so safe methods from the MEC assessment are shown below as selectable cards."
    )
    return fallback, intro + text