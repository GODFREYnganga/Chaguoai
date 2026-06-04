"""One-off refactor helper: split legacy main.py into modular packages."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "mhc-backend"
MAIN = BACKEND / "main.py"

lines = MAIN.read_text(encoding="utf-8").splitlines(keepends=True)


def chunk(start: int, end: int) -> str:
    return "".join(lines[start - 1 : end])


# 1-based line slices from the pre-refactor layout.
SLICES = {
    "http_tail": (1017, 1075),
    "whatsapp_options": (194, 293),
    "whatsapp_i18n": (310, 446),
    "whatsapp_flow": (447, 814),
    "public_handlers": (120, 126, 296, 308, 816, 821, 848, 851),
    "admin_handlers": (825, 938),
    "provider_handlers": (942, 1747),
}

# Write helper modules first.
(BACKEND / "core").mkdir(exist_ok=True)
(BACKEND / "whatsapp").mkdir(exist_ok=True)
(BACKEND / "routes").mkdir(exist_ok=True)

http_utils = '''"""HTTP and Firestore serialization helpers."""

from __future__ import annotations

import datetime
import re
from typing import Any

from flask import jsonify

from db_client import get_db
from method_categories import classify_method_category_primary


def format_to_e164(phone, country_code="+254"):
    """Convert local phone formats (e.g. 07...) to E.164 (+254...)."""
    if not phone:
        return phone
    cleaned = re.sub(r"[^\\d+]", "", phone)
    if cleaned.startswith("0") and len(cleaned) == 10:
        return f"{country_code}{cleaned[1:]}"
    if cleaned.startswith(country_code[1:]) and not cleaned.startswith("+"):
        return f"+{cleaned}"
    if len(cleaned) <= 10 and not cleaned.startswith("+"):
        return f"{country_code}{cleaned}"
    return cleaned


def require_db():
    """Return a Firestore client or a Flask error response tuple."""
    db = get_db()
    if db is None:
        return None, (jsonify({"error": "Database is not initialized"}), 503)
    return db, None


def sanitize_provider(data):
    cleaned = dict(data or {})
    for field in ("password", "password_hash", "passwordHash"):
        cleaned.pop(field, None)
    return cleaned


def serialize_firestore_value(value):
    """Convert Firestore types to JSON-safe values for dashboard APIs."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError, OSError):
            pass
    if hasattr(value, "timestamp"):
        try:
            return datetime.datetime.utcfromtimestamp(value.timestamp()).isoformat() + "Z"
        except (TypeError, ValueError, OSError):
            pass
    if isinstance(value, dict):
        return {k: serialize_firestore_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [serialize_firestore_value(v) for v in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def extract_method_snippet(text, limit=120):
    if not text:
        return "Pending"
    cleaned = re.sub(r"\\s+", " ", str(text)).strip()
    match = re.search(r"\\*([^*]+)\\*", cleaned)
    if match:
        return match.group(1).strip()[:limit]
    for keyword in ("Implant", "IUD", "Injection", "Pill", "Condom", "Injectable", "DIU"):
        if keyword.lower() in cleaned.lower():
            return keyword
    return cleaned[:limit] + ("…" if len(cleaned) > limit else "")


def provider_client_summary(doc) -> dict:
    u = serialize_firestore_value(doc.to_dict())
    u["id"] = doc.id
    u["phone"] = doc.id
    matched = u.get("matched_method") or u.get("latest_recommendation") or ""
    u["method_snippet"] = extract_method_snippet(matched)
    u["method_category_primary"] = (
        u.get("method_category_primary") or classify_method_category_primary(matched)
    )
    u["channel"] = u.get("source") or ("provider" if u.get("triage_status") else "whatsapp")
    u["registered_at"] = serialize_firestore_value(u.get("registered_at") or u.get("created_at"))
    u["completed_at"] = serialize_firestore_value(
        u.get("method_match_completed_at") or u.get("triage_completed_at")
    )
    if u.get("method_match_status") == "completed" or u.get("triage_status") == "completed":
        u["match_status"] = "completed"
    elif u.get("method_match_status") == "failed" or u.get("triage_status") == "failed":
        u["match_status"] = "failed"
    elif u.get("triage_status") in ("queued", "processing"):
        u["match_status"] = u.get("triage_status")
    elif matched:
        u["match_status"] = "completed"
    else:
        u["match_status"] = "in_progress"
    return u
'''

(BACKEND / "core" / "http_utils.py").write_text(http_utils, encoding="utf-8")

security_utils = '''"""Security helpers for admin, provider, and Twilio webhooks."""

from __future__ import annotations

import os

from flask import jsonify, request, session
from twilio.request_validator import RequestValidator

from app_config import ADMIN_CODE


def app_env() -> str:
    return os.environ.get("APP_ENV") or os.environ.get("FLASK_ENV", "development")


def twilio_signature_valid() -> bool:
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    env = app_env().lower()
    if not auth_token:
        return env not in {"production", "prod"}
    if os.environ.get("DISABLE_TWILIO_SIGNATURE_VALIDATION") == "1":
        return env not in {"production", "prod"}
    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature:
        return False
    public_url = os.environ.get("PUBLIC_BASE_URL") or os.environ.get("BASE_URL")
    url = f"{public_url.rstrip('/')}{request.path}" if public_url else request.url
    return RequestValidator(auth_token).validate(url, request.form, signature)


def require_admin():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    return None
'''

(BACKEND / "core" / "security_utils.py").write_text(security_utils, encoding="utf-8")

(BACKEND / "core" / "__init__.py").write_text('"""Shared backend utilities."""\n', encoding="utf-8")

whatsapp_options = chunk(194, 293)
whatsapp_i18n = chunk(310, 446)
whatsapp_flow_body = chunk(447, 814)

# Fix references in extracted chunks
whatsapp_options = whatsapp_options.replace("db.collection", "get_db().collection")
whatsapp_flow_body = whatsapp_flow_body.replace("\ndb.", "\nget_db().")

constants_header = '''"""WhatsApp survey menus, translations, and conversational constants."""

from __future__ import annotations

'''
helpers_header = '''"""WhatsApp UI helpers used by the inbound webhook flow."""

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

from whatsapp.constants import (
    LANGUAGE_OPTIONS,
    MAIN_MENU_OPTIONS,
    STRINGS,
)

'''
flow_header = '''"""Background WhatsApp webhook processing."""

from __future__ import annotations

import threading
import traceback

from app_config import METHOD_MATCH_FALLBACK
from clinical_pipeline import generate_whatsapp_chat_reply
from db_client import get_db
from followup_tasks import attach_client_followup_reply
from twilio_messaging import TWILIO_NUMBER, send_whatsapp_message
from whatsapp.constants import LANGUAGE_ALIASES, LANGUAGES, STRINGS
from whatsapp.helpers import (
    dispatch_whatsapp_method_match,
    extract_whatsapp_reply,
    get_user_state,
    option_selected,
    question_body,
    send_language_menu,
    send_main_menu,
    send_whatsapp_buttons,
    send_whatsapp_list_picker,
)
from whatsapp_helpers import send_long_whatsapp_message
from geography import (
    admin_area_prompt,
    build_admin_area_firestore_fields,
    build_country_firestore_fields,
    country_confirm_prompt,
    country_prompt,
    invalid_location_prompt,
    is_valid_country_input,
    is_valid_location_input,
    normalize_country,
    normalize_admin_area,
)
from core.http_utils import format_to_e164

'''

(BACKEND / "whatsapp" / "constants.py").write_text(constants_header + whatsapp_i18n + "\n" + whatsapp_options.replace("db.collection", "get_db().collection"), encoding="utf-8")

# Move MAIN_MENU etc that were before i18n - options chunk has MAIN_MENU at start
# Re-read: options 194-293 has MAIN_MENU, helpers. i18n 310+ has LANGUAGES STRINGS
# constants should be options lines that are dicts + i18n block
constants_content = chunk(194, 216) + "\n" + chunk(310, 446)
(BACKEND / "whatsapp" / "constants.py").write_text(constants_header + constants_content, encoding="utf-8")

helpers_content = chunk(218, 293)
helpers_content = helpers_content.replace("db.collection", "get_db().collection")
(BACKEND / "whatsapp" / "helpers.py").write_text(helpers_header + helpers_content, encoding="utf-8")

flow_body_fixed = whatsapp_flow_body.replace("db.", "get_db().")
(BACKEND / "whatsapp" / "flow.py").write_text(flow_header + "def process_webhook_background(incoming_msg, user_phone, to_number):\n" + flow_body_fixed.split("def process_webhook_background", 1)[1], encoding="utf-8")

print("Wrote core/ and whatsapp/ modules")
