"""
Map Firestore survey answers to WHO MEC UserProfile and readable LLM summaries.
Shared by WhatsApp, USSD, and provider triage flows.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from geography import strip_analytics_fields
from who_mec_engine import UserProfile


def _is_yes(value: str) -> bool:
    text = str(value or "").lower().strip()
    return text in {"1", "yes", "ndio", "oui", "sim", "y"} or text.startswith("yes")


def _is_no(value: str) -> bool:
    text = str(value or "").lower().strip()
    return text in {"2", "no", "hapana", "non", "nao", "não", "n"} or text.startswith("no")


def _first_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else None


def _map_fertility_intention(raw: str) -> Optional[str]:
    text = str(raw or "").lower()
    if any(token in text for token in ("1", "2 year", "miaka 2", "2 ans", "2 anos", "soon", "karibuni", "bientôt")):
        return "within_2_years"
    if any(token in text for token in ("2", "later", "baadaye", "tard", "depois", "plus tard")):
        return "later"
    if any(token in text for token in ("3", "no", "hapana", "non", "nao", "não", "no more", "tena")):
        return "no_more"
    return None


def _map_facility_access(raw: str) -> Optional[str]:
    text = str(raw or "").lower()
    if "1" in text or "easy" in text or "rahisi" in text or "facile" in text or "fácil" in text or "facil" in text:
        return "easy"
    if "3" in text or "very" in text or "sana" in text or "très" in text or "muito" in text:
        return "very_hard"
    if "2" in text or "sometimes" in text or "wakati" in text or "parfois" in text or "vezes" in text:
        return "sometimes_hard"
    return None


def _map_previous_method_stop(raw: str) -> tuple[Optional[str], Optional[bool]]:
    text = str(raw or "").lower()
    if not text:
        return None, None
    if "2" in text or "side effect" in text or "madhara" in text or "effet" in text or "efeito" in text:
        return "unknown", True
    if "1" in text or "still" in text or "bado" in text or "toujours" in text or "ainda" in text:
        return "unknown", False
    return "unknown", None


def map_firestore_user_to_profile(user: dict) -> UserProfile:
    """Build a complete UserProfile from WhatsApp / web survey Firestore fields."""
    user = strip_analytics_fields(user)
    prof = UserProfile()
    prof.age_years = _first_int(user.get("age"))

    lp = str(user.get("last_period", "")).lower()
    if any(token in lp for token in ("3", "pregnant", "mimba", "enceinte", "grávida", "gravida")):
        prof.pregnancy_status = "pregnant"
    elif any(token in lp for token in ("1", "within", "wiki 4", "4 semaines", "4 semanas", "semaines")):
        prof.last_period_timing = "within_4_weeks"
    elif any(token in lp for token in ("2", "not sure", "uhakika", "pas sûr", "certeza", "unsure")):
        prof.last_period_timing = "unknown"

    if _is_yes(user.get("baby_under_6m", "")):
        prof.postpartum_days = 90
        if _is_yes(user.get("breastfeeding_only", "")):
            prof.breastfeeding = True
            prof.breastfeeding_exclusively = True
            prof.baby_age_months = 3.0
        elif _is_no(user.get("breastfeeding_only", "")):
            prof.breastfeeding = True
            prof.breastfeeding_exclusively = False
            prof.baby_age_months = 3.0
    elif _is_no(user.get("baby_under_6m", "")):
        prof.breastfeeding = False

    prof.number_of_children = _first_int(user.get("living_children"))
    prof.fertility_intention = _map_fertility_intention(user.get("more_children", ""))

    hc = str(user.get("health_conditions", ""))
    if "1" in hc:
        prof.hypertension = True
    if "2" in hc:
        prof.diabetes = True
    if "3" in hc:
        prof.heart_disease = True
    if "4" in hc:
        prof.liver_disease = True
    if "5" in hc:
        prof.breast_cancer_current = True
    if "6" in hc:
        prof.migraine_without_aura = True

    hiv = str(user.get("hiv_status", "")).lower()
    if _is_yes(hiv) or "positive" in hiv or "chanya" in hiv:
        prof.hiv_positive = True
    elif _is_no(hiv) or "negative" in hiv or "hasi" in hiv:
        prof.hiv_positive = False

    smoke = str(user.get("smoke", "")).lower()
    if _is_yes(smoke):
        prof.smoker = True
    elif _is_no(smoke):
        prof.smoker = False

    sti = str(user.get("sti_concern", "")).lower()
    if _is_yes(sti):
        prof.high_sti_risk = True
    elif _is_no(sti):
        prof.high_sti_risk = False

    partner = str(user.get("partner_support", "")).lower()
    if _is_yes(partner):
        prof.partner_supports_contraception = True
    elif _is_no(partner) or "no partner" in partner or "sina mpenzi" in partner:
        prof.partner_supports_contraception = False

    prof.facility_access = _map_facility_access(user.get("facility_access", ""))

    prev_use = str(user.get("previous_use", "")).lower()
    if _is_yes(prev_use):
        prev_method, side_effects = _map_previous_method_stop(user.get("stop_reason", ""))
        prof.previous_method = prev_method or "unknown"
        if side_effects is not None:
            prof.previous_side_effects = side_effects
    elif _is_no(prev_use):
        prof.previous_method = "none"

    return prof


METHOD_AVOID_LABELS = {
    "1": "oral contraceptive pills",
    "2": "injectables",
    "3": "IUD",
    "4": "implants",
    "5": "none specified",
}


def format_survey_context_for_llm(user: dict) -> str:
    """Plain-language summary of clinical intake answers (excludes analytics geography)."""
    user = strip_analytics_fields(user)
    avoid_raw = str(user.get("prefer_not_to_use", ""))
    avoided = []
    for key, label in METHOD_AVOID_LABELS.items():
        if key in avoid_raw and key != "5":
            avoided.append(label)
    avoid_text = ", ".join(avoided) if avoided else "No method exclusions reported"

    lines = [
        f"Name: {user.get('name', 'Client')}",
        f"Age: {user.get('age', 'unknown')}",
        f"Last period / pregnancy status: {user.get('last_period', 'unknown')}",
        f"Baby under 6 months: {user.get('baby_under_6m', 'unknown')}",
        f"Exclusive breastfeeding: {user.get('breastfeeding_only', 'n/a')}",
        f"Living children: {user.get('living_children', 'unknown')}",
        f"Wants more children: {user.get('more_children', 'unknown')}",
        f"Health conditions (numbered selections): {user.get('health_conditions', 'none')}",
        f"HIV status: {user.get('hiv_status', 'unknown')}",
        f"Smoker: {user.get('smoke', 'unknown')}",
        f"Previous contraception use: {user.get('previous_use', 'unknown')}",
        f"Stop reason if applicable: {user.get('stop_reason', 'n/a')}",
        f"Partner support: {user.get('partner_support', 'unknown')}",
        f"Facility access: {user.get('facility_access', 'unknown')}",
        f"STI protection concern: {user.get('sti_concern', 'unknown')}",
        f"Methods to avoid: {avoid_text}",
        "Survey status: COMPLETE (all 13 questions answered).",
    ]
    return "\n".join(lines)


def build_method_match_user_message(user: dict, language: str = "english") -> str:
    """Explicit instruction so the LLM must output a concrete method recommendation."""
    name = user.get("name", "there")
    prompts = {
        "english": (
            f"The client {name} has completed all 13 Method Match questions. "
            "Using Section A (profile), Section B (WHO MEC), and Section C (guidelines), "
            "recommend the TOP 2-3 safest contraceptive methods. "
            "Write a COMPLETE message of at least 50 words (up to 250). "
            "Do not stop mid-sentence. Start with #1 in *bold*, then bullets for options 2-3, source line, one short question."
        ),
        "swahili": (
            f"Mteja {name} amemaliza maswali 13 ya Method Match. "
            "Pendekeza njia 2-3 salama zaidi kutoka WHO MEC. "
            "Andika ujumbe KAMILI wa angalau maneno 50 (hadi 250). Usisimamishe katikati. Anza na #1 kwa *bold*, bullets, chanzo, swali moja."
        ),
        "french": (
            f"La cliente {name} a terminé les 13 questions Method Match. "
            "Recommandez 2-3 méthodes les plus sûres selon la CMM OMS. "
            "LIMITE STRICTE : 50-200 mots. Commencez par #1 en *gras*, puces brèves, source, une question."
        ),
        "portuguese": (
            f"A cliente {name} completou as 13 perguntas do Method Match. "
            "Recomende 2-3 métodos mais seguros segundo a CMC da OMS. "
            "LIMITE ESTRITO: 50-200 palavras. Comece com #1 em *negrito*, bullets breves, fonte, uma pergunta."
        ),
    }
    return prompts.get(language, prompts["english"])


def map_ussd_responses_to_firestore_user(responses: dict, phone: str, lang: str = "english") -> dict:
    """Convert USSD numeric answers to the same Firestore shape WhatsApp uses."""
    doc = {
        "phone": phone,
        "language": lang,
        "name": responses.get("name") or "USSD Client",
        "age": responses.get("age"),
        "last_period": responses.get("last_period"),
        "baby_under_6m": responses.get("baby_under_6m"),
        "breastfeeding_only": responses.get("breastfeeding"),
        "living_children": responses.get("children"),
        "more_children": responses.get("more_children"),
        "health_conditions": responses.get("health"),
        "hiv_status": responses.get("hiv"),
        "smoke": responses.get("smoke"),
        "previous_use": responses.get("used_before"),
        "stop_reason": responses.get("stop_reason"),
        "partner_support": responses.get("partner"),
        "facility_access": responses.get("facility_access"),
        "sti_concern": responses.get("sti"),
        "prefer_not_to_use": responses.get("prefer_not"),
        "source": "ussd",
    }
    if responses.get("country"):
        doc["country"] = responses.get("country")
        doc["country_raw"] = responses.get("country_raw")
        doc["country_match_confidence"] = responses.get("country_match_confidence")
        doc["location_capture_purpose"] = "analytics_only"
        doc["location_source"] = "ussd"
    if responses.get("admin_area"):
        doc["admin_area"] = responses.get("admin_area")
        doc["admin_area_raw"] = responses.get("admin_area_raw")
        doc["admin_area_type"] = responses.get("admin_area_type")
    return doc


def map_triage_form_to_user(data: dict) -> dict:
    """Map provider triage wizard fields to a Firestore-compatible user dict."""
    user_like = {
        "age": data.get("age"),
        "last_period": data.get("last_period"),
        "baby_under_6m": "Yes" if "Yes" in str(data.get("nursing", "")) else "No",
        "breastfeeding_only": "Yes" if "Less than" in str(data.get("nursing", "")) else "No",
        "living_children": data.get("parity"),
        "more_children": data.get("future_children"),
        "health_conditions": "1" if "High" in str(data.get("blood_pressure", "")) else "7",
        "hiv_status": data.get("hiv_status"),
        "smoke": data.get("smoking"),
        "previous_use": "No",
        "partner_support": "Yes",
        "facility_access": "Easy",
        "sti_concern": "Yes" if "High" in str(data.get("sti_risk", "")) else "No",
        "prefer_not_to_use": data.get("preference", ""),
        "name": data.get("name"),
        "phone": data.get("phone"),
    }
    health = str(data.get("health_history", "")).lower()
    codes = []
    if "migraine" in health:
        codes.append("6")
    if "liver" in health:
        codes.append("4")
    if "heart" in health:
        codes.append("3")
    if codes:
        user_like["health_conditions"] = ",".join(codes)
    return user_like


def serializable_user_snapshot(user: dict) -> dict:
    """Strip Firestore types and analytics geography for RQ job payloads."""
    user = strip_analytics_fields(user)
    safe = {}
    for key, value in user.items():
        if value is None or isinstance(value, (str, int, float, bool)):
            safe[key] = value
        elif isinstance(value, (list, dict)):
            safe[key] = value
        else:
            safe[key] = str(value)
    return safe
