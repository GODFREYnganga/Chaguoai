"""Security helpers for admin sessions and Twilio webhooks."""

from __future__ import annotations

import logging
import os

from flask import jsonify, request, session
from twilio.request_validator import RequestValidator

logger = logging.getLogger(__name__)


def app_env() -> str:
    """Return the active deployment environment name."""
    return os.environ.get("APP_ENV") or os.environ.get("FLASK_ENV", "development")


def _twilio_signature_disabled() -> bool:
    return os.environ.get("DISABLE_TWILIO_SIGNATURE_VALIDATION", "").strip() == "1"


def _twilio_validation_urls() -> list[str]:
    """Build candidate request URLs Twilio may have used when signing the webhook."""
    urls: list[str] = []
    seen: set[str] = set()

    def add(url: str | None) -> None:
        if not url or url in seen:
            return
        seen.add(url)
        urls.append(url)

    public_url = (os.environ.get("PUBLIC_BASE_URL") or os.environ.get("BASE_URL") or "").strip()
    if public_url:
        add(f"{public_url.rstrip('/')}{request.path}")

    add(request.url)

    forwarded_proto = (request.headers.get("X-Forwarded-Proto") or "https").split(",")[0].strip()
    forwarded_host = (
        request.headers.get("X-Forwarded-Host")
        or request.headers.get("Host")
        or ""
    ).split(",")[0].strip()
    if forwarded_host and not forwarded_host.startswith("127.0.0.1"):
        add(f"{forwarded_proto}://{forwarded_host}{request.path}")
        if request.query_string:
            add(f"{forwarded_proto}://{forwarded_host}{request.full_path.rstrip('?')}")

    return urls


def twilio_signature_valid() -> bool:
    """Validate the Twilio webhook signature for the current request."""
    env = app_env().lower()
    is_prod = env in {"production", "prod"}
    auth_token = (os.environ.get("TWILIO_AUTH_TOKEN") or "").strip()

    if _twilio_signature_disabled() and not is_prod:
        return True

    if not auth_token:
        if is_prod:
            logger.error("TWILIO_AUTH_TOKEN is not set in production")
            return False
        logger.warning("TWILIO_AUTH_TOKEN is unset; skipping Twilio signature validation in %s", env)
        return True

    signature = (request.headers.get("X-Twilio-Signature") or "").strip()
    if not signature:
        logger.warning("Twilio webhook missing X-Twilio-Signature header")
        return False

    validator = RequestValidator(auth_token)
    params = request.form
    for url in _twilio_validation_urls():
        if validator.validate(url, params, signature):
            return True

    if not is_prod:
        logger.warning(
            "Twilio signature rejected. Tried URLs: %s. "
            "Set PUBLIC_BASE_URL to your exact ngrok host (no /whatsapp path) and restart, "
            "or set DISABLE_TWILIO_SIGNATURE_VALIDATION=1 for local dev.",
            _twilio_validation_urls(),
        )
    return False


def require_admin():
    """Return an error response when the admin session is missing."""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    return None
