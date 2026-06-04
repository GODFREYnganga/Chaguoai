"""Build blueprint route modules from extracted handler bodies."""

from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "mhc-backend"


def read(name: str) -> str:
    return (BACKEND / name).read_text(encoding="utf-8")


def patch_provider(body: str) -> str:
    replacements = [
        ("_require_db()", "require_db()"),
        ("db_error = require_db()\n    if db_error:\n        return db_error", "db, db_error = require_db()\n    if db_error:\n        return db_error"),
        ("_sanitize_provider", "sanitize_provider"),
        ("serialize_firestore_value", "serialize_firestore_value"),
        ("_provider_client_summary", "provider_client_summary"),
        ("_provider_role", "provider_role"),
    ]
    for old, new in replacements:
        body = body.replace(old, new)
    # require_db used as single return - fix pattern in file
    body = body.replace(
        "    db_error = require_db()\n    if db_error:\n        return db_error\n",
        "    db, db_error = require_db()\n    if db_error:\n        return db_error\n",
    )
    return body


def patch_admin(body: str) -> str:
    body = body.replace("_require_admin()", "require_admin()")
    body = body.replace(
        "    db_error = _require_db()\n    if db_error:\n        return db_error\n",
        "    db, db_error = require_db()\n    if db_error:\n        return db_error\n",
    )
    body = body.replace("_require_db()", "require_db()")
    body = body.replace("url_for('admin_login_page')", "url_for('admin.admin_login_page')")
    body = body.replace("url_for(\"admin_login_page\")", "url_for('admin.admin_login_page')")
    return body


public_header = '''"""Public HTTP routes: health, WhatsApp webhook, USSD, geography API."""

from __future__ import annotations

import threading

from flask import Blueprint, jsonify, request
from twilio.twiml.messaging_response import MessagingResponse

from core.security_utils import twilio_signature_valid
from db_client import get_db
from geography import countries_for_api
from health_check import run_health_checks
from ussd_logic import handle_ussd_request
from whatsapp.flow import process_webhook_background
from whatsapp.helpers import extract_whatsapp_reply

public_bp = Blueprint("public", __name__)


'''

public_body = read("routes/_public_body.py")
public_body = public_body.replace("_twilio_signature_valid()", "twilio_signature_valid()")
public_body = public_body.replace("handle_ussd_request(session_id, service_code, phone_number, text, db=db)", "handle_ussd_request(session_id, service_code, phone_number, text, db=get_db())")

admin_header = '''"""Admin portal and analytics routes."""

from __future__ import annotations

import json
import time

from flask import Blueprint, Response, jsonify, redirect, render_template, request, session, url_for

from admin_analytics import build_admin_stats, export_clients_csv
from app_config import ADMIN_CODE
from core.http_utils import require_db
from core.security_utils import require_admin
from db_client import get_db
from geography import countries_for_api

admin_bp = Blueprint("admin", __name__)


'''

admin_body = patch_admin(read("routes/_admin_body.py"))

provider_header = '''"""Provider portal, client care, follow-up, and triage routes."""

from __future__ import annotations

import datetime
import re

from firebase_admin import firestore
from flask import Blueprint, jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from analytics_service import build_analytics_summary, export_model_training_events
from app_config import WEB_PROVIDER_MAX_OUTPUT_TOKENS
from audit_trail import fetch_audit_trail, record_audit_event
from care_plan import build_client_timeline, transition_for_followup_sent
from client_messages import compose_followup_reminder
from core.http_utils import (
    extract_method_snippet,
    provider_client_summary,
    require_db,
    sanitize_provider,
    serialize_firestore_value,
)
from db_client import get_db
from followup_tasks import run_followup_automation
from fhir_utils import to_fhir_patient
from gemini_client import generate_gemini_text
from method_library import all_methods, get_method_info
from method_selection import (
    build_selection_client_message,
    create_referral,
    record_followup_outcome,
    select_method,
    update_referral_status,
)
from rag_ingestor import get_retriever
from rag_prompt import build_system_prompt, build_web_clinical_instruction
from recommendation_packet import build_recommendation_packet
from response_cards import resolve_method_cards
from task_queue import (
    TRIAGE_JOB_FAILURE_TTL_SECONDS,
    TRIAGE_JOB_RESULT_TTL_SECONDS,
    TRIAGE_JOB_TIMEOUT_SECONDS,
    get_triage_queue,
)
from triage_tasks import process_provider_triage_job
from twilio_messaging import send_whatsapp_with_sms_fallback

provider_bp = Blueprint("provider", __name__)


def provider_role(provider_id: str) -> str:
    doc = get_db().collection("providers").document(provider_id).get()
    return (doc.to_dict() or {}).get("role", "")


'''

provider_body = patch_provider(read("routes/_provider_body.py"))
provider_body = provider_body.replace("_provider_role", "provider_role")
provider_body = provider_body.replace("db.collection", "get_db().collection")
provider_body = provider_body.replace("db=db", "db=get_db()")

admin_body = admin_body.replace("db.collection", "get_db().collection")

(BACKEND / "routes" / "public.py").write_text(public_header + public_body, encoding="utf-8")
(BACKEND / "routes" / "admin.py").write_text(admin_header + admin_body, encoding="utf-8")
(BACKEND / "routes" / "provider.py").write_text(provider_header + provider_body, encoding="utf-8")

print("route modules written")
