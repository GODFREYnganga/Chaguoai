"""
Deterministic contraceptive method education and follow-up schedules.

This module complements the AI recommendation. The LLM can personalize the
clinical rationale, but the CHW workflow needs stable, auditable facts for
"More info", client messages, referrals, and follow-up scheduling.
"""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import timedelta
from typing import Any


DEFAULT_CITATIONS = [
    {
        "id": "LIB1",
        "document": "Kenya National Family Planning Guidelines, 7th Edition",
        "page": "",
        "section": "Contraceptive method counseling and follow-up",
    },
    {
        "id": "LIB2",
        "document": "WHO Selected Practice Recommendations for Contraceptive Use, 4th Edition",
        "page": "",
        "section": "Selected practice recommendations",
    },
]


METHOD_LIBRARY: dict[str, dict[str, Any]] = {
    "implant": {
        "key": "implant",
        "display_name": "Contraceptive implant",
        "category": "Implant",
        "how_it_works": "A small rod is placed under the skin of the upper arm and slowly releases hormone to prevent pregnancy.",
        "how_to_use": "A trained provider inserts it. The client should keep the insertion site clean and return if there is swelling, pus, severe pain, or the rod seems to move out.",
        "common_side_effects": "Irregular bleeding, spotting, lighter or no periods, headaches, breast tenderness, and mild arm soreness after insertion can happen.",
        "warning_signs": "Urgent review is needed for severe lower abdominal pain, heavy bleeding, infection at the insertion site, suspected pregnancy, or the implant coming out.",
        "duration_or_revisit": "Depending on the implant type, it protects for several years. Return any time side effects are unacceptable or pregnancy is desired.",
        "return_to_fertility": "Fertility usually returns quickly after removal.",
        "referral_required": True,
        "referral_reason": "Insertion and removal require a trained provider.",
        "follow_up_schedule": [
            {"days_after_start": 14, "reason": "Early check-in for insertion site and bleeding concerns"},
            {"days_after_start": 90, "reason": "Continuation support and side-effect review"},
            {"days_after_start": 365, "reason": "Annual method review"},
        ],
        "citations": deepcopy(DEFAULT_CITATIONS),
    },
    "iud": {
        "key": "iud",
        "display_name": "Intrauterine device (IUD)",
        "category": "IUD",
        "how_it_works": "An IUD is placed inside the uterus by a trained provider. Copper IUDs prevent fertilization; hormonal IUDs also thicken cervical mucus.",
        "how_to_use": "A trained provider inserts it after checking eligibility. The client should return if strings feel longer or shorter, pain is severe, or pregnancy is suspected.",
        "common_side_effects": "Cramping and bleeding changes can occur after insertion. Copper IUDs may make periods heavier at first; hormonal IUDs may reduce bleeding over time.",
        "warning_signs": "Urgent review is needed for severe pelvic pain, fever, foul discharge, heavy bleeding, suspected pregnancy, or possible expulsion.",
        "duration_or_revisit": "IUDs protect for years depending on type. A check is useful after insertion and anytime warning symptoms occur.",
        "return_to_fertility": "Fertility usually returns quickly after removal.",
        "referral_required": True,
        "referral_reason": "Insertion and removal require a trained provider and sterile procedure.",
        "follow_up_schedule": [
            {"days_after_start": 42, "reason": "Post-insertion check and side-effect review"},
            {"days_after_start": 180, "reason": "Continuation support"},
            {"days_after_start": 365, "reason": "Annual method review"},
        ],
        "citations": deepcopy(DEFAULT_CITATIONS),
    },
    "injectable": {
        "key": "injectable",
        "display_name": "Contraceptive injection",
        "category": "Injectable",
        "how_it_works": "The injection releases hormone that stops ovulation and thickens cervical mucus to prevent pregnancy.",
        "how_to_use": "The client returns for repeat injections on schedule. DMPA is commonly repeated every 3 months.",
        "common_side_effects": "Irregular bleeding, spotting, no monthly bleeding, weight change, headaches, and delayed return to fertility can happen.",
        "warning_signs": "Urgent review is needed for very heavy bleeding, severe headache with vision changes, chest pain, shortness of breath, or suspected pregnancy.",
        "duration_or_revisit": "Plan the next injection before leaving the clinic; late injections can reduce protection.",
        "return_to_fertility": "Fertility can take several months to return after stopping DMPA.",
        "referral_required": False,
        "referral_reason": "",
        "follow_up_schedule": [
            {"days_after_start": 30, "reason": "Early side-effect and satisfaction check"},
            {"days_after_start": 77, "reason": "Reminder for next injection window"},
            {"days_after_start": 90, "reason": "Confirm reinjection or alternative plan"},
        ],
        "citations": deepcopy(DEFAULT_CITATIONS),
    },
    "pill": {
        "key": "pill",
        "display_name": "Contraceptive pills",
        "category": "Pill",
        "how_it_works": "Pills use hormones to prevent ovulation or thicken cervical mucus, depending on pill type.",
        "how_to_use": "Take one pill every day. If pills are missed, the client may need backup protection or emergency contraception depending on timing.",
        "common_side_effects": "Nausea, breast tenderness, spotting, headaches, and lighter periods can occur, especially in the first months.",
        "warning_signs": "Urgent review is needed for severe chest pain, severe headache with vision changes, leg swelling, jaundice, or suspected pregnancy.",
        "duration_or_revisit": "Review after the first month, then at resupply visits or if missed pills become common.",
        "return_to_fertility": "Fertility usually returns quickly after stopping.",
        "referral_required": False,
        "referral_reason": "",
        "follow_up_schedule": [
            {"days_after_start": 30, "reason": "Check daily adherence, missed pills, and side effects"},
            {"days_after_start": 90, "reason": "Continuation and resupply support"},
        ],
        "citations": deepcopy(DEFAULT_CITATIONS),
    },
    "condom": {
        "key": "condom",
        "display_name": "Condoms",
        "category": "Condom",
        "how_it_works": "Condoms create a barrier that prevents sperm from entering the vagina and also reduce STI risk.",
        "how_to_use": "Use a new condom every time before any genital contact. Check expiry date, open carefully, and use water-based lubricant if needed.",
        "common_side_effects": "Some clients report irritation or latex sensitivity. Non-latex options may help when available.",
        "warning_signs": "Seek care if there is genital pain, sores, discharge, possible STI exposure, or condom break with pregnancy concern.",
        "duration_or_revisit": "Protection is per sex act. Support regular resupply.",
        "return_to_fertility": "No delay in fertility.",
        "referral_required": False,
        "referral_reason": "",
        "follow_up_schedule": [
            {"days_after_start": 30, "reason": "Correct-use and resupply support"},
        ],
        "citations": deepcopy(DEFAULT_CITATIONS),
    },
    "emergency contraception": {
        "key": "emergency contraception",
        "display_name": "Emergency contraception",
        "category": "Emergency contraception",
        "how_it_works": "Emergency contraception reduces pregnancy risk after unprotected sex or contraceptive failure.",
        "how_to_use": "Use as soon as possible after unprotected sex. A copper IUD can also be used as emergency contraception when inserted by a trained provider.",
        "common_side_effects": "Nausea, vomiting, fatigue, breast tenderness, spotting, and a changed next period can occur.",
        "warning_signs": "Seek care if the period is more than 7 days late, pregnancy symptoms occur, or there is severe lower abdominal pain.",
        "duration_or_revisit": "It is for emergencies, not ongoing contraception. Offer a regular method after use.",
        "return_to_fertility": "It does not delay future fertility.",
        "referral_required": False,
        "referral_reason": "Copper IUD emergency contraception requires referral for insertion.",
        "follow_up_schedule": [
            {"days_after_start": 21, "reason": "Pregnancy check if no period or symptoms occur"},
            {"days_after_start": 30, "reason": "Offer ongoing contraceptive method"},
        ],
        "citations": deepcopy(DEFAULT_CITATIONS),
    },
    "sterilization": {
        "key": "sterilization",
        "display_name": "Permanent contraception",
        "category": "Sterilization",
        "how_it_works": "Permanent methods prevent pregnancy by blocking sperm or eggs permanently.",
        "how_to_use": "This requires informed consent and a trained surgical provider. It should only be chosen when the client is sure they do not want future pregnancy.",
        "common_side_effects": "Short-term procedure-site pain or discomfort can occur. Counseling should cover permanence and alternatives.",
        "warning_signs": "Urgent review is needed for fever, severe pain, heavy bleeding, wound discharge, or fainting after the procedure.",
        "duration_or_revisit": "Permanent. Follow local surgical follow-up guidance after the procedure.",
        "return_to_fertility": "It should be considered permanent.",
        "referral_required": True,
        "referral_reason": "Requires trained surgical provider and informed consent process.",
        "follow_up_schedule": [
            {"days_after_start": 7, "reason": "Post-procedure wound and recovery check"},
            {"days_after_start": 42, "reason": "Recovery and satisfaction review"},
        ],
        "citations": deepcopy(DEFAULT_CITATIONS),
    },
}


ALIASES = {
    "jadelle": "implant",
    "implanon": "implant",
    "levoplant": "implant",
    "implant": "implant",
    "copper iud": "iud",
    "hormonal iud": "iud",
    "iucd": "iud",
    "iud": "iud",
    "injection": "injectable",
    "injectable": "injectable",
    "depo": "injectable",
    "dmpa": "injectable",
    "sayana": "injectable",
    "combined pill": "pill",
    "progestin-only pill": "pill",
    "oral contraceptive": "pill",
    "pill": "pill",
    "condom": "condom",
    "emergency": "emergency contraception",
    "ec": "emergency contraception",
    "sterilization": "sterilization",
    "tubal": "sterilization",
    "vasectomy": "sterilization",
}


def normalize_method_key(method_name: str) -> str:
    text = re.sub(r"\s+", " ", str(method_name or "").lower()).strip()
    if not text:
        return ""
    if text in METHOD_LIBRARY:
        return text
    for alias, key in ALIASES.items():
        if alias in text:
            return key
    return text


def get_method_info(method_name: str) -> dict[str, Any]:
    key = normalize_method_key(method_name)
    info = METHOD_LIBRARY.get(key)
    if not info:
        return {
            "key": key or "unknown",
            "display_name": method_name or "Selected method",
            "category": method_name or "Other",
            "how_it_works": "Review the clinical recommendation and local guidance for this method.",
            "how_to_use": "Discuss correct use with a trained health worker before starting.",
            "common_side_effects": "Side effects vary by method. Explain expected changes and warning signs.",
            "warning_signs": "Seek urgent care for severe pain, heavy bleeding, chest pain, shortness of breath, fainting, or suspected pregnancy.",
            "duration_or_revisit": "Set a follow-up date based on the method and client's needs.",
            "return_to_fertility": "Return to fertility depends on the method.",
            "referral_required": False,
            "referral_reason": "",
            "follow_up_schedule": [{"days_after_start": 30, "reason": "General follow-up and continuation support"}],
            "citations": deepcopy(DEFAULT_CITATIONS),
        }
    return deepcopy(info)


def all_methods() -> list[dict[str, Any]]:
    return [deepcopy(v) for v in METHOD_LIBRARY.values()]


def build_followup_dates(method_name: str, start_dt) -> list[dict[str, Any]]:
    info = get_method_info(method_name)
    tasks = []
    for item in info.get("follow_up_schedule", []):
        days = int(item.get("days_after_start", 30))
        tasks.append({
            "due_at": start_dt + timedelta(days=days),
            "reason": item.get("reason", "Follow-up support"),
            "days_after_start": days,
        })
    return tasks
