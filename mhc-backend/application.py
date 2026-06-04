"""Flask application factory for ChaguoAI."""

from __future__ import annotations

import os
import secrets

from dotenv import load_dotenv
from flask import Flask

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
except ImportError:
    Limiter = None
    get_remote_address = None

try:
    from flask_talisman import Talisman
except ImportError:
    Talisman = None

from db_client import init_firebase
from routes import register_blueprints
from twilio_messaging import TWILIO_TEMPLATES

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "mhc-dashboard"))
STATIC_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "static"))


def _log_whatsapp_template_status() -> None:
    status = TWILIO_TEMPLATES.status_report()
    print(f"[WhatsApp Templates] {' '.join(f'{k}={v}' for k, v in status.items())}")
    missing = TWILIO_TEMPLATES.missing_for_survey()
    if missing:
        print("[WhatsApp Templates] Missing SIDs — some questions will use text menus:")
        for item in missing:
            print(f"  - {item}")
        print("  See docs/twilio_content_templates.md for setup steps.")


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
    app_env = os.environ.get("APP_ENV") or os.environ.get("FLASK_ENV", "development")
    app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_urlsafe(48)
    if not os.environ.get("FLASK_SECRET_KEY"):
        print("[Security] FLASK_SECRET_KEY is not set; using an ephemeral development secret.")
    if app_env.lower() in {"production", "prod"} and not os.environ.get("FLASK_SECRET_KEY"):
        raise RuntimeError("FLASK_SECRET_KEY must be set in production.")
    if Talisman:
        Talisman(app, content_security_policy=None, force_https=app_env.lower() in {"production", "prod"})
    if Limiter and get_remote_address:
        Limiter(
            get_remote_address,
            app=app,
            default_limits=[os.environ.get("APP_RATE_LIMIT", "300 per hour")],
        )
    print(f"[DEBUG] Starting initialization. Port: {os.environ.get('PORT', '8080')}")
    init_firebase()
    _log_whatsapp_template_status()
    register_blueprints(app)
    return app


app = create_app()
