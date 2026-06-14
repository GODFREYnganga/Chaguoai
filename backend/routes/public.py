"""Public HTTP routes: health, WhatsApp webhook, USSD, geography API."""

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


def index():
    return "Contraception DSS Backend is running. Access /admin or /provider for dashboards."

def health():
    checks = run_health_checks()
    status_code = 200 if checks.get("overall", {}).get("ok") else 503
    return jsonify(checks), status_code
def webhook():
    if not twilio_signature_valid():
        return "Invalid Twilio signature", 403
    incoming_msg = extract_whatsapp_reply(request.values)
    user_phone = request.values.get('From', '')
    to_number = request.values.get('To', '')
    
    thread = threading.Thread(
        target=process_webhook_background,
        args=(incoming_msg, user_phone, to_number)
    )
    thread.start()
    return str(MessagingResponse())
def ussd():
    session_id = request.values.get('sessionId')
    service_code = request.values.get('serviceCode')
    phone_number = request.values.get('phoneNumber')
    text = request.values.get('text')
    return handle_ussd_request(session_id, service_code, phone_number, text, db=get_db())
def api_geography_countries():
    """Canonical country list for provider portal dropdown (analytics only)."""
    return jsonify({"countries": countries_for_api()})

