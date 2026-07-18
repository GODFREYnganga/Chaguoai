"""WhatsApp helper functions for menus and method match dispatch."""

from __future__ import annotations

import threading

from db_client import get_db
from method_match_tasks import process_whatsapp_method_match_job
from task_queue import (
    TRIAGE_JOB_FAILURE_TTL_SECONDS,
    TRIAGE_JOB_RESULT_TTL_SECONDS,
    TRIAGE_JOB_TIMEOUT_SECONDS,
    get_triage_queue,
)
from twilio_messaging import send_whatsapp_options
from user_profile_mapper import serializable_user_snapshot
from whatsapp.constants import LANGUAGE_OPTIONS, MAIN_MENU_OPTIONS, STRINGS

def get_user_state(phone):
    doc = get_db().collection('contraceptive_users').document(phone).get()
    if doc.exists:
        return doc.to_dict()
    return None

def send_whatsapp_buttons(from_number, to_number, body_text, buttons):
    send_whatsapp_options(from_number, to_number, body_text, buttons)

def send_whatsapp_list_picker(from_number, to_number, body_text, options, button_text="Choose"):
    send_whatsapp_options(from_number, to_number, body_text, options, button_text=button_text)

def dispatch_whatsapp_method_match(user_phone, to_number, lang, user_snapshot):
    """Queue Method Match generation (Redis worker) with inline thread fallback."""
    payload = serializable_user_snapshot(user_snapshot)
    payload["phone"] = user_phone
    payload["language"] = lang
    payload["stage"] = "REGISTERED"
    payload["method_match_pending"] = True

    get_db().collection("contraceptive_users").document(user_phone).update({
        "method_match_status": "queued",
    })

    try:
        job = get_triage_queue().enqueue_call(
            func=process_whatsapp_method_match_job,
            args=(user_phone, to_number, lang, payload),
            timeout=TRIAGE_JOB_TIMEOUT_SECONDS,
            result_ttl=TRIAGE_JOB_RESULT_TTL_SECONDS,
            failure_ttl=TRIAGE_JOB_FAILURE_TTL_SECONDS,
        )
        print(f"[{user_phone}] Queued method match job {job.id}")
    except Exception as exc:
        print(f"[{user_phone}] Redis queue unavailable ({exc}); running inline worker thread")
        threading.Thread(
            target=process_whatsapp_method_match_job,
            args=(user_phone, to_number, lang, payload),
            daemon=True,
        ).start()

def extract_whatsapp_reply(form):
    return (
        form.get('ButtonPayload')
        or form.get('ListId')
        or form.get('ButtonText')
        or form.get('ListTitle')
        or form.get('Body')
        or ''
    ).strip()

def option_selected(message, option_number, *keywords):
    msg = str(message or '').lower().strip()
    if msg == str(option_number):
        return True
    return any(keyword in msg for keyword in keywords)

def question_body(text):
    return str(text).split("\n", 1)[0]

def send_main_menu(from_number, to_number, lang, greeting=None):
    s = STRINGS.get(lang, STRINGS["english"])
    menu_text = s["menu"]
    if greeting:
        menu_text = f"{greeting}{menu_text}"
    menu_options = MAIN_MENU_OPTIONS.get(lang, MAIN_MENU_OPTIONS["english"])
    send_whatsapp_list_picker(from_number, to_number, menu_text, menu_options, "Menu")

def send_language_menu(from_number, to_number):
    send_whatsapp_list_picker(
        from_number,
        to_number,
        "Welcome to ChaguoAI. Please select your preferred language.",
        LANGUAGE_OPTIONS,
        "Language"
    )
