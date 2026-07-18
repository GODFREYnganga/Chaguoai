"""
Structured Recommendation Packet for provider/clinician dashboards.

This module is intentionally deterministic. The LLM can produce narrative
recommendations, but dashboards need stable fields for clinical review,
follow-up, analytics, and action buttons.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from method_library import get_method_info
from model_adherence import predict_method_adherence
from response_cards import resolve_method_cards


MISSING_INFO_RULES = [
    ("last_period", "Pregnancy status uncertain", "When was your last menstrual period, or could you be pregnant?"),
    ("smoke", "Smoking status unknown", "Do you smoke cigarettes or use nicotine products?"),
    ("health_conditions", "Medical conditions unknown", "Do you have high blood pressure, diabetes, migraines, liver disease, blood clots, or cancer?"),
    ("hiv_status", "HIV status unknown", "Are you living with HIV or taking HIV treatment?"),
    ("facility_access", "Facility access unknown", "How easy is it for you to visit a clinic or hospital?"),
    ("sti_concern", "STI protection preference unknown", "Do you also want protection from sexually transmitted infections?"),
]


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _lower_join(*values: Any) -> str:
    return " ".join(_text(v).lower() for v in values if _text(v))


def _first_present(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return ""


def _parse_datetime(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return _text(value)


def build_client_snapshot(client: dict[str, Any]) -> dict[str, Any]:
    nursing = _text(_first_present(client, "nursing", "baby_under_6m", "breastfeeding_only"))
    postpartum_status = "Unknown"
    breastfeeding_status = "Unknown"
    if "pregnant" in _lower_join(client.get("last_period")):
        postpartum_status = "Pregnancy possible/current"
    elif any(token in _lower_join(nursing) for token in ("yes", "ndio", "oui", "sim", "less than")):
        postpartum_status = "Postpartum / baby under 6 months"
        breastfeeding_status = "Breastfeeding"
    elif any(token in _lower_join(nursing) for token in ("no", "hapana", "non", "nao", "não")):
        postpartum_status = "Not recently postpartum"
        breastfeeding_status = "Not breastfeeding"

    conditions = []
    health = _lower_join(client.get("health_conditions"), client.get("health_history"), client.get("blood_pressure"))
    for label, tokens in (
        ("Hypertension", ("high blood", "hypertension", "1")),
        ("Diabetes", ("diabetes", "2")),
        ("Heart disease", ("heart", "3")),
        ("Liver disease", ("liver", "4")),
        ("Cancer", ("cancer", "5")),
        ("Migraine", ("migraine", "6")),
    ):
        if any(token in health for token in tokens):
            conditions.append(label)

    return {
        "name": client.get("name") or "",
        "phone": client.get("phone") or client.get("id") or "",
        "age": client.get("age") or "",
        "postpartum_status": postpartum_status,
        "breastfeeding_status": breastfeeding_status,
        "key_medical_conditions": conditions,
        "client_preferences": client.get("prefer_not_to_use") or client.get("preference") or "",
        "country": client.get("country") or "",
        "admin_area": client.get("admin_area") or "",
        "communication_channel": client.get("source") or client.get("channel") or ("provider" if client.get("triage_status") else "whatsapp"),
        "last_activity": _parse_datetime(
            _first_present(
                client,
                "last_followup_response_at",
                "latest_followup_at",
                "method_match_completed_at",
                "triage_completed_at",
                "updated_at",
                "created_at",
            )
        ),
    }


def build_risk_flags(client: dict[str, Any], mec_text: str = "") -> list[dict[str, Any]]:
    text = _lower_join(client, mec_text)
    rules = [
        ("hypertension", "Hypertension", "Review blood pressure and avoid estrogen methods if severe."),
        ("diabetes", "Diabetes", "Check for vascular complications before estrogen methods."),
        ("smok", "Smoking", "Smoking with age 35+ increases combined hormonal method risk."),
        ("migraine", "Migraine", "Migraine with aura is a major warning for estrogen methods."),
        ("vte", "History of DVT/VTE", "Blood clot history affects combined hormonal methods."),
        ("postpartum", "Postpartum", "Timing after delivery affects IUD and estrogen eligibility."),
        ("breastfeeding", "Breastfeeding", "Breastfeeding status affects early postpartum options."),
        ("pregnan", "Pregnancy concern", "Confirm pregnancy status before starting contraception."),
        ("sti", "High STI risk", "Condom counseling should accompany pregnancy prevention."),
        ("hiv", "HIV", "Review ART interactions and STI prevention needs."),
    ]
    flags = []
    for key, label, detail in rules:
        if key in text:
            flags.append({"key": label.lower().replace("/", "_").replace(" ", "_"), "label": label, "detail": detail})
    return flags


def detect_missing_information(client: dict[str, Any]) -> list[dict[str, str]]:
    missing = []
    for field, label, question in MISSING_INFO_RULES:
        if not _text(client.get(field)):
            missing.append({"field": field, "label": label, "question": question})
    return missing


def _safe_section(mec_text: str) -> str:
    text = _text(mec_text)
    if "METHODS SAFE TO RECOMMEND" in text:
        text = text.split("METHODS SAFE TO RECOMMEND", 1)[1]
    for stop in ("METHODS REQUIRING PROVIDER JUDGMENT", "ABSOLUTELY CONTRAINDICATED", "INSTRUCTION TO LLM"):
        if stop in text:
            text = text.split(stop, 1)[0]
    return text


def _mec_category_for_method(method_name: str, mec_text: str) -> int:
    safe = _safe_section(mec_text)
    target = method_name.lower()
    for line in safe.splitlines():
        if target[:12] in line.lower() or any(part and part in line.lower() for part in target.split()[:2]):
            match = re.search(r"Category\s+([1234])", line, re.IGNORECASE)
            if match:
                return int(match.group(1))
    return 2


def score_method_confidence(card: dict[str, Any], client: dict[str, Any], mec_text: str, missing: list[dict[str, str]] | None = None) -> dict[str, Any]:
    missing = missing or []
    category = _mec_category_for_method(card.get("name", ""), mec_text)
    score = 96 if category == 1 else 88 if category == 2 else 65
    reasons = [f"WHO MEC Category {category} in the safe-method assessment."]
    confidence_reasons = [
        "No restriction detected" if category == 1 else "Generally acceptable under WHO MEC",
    ]

    preference = _lower_join(client.get("prefer_not_to_use"), client.get("preference"))
    name = _lower_join(card.get("name"), card.get("category"))
    if preference and any(token in name for token in ("implant", "iud", "inject", "pill") if token in preference):
        score -= 14
        reasons.append("Client preference may not favor this method.")
        confidence_reasons.append("May not match recorded method preference")
    else:
        reasons.append("No direct conflict with recorded method preference.")
        confidence_reasons.append("No direct conflict with recorded preference")

    if card.get("referral_required"):
        score -= 5
        reasons.append("Requires provider visit or procedure access.")
        confidence_reasons.append("Needs trained provider access")
    if missing:
        score -= min(15, len(missing) * 3)
        reasons.append("Some intake information is missing.")
        confidence_reasons.append("Some intake information is missing")
    if "condom" in name and _lower_join(client.get("sti_concern")):
        score += 4
        reasons.append("Supports STI protection preference.")
        confidence_reasons.append("Supports STI protection")
    if any(token in name for token in ("implant", "iud")):
        confidence_reasons.append("Highly effective long-acting option")
    if "breastfeeding" in _lower_join(client, mec_text):
        confidence_reasons.append("Compatible with recorded breastfeeding context")

    score = max(0, min(100, score))
    level = "High" if score >= 85 else "Moderate" if score >= 65 else "Low"
    return {
        "score": score,
        "level": level,
        "reasoning": reasons,
        "reasons": confidence_reasons[:5],
        "confidence_reasons": confidence_reasons[:5],
    }


def build_methods_not_recommended(mec_text: str) -> list[dict[str, Any]]:
    text = _text(mec_text)
    sections = [
        ("METHODS REQUIRING PROVIDER JUDGMENT", "provider_judgment", 3),
        ("ABSOLUTELY CONTRAINDICATED", "contraindicated", 4),
    ]
    items = []
    for marker, severity, default_category in sections:
        if marker not in text:
            continue
        section = text.split(marker, 1)[1]
        for stop in ("METHODS REQUIRING PROVIDER JUDGMENT", "ABSOLUTELY CONTRAINDICATED", "INSTRUCTION TO LLM"):
            if stop != marker and stop in section:
                section = section.split(stop, 1)[0]
        for line in section.splitlines():
            cleaned = line.strip(" -•\t")
            if not cleaned or cleaned.lower() == "none":
                continue
            category_match = re.search(r"Category\s+([1234])", cleaned, re.IGNORECASE)
            category = int(category_match.group(1)) if category_match else default_category
            name, _, reason = cleaned.partition(":")
            if "(" in name:
                name = name.split("(", 1)[0].strip()
            items.append({
                "method_name": name.strip(),
                "mec_category": category,
                "reason": reason.strip() or cleaned,
                "severity": severity,
            })
    return items


def build_safety_summary(mec_text: str, recommended_methods: list[dict[str, Any]], methods_not_recommended: list[dict[str, Any]]) -> dict[str, Any]:
    contraindicated = [m for m in methods_not_recommended if m.get("severity") == "contraindicated"]
    provider_judgment = [m for m in methods_not_recommended if m.get("severity") == "provider_judgment"]
    return {
        "status": "safe_options_available" if recommended_methods else "provider_review_needed",
        "safe_method_count": len(recommended_methods),
        "provider_judgment_count": len(provider_judgment),
        "contraindicated_count": len(contraindicated),
        "summary": (
            f"{len(recommended_methods)} method option(s) are safe to discuss. "
            f"{len(provider_judgment)} need provider judgment and {len(contraindicated)} are not recommended."
        ),
    }


def build_clarification_questions(missing: list[dict[str, str]], recommended_methods: list[dict[str, Any]]) -> list[dict[str, str]]:
    questions = [{"topic": item["label"], "question": item["question"]} for item in missing[:4]]
    for card in recommended_methods[:3]:
        name = card.get("name", "this method")
        questions.append({"topic": name, "question": f"Do you want to know about side effects, fertility return, or how to start {name}?"})
    return questions[:6]


def build_counseling_notes(recommended_methods: list[dict[str, Any]], risk_flags: list[dict[str, Any]]) -> list[str]:
    notes = [
        "Confirm the client understands benefits, side effects, warning signs, and alternatives before selection.",
        "Remind the client that she can switch or stop a method if it does not suit her.",
    ]
    if any(flag["label"] == "High STI risk" for flag in risk_flags):
        notes.append("Discuss condom use because most contraceptive methods do not protect against STIs.")
    if any(card.get("referral_required") for card in recommended_methods):
        notes.append("At least one option requires a trained provider; confirm referral access before selection.")
    return notes


def build_care_plan_status(client: dict[str, Any]) -> dict[str, Any]:
    return {
        "selected_method": client.get("selected_method") or "",
        "referral_status": client.get("referral_status") or ("required" if client.get("referral_required") else "not_required"),
        "care_plan_status": client.get("care_plan_status") or client.get("continuation_status") or ("active" if client.get("selected_method") else "not_started"),
        "next_followup_at": _parse_datetime(client.get("next_followup_at")),
        "last_followup_sent_at": _parse_datetime(client.get("last_followup_sent_at") or client.get("latest_followup_sent_at")),
        "last_followup_response_at": _parse_datetime(client.get("last_followup_response_at")),
        "no_response_count": int(client.get("no_response_count") or 0),
        "automation_enabled": bool(client.get("automation_enabled", False)),
        "followup_consent": bool(client.get("followup_consent", False)),
    }


def build_recommended_methods(
    recommendation_text: str,
    mec_text: str,
    citations: list[dict] | None,
    method_cards: list[dict[str, Any]] | None,
    client: dict[str, Any],
) -> list[dict[str, Any]]:
    cards = method_cards or []
    if not cards:
        cards, _ = resolve_method_cards(recommendation_text, mec_text, citations or [])

    missing = detect_missing_information(client)
    methods = []
    for card in cards:
        info = get_method_info(card.get("name", ""))
        adherence_prediction = predict_method_adherence(client, card.get("name", ""))
        method = {
            **card,
            "actions": ["ask_question", "view_side_effects", "confirm_client_choice", "refer", "send_instructions"],
            "confidence": score_method_confidence(card, client, mec_text, missing),
            "adherence_prediction": adherence_prediction,
            "side_effects": card.get("common_side_effects") or info.get("common_side_effects", ""),
            "warning_signs": info.get("warning_signs", ""),
            "instructions": card.get("how_to_use") or info.get("how_to_use", ""),
        }
        methods.append(method)
    return methods


def build_recommendation_packet(
    *,
    client: dict[str, Any],
    recommendation_text: str = "",
    mec_text: str = "",
    citations: list[dict] | None = None,
    method_cards: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    recommended_methods = build_recommended_methods(
        recommendation_text,
        mec_text,
        citations or [],
        method_cards,
        client,
    )
    missing = detect_missing_information(client)
    methods_not_recommended = build_methods_not_recommended(mec_text)
    risk_flags = build_risk_flags(client, mec_text)
    adherence_predictions = [m.get("adherence_prediction") for m in recommended_methods if m.get("adherence_prediction")]
    return {
        "client_snapshot": build_client_snapshot(client),
        "safety_summary": build_safety_summary(mec_text, recommended_methods, methods_not_recommended),
        "risk_flags": risk_flags,
        "recommendation_confidence": {
            "score": round(sum(m["confidence"]["score"] for m in recommended_methods) / len(recommended_methods)) if recommended_methods else 0,
            "level": "High" if recommended_methods and min(m["confidence"]["score"] for m in recommended_methods) >= 85 else "Moderate" if recommended_methods else "Low",
            "reasoning": [reason for method in recommended_methods for reason in method["confidence"]["reasoning"][:1]][:4],
            "confidence_reasons": [reason for method in recommended_methods for reason in method["confidence"]["confidence_reasons"][:1]][:4],
        },
        "adherence_model": {
            "mode": "shadow",
            "available": any(p.get("available") for p in adherence_predictions),
            "model_name": next((p.get("model_name") for p in adherence_predictions if p.get("model_name")), "lightgbm"),
            "model_version": next((p.get("model_version") for p in adherence_predictions if p.get("model_version")), ""),
            "applicability": next((p.get("model_applicability") for p in adherence_predictions if p.get("model_applicability")), "unknown"),
            "note": "Scores annotate MEC-safe methods for continuation support and do not override WHO MEC safety.",
        },
        "missing_information": missing,
        "recommended_methods": recommended_methods,
        "methods_not_recommended": methods_not_recommended,
        "clarification_questions": build_clarification_questions(missing, recommended_methods),
        "counseling_notes": build_counseling_notes(recommended_methods, risk_flags),
        "citations": citations or [],
        "care_plan_status": build_care_plan_status(client),
    }
