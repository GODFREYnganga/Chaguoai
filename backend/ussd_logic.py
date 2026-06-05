"""
USSD flow — aligned with WhatsApp Method Match (13 questions, shared clinical pipeline).
Supports English, Kiswahili, French, and Portuguese.
Method Match LLM runs asynchronously via Redis worker to avoid AT session timeouts.
"""

from __future__ import annotations

import re

from firebase_admin import firestore

from db_client import get_db
from geography import (
    admin_area_label,
    build_admin_area_firestore_fields,
    build_country_firestore_fields,
    is_valid_country_input,
    is_valid_location_input,
    normalize_country,
)
from user_profile_mapper import map_ussd_responses_to_firestore_user
from ussd_strings import LANG_BY_CHOICE, ussd_text

SUPPORTED_LANG_CHOICES = frozenset(LANG_BY_CHOICE.keys())


def _t(lang: str, key: str) -> str:
    return ussd_text(lang, key)


def _ussd_geo_area_prompt(lang: str, country: str) -> str:
    label = admin_area_label(country)
    prompts = {
        "swahili": f"CON Kwa takwimu tu: Andika {label} yako:",
        "french": f"CON Stats seulement: Entrez {label}:",
        "portuguese": f"CON So estatisticas: Indique {label}:",
    }
    return prompts.get(lang, f"CON Analytics only: Enter your {label}:")


def _resolve_lang_choice(choice: str) -> str | None:
    return LANG_BY_CHOICE.get(str(choice).strip())


def _get_lang(db, phone: str) -> str | None:
    if not db:
        return "english"
    doc = db.collection("contraceptive_users").document(phone).get()
    if doc.exists:
        return doc.to_dict().get("language")
    return None


def _save_lang(db, phone: str, lang: str):
    if db:
        db.collection("contraceptive_users").document(phone).set({
            "phone": phone,
            "language": lang,
            "source": "ussd",
        }, merge=True)


def _safe_job_id(phone_number: str) -> str:
    digits = re.sub(r"\D", "", phone_number or "unknown")
    return f"ussd_{digits or 'unknown'}"


def _enqueue_ussd_method_match(phone_number: str, lang: str, user_doc: dict) -> bool:
    try:
        from task_queue import (
            TRIAGE_JOB_FAILURE_TTL_SECONDS,
            TRIAGE_JOB_RESULT_TTL_SECONDS,
            TRIAGE_JOB_TIMEOUT_SECONDS,
            get_triage_queue,
        )
        get_triage_queue().enqueue_call(
            func="ussd_tasks.process_ussd_method_match_job",
            args=(phone_number, lang, user_doc),
            job_id=_safe_job_id(phone_number),
            timeout=TRIAGE_JOB_TIMEOUT_SECONDS,
            result_ttl=TRIAGE_JOB_RESULT_TTL_SECONDS,
            failure_ttl=TRIAGE_JOB_FAILURE_TTL_SECONDS,
        )
        return True
    except Exception as exc:
        print(f"[{phone_number}] USSD enqueue failed: {exc}")
        return False


def _finish_method_match(phone_number: str, lang: str, responses: dict, db) -> str:
    """Queue async LLM job or return fast MEC summary when Redis is unavailable."""
    user_doc = map_ussd_responses_to_firestore_user(responses, phone_number, lang)
    pending = {
        **user_doc,
        "stage": "REGISTERED",
        "registered_at": firestore.SERVER_TIMESTAMP,
        "method_match_status": "queued",
        "method_match_pending": True,
        "source": "ussd",
    }
    if db:
        db.collection("contraceptive_users").document(phone_number).set(pending, merge=True)

    if _enqueue_ussd_method_match(phone_number, lang, user_doc):
        return _t(lang, "queued")

    try:
        from clinical_pipeline import generate_ussd_fast_mec_summary
        from method_categories import classify_method_category_primary

        print(f"[{phone_number}] USSD: Redis unavailable — using fast MEC summary")
        reply_text, mec_text = generate_ussd_fast_mec_summary(user_doc)
        if db:
            db.collection("contraceptive_users").document(phone_number).set({
                **user_doc,
                "matched_method": reply_text,
                "method_category_primary": classify_method_category_primary(reply_text),
                "latest_mec_text": mec_text,
                "method_match_status": "completed",
                "method_match_pending": False,
                "method_match_completed_at": firestore.SERVER_TIMESTAMP,
                "stage": "REGISTERED",
                "source": "ussd",
            }, merge=True)
        return f"{_t(lang, 'match_prefix')}{reply_text}"
    except Exception as exc:
        print(f"USSD ERROR (fast path): {exc}")
        if db:
            db.collection("contraceptive_users").document(phone_number).set({
                **user_doc,
                "method_match_status": "failed",
                "method_match_error": str(exc),
                "method_match_pending": False,
                "stage": "REGISTERED",
            }, merge=True)
        return _t(lang, "match_error")


def process_method_match(answers, phone_number, db):
    lang = _get_lang(db, phone_number) or "english"
    ans_index = 0
    responses = {}

    def need(key):
        return _t(lang, key)

    if ans_index >= len(answers):
        return need("geo_country")
    country_text = answers[ans_index]
    if not is_valid_country_input(country_text):
        return need("geo_invalid")
    normalized = normalize_country(country_text)
    responses.update(build_country_firestore_fields(normalized, source="ussd"))
    ans_index += 1

    if ans_index >= len(answers):
        return _ussd_geo_area_prompt(lang, normalized.canonical)
    area_text = answers[ans_index]
    if not is_valid_location_input(area_text):
        return need("geo_invalid")
    responses.update(
        build_admin_area_firestore_fields(area_text, normalized.canonical, source="ussd")
    )
    ans_index += 1

    if ans_index >= len(answers):
        return need("q1")
    responses["age"] = answers[ans_index]
    ans_index += 1

    if ans_index >= len(answers):
        return need("q2")
    responses["last_period"] = answers[ans_index]
    ans_index += 1

    if ans_index >= len(answers):
        return need("q3")
    q3_ans = answers[ans_index]
    responses["baby_under_6m"] = q3_ans
    ans_index += 1

    if q3_ans == "1":
        if ans_index >= len(answers):
            return need("q3a")
        responses["breastfeeding"] = answers[ans_index]
        ans_index += 1

    if ans_index >= len(answers):
        return need("q4")
    responses["children"] = answers[ans_index]
    ans_index += 1

    if ans_index >= len(answers):
        return need("q5")
    responses["more_children"] = answers[ans_index]
    ans_index += 1

    if ans_index >= len(answers):
        return need("q6")
    responses["health"] = answers[ans_index]
    ans_index += 1

    if ans_index >= len(answers):
        return need("q7")
    responses["hiv"] = answers[ans_index]
    ans_index += 1

    if ans_index >= len(answers):
        return need("q8")
    responses["smoke"] = answers[ans_index]
    ans_index += 1

    if ans_index >= len(answers):
        return need("q9")
    q9_ans = answers[ans_index]
    responses["used_before"] = q9_ans
    ans_index += 1

    if q9_ans == "1":
        if ans_index >= len(answers):
            return need("q9a")
        responses["stop_reason"] = answers[ans_index]
        ans_index += 1

    if ans_index >= len(answers):
        return need("q10")
    responses["partner"] = answers[ans_index]
    ans_index += 1

    if ans_index >= len(answers):
        return need("q11")
    responses["facility_access"] = answers[ans_index]
    ans_index += 1

    if ans_index >= len(answers):
        return need("q12")
    responses["sti"] = answers[ans_index]
    ans_index += 1

    if ans_index >= len(answers):
        return need("q13")
    responses["prefer_not"] = answers[ans_index]

    return _finish_method_match(phone_number, lang, responses, db)


def _apply_language_choice(db, phone_number: str, choice: str) -> str | None:
    lang = _resolve_lang_choice(choice)
    if not lang:
        return None
    _save_lang(db, phone_number, lang)
    return lang


def handle_ussd_request(session_id, service_code, phone_number, text, db=None):
    db = db or get_db()
    text_array = text.split("*") if text else []

    lang = _get_lang(db, phone_number)

    if lang is None:
        if len(text_array) == 0:
            return _t("english", "language")
        if len(text_array) == 1:
            chosen = _apply_language_choice(db, phone_number, text_array[0])
            if chosen:
                return _t(chosen, "welcome")
        return _t("english", "language")

    if len(text_array) == 0:
        return _t(lang, "welcome")

    if text_array[0] == "5":
        if len(text_array) == 1:
            return _t(lang, "language")
        if len(text_array) == 2:
            chosen = _apply_language_choice(db, phone_number, text_array[1])
            if chosen:
                return _t(chosen, "welcome")
        return _t(lang, "language")

    choice = text_array[0]

    if choice == "1":
        return process_method_match(text_array[1:], phone_number, db)
    if choice == "2":
        if len(text_array) == 1:
            return _t(lang, "side_effect_prompt")
        if db:
            try:
                db.collection("contraceptive_users").document(phone_number).collection("side_effects").add({
                    "report": text_array[1],
                    "language": lang,
                    "timestamp": firestore.SERVER_TIMESTAMP,
                    "source": "ussd",
                })
            except Exception:
                pass
        return _t(lang, "side_effect_saved")
    if choice == "3":
        if db:
            try:
                user_doc = db.collection("contraceptive_users").document(phone_number).get()
                if user_doc.exists:
                    data = user_doc.to_dict() or {}
                    status = data.get("method_match_status")
                    if data.get("method_match_pending") or status in ("queued", "pending"):
                        return _t(lang, "still_processing")
                    if status == "failed":
                        return _t(lang, "match_error")
                    method = data.get("matched_method")
                    if method:
                        short = method[:120] + ("..." if len(method) > 120 else "")
                        return f"END {short}"
            except Exception:
                pass
        return _t(lang, "no_match")
    if choice == "4":
        return _t(lang, "hotline")

    return _t(lang, "invalid")
