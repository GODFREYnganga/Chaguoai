"""
Derive a single primary contraceptive method category from recommendation text.
Used for honest admin analytics (not keyword scraping of full LLM output).
"""

from __future__ import annotations

import re
from typing import Optional

# Order matters: more specific phrases first
_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Emergency contraception", ("emergency contraception", "ec pill", "morning after")),
    ("Implant", ("implant", "jadelle", "implanon", "levoplant")),
    ("IUD", ("iud", "iucd", "intrauterine", "copper t", "hormonal iud")),
    ("Injectable", ("injectable", "injection", "depo", "sayana", "dmpa")),
    ("Pill", ("combined pill", "oral contraceptive", " coc ", "progestin-only pill", " pop ", "pill")),
    ("Condom", ("condom", "female condom")),
    ("Sterilization", ("sterilization", "tubal", "vasectomy")),
    ("Patch", ("patch", "transdermal")),
    ("Ring", ("vaginal ring", "ring")),
    ("LARC unspecified", ("larc", "long-acting")),
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower())


def _first_method_card_name(text: str) -> Optional[str]:
    for block in re.findall(
        r"\[METHOD_CARD\]([\s\S]*?)\[/METHOD_CARD\]",
        str(text or ""),
        flags=re.IGNORECASE,
    ):
        match = re.search(r"NAME:\s*(.+)", block, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            if name:
                return name
    return None


def classify_method_category_primary(text: str) -> Optional[str]:
    """
    Return one primary category label, or None if no recommendation yet.
    """
    if not text or not str(text).strip():
        return None

    raw = str(text)
    card_name = _first_method_card_name(raw)
    haystack = _normalize(card_name or raw)

    for category, keywords in _CATEGORY_RULES:
        if any(kw in haystack for kw in keywords):
            return category

    if card_name:
        return "Other (named in card)"

    return "Other / narrative only"
