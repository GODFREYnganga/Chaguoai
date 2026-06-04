from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "mhc-backend"


def replace_db_refs(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = text.replace("db=db", "db=get_db()")
    text = text.replace("db.collection", "get_db().collection")
    text = text.replace("db is None", "get_db() is None")
    path.write_text(text, encoding="utf-8")


flow_imports = '''"""Inbound WhatsApp conversation state machine."""

from __future__ import annotations

from flask import session

from firebase_admin import firestore

from app_config import METHOD_MATCH_FALLBACK
from clinical_pipeline import generate_whatsapp_chat_reply
from db_client import get_db
from followup_tasks import attach_client_followup_reply
from geography import (
    admin_area_prompt,
    build_admin_area_firestore_fields,
    build_country_firestore_fields,
    country_confirm_prompt,
    country_prompt,
    invalid_location_prompt,
    is_valid_country_input,
    is_valid_location_input,
    normalize_admin_area,
    normalize_country,
)
from twilio_messaging import send_whatsapp_message
from whatsapp.constants import (
    CHILDREN_COUNT_OPTIONS,
    HEALTH_CONDITION_OPTIONS,
    LANGUAGE_ALIASES,
    LANGUAGES,
    METHOD_AVOID_OPTIONS,
    PARTNER_SUPPORT_OPTIONS,
    STRINGS,
    YES_NO_OPTIONS,
)
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

'''

flow_path = BACKEND / "whatsapp" / "flow.py"
flow_body = flow_path.read_text(encoding="utf-8")
if "def process_webhook_background" in flow_body:
    flow_body = flow_body.split("def process_webhook_background", 1)[1]
    flow_path.write_text(flow_imports + "def process_webhook_background" + flow_body, encoding="utf-8")

replace_db_refs(BACKEND / "whatsapp" / "helpers.py")
replace_db_refs(BACKEND / "whatsapp" / "flow.py")

# Remove duplicate geography route from admin extract
admin_path = BACKEND / "routes" / "_admin_body.py"
admin_text = admin_path.read_text(encoding="utf-8")
marker = "def api_geography_countries"
if marker in admin_text:
    admin_text = admin_text.split(marker, 1)[0].rstrip() + "\n"
    admin_path.write_text(admin_text, encoding="utf-8")

print("finalize complete")
