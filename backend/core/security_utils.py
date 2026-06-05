"""Security helpers for admin sessions and Twilio webhooks."""

from __future__ import annotations

import os

from flask import jsonify, request, session
from twilio.request_validator import RequestValidator


def app_env() -> str:
    """Return the active deployment environment name."""
    return os.environ.get("APP_ENV") or os.environ.get("FLASK_ENV", "development")


def twilio_signature_valid() -> bool:
    """Validate the Twilio webhook signature for the current request."""
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
    """Return an error response when the admin session is missing."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    return None
