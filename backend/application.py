"""Flask application factory for ChaguoAI."""

from __future__ import annotations

import os
from flask import Flask

from env_loader import load_backend_dotenv

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
from twilio_messaging import TWILIO_TEMPLATES, verify_twilio_credentials

load_backend_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "dashboard"))
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
    dev_secret = "chaguoai-dev-only-secret"
    app.secret_key = os.environ.get("FLASK_SECRET_KEY") or dev_secret
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=app_env.lower() in {"production", "prod"},
    )
    if not os.environ.get("FLASK_SECRET_KEY"):
        print(
            "[Security] FLASK_SECRET_KEY is not set; using a stable local-dev default. "
            "Set FLASK_SECRET_KEY in backend/.env before production deploy."
        )
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
    disable_sig = os.environ.get("DISABLE_TWILIO_SIGNATURE_VALIDATION", "").strip() == "1"
    print(
        "[Twilio] Webhook signature check: "
        f"{'DISABLED (dev)' if disable_sig and app_env.lower() not in {'production', 'prod'} else 'ENABLED'}, "
        f"env={app_env}, PUBLIC_BASE_URL={os.environ.get('PUBLIC_BASE_URL') or '(unset)'}"
    )
    print(
        "[Auth] Provider portal: log in at http://127.0.0.1:%s/provider/login "
        "(use the same host you open in the browser — not localhost vs 127.0.0.1 mixed)."
        % os.environ.get("PORT", "8080")
    )
    init_firebase()
    verify_twilio_credentials()
    _log_whatsapp_template_status()
    register_blueprints(app)
    return app


app = create_app()
