"""Flask blueprint registration for ChaguoAI backend routes.

Route declarations live here so ``main.py`` can focus on application setup and
workflow handlers. The handlers are passed in as a mapping to preserve existing
behavior while still giving each route group a clear ownership boundary.
"""

from flask import Blueprint


def _add(bp, rule, endpoint, view_func, methods=None):
    """Register one URL rule on a blueprint."""
    bp.add_url_rule(rule, endpoint, view_func, methods=methods)


def _view(views, name):
    """Fetch a route handler by name and fail loudly during startup if missing."""
    try:
        return views[name]
    except KeyError as exc:
        raise RuntimeError(f"Missing Flask route handler: {name}") from exc


def create_public_blueprint(views):
    """Create routes for health checks, WhatsApp, and USSD entry points."""
    bp = Blueprint("public", __name__)
    _add(bp, "/", "index", _view(views, "index"))
    _add(bp, "/health", "health", _view(views, "health"), methods=["GET"])
    _add(bp, "/webhook", "webhook", _view(views, "webhook"), methods=["POST"])
    _add(bp, "/whatsapp", "webhook_whatsapp", _view(views, "webhook"), methods=["POST"])
    _add(bp, "/ussd", "ussd", _view(views, "ussd"), methods=["POST"])
    _add(bp, "/api/geography/countries", "api_geography_countries", _view(views, "api_geography_countries"), methods=["GET"])
    return bp


def create_admin_blueprint(views):
    """Create admin portal, approval, analytics, export, and SSE routes."""
    bp = Blueprint("admin", __name__)
    _add(bp, "/admin", "admin_login_page", _view(views, "admin_login_page"))
    _add(bp, "/admin/portal", "admin_portal", _view(views, "admin_portal"))
    _add(bp, "/api/admin/login", "api_admin_login", _view(views, "api_admin_login"), methods=["POST"])
    _add(bp, "/admin/logout", "admin_logout", _view(views, "admin_logout"))
    _add(bp, "/api/admin/stats", "admin_stats", _view(views, "admin_stats"), methods=["GET"])
    _add(bp, "/api/admin/export/clients.csv", "admin_export_clients", _view(views, "admin_export_clients"), methods=["GET"])
    _add(bp, "/api/admin/events", "admin_events", _view(views, "admin_events"), methods=["GET"])
    _add(bp, "/api/admin/pending_providers", "admin_pending_providers", _view(views, "admin_pending_providers"), methods=["GET"])
    _add(
        bp,
        "/api/admin/approve_provider/<provider_id>",
        "admin_approve_provider",
        _view(views, "admin_approve_provider"),
        methods=["POST"],
    )
    return bp


def create_provider_blueprint(views):
    """Create provider portal, client care, follow-up, analytics, and triage routes."""
    bp = Blueprint("provider", __name__)
    _add(bp, "/provider", "provider_dashboard", _view(views, "provider_dashboard"))
    _add(bp, "/provider/login", "provider_login", _view(views, "provider_login"))
    _add(bp, "/provider/register", "provider_register", _view(views, "provider_register"))
    _add(bp, "/provider/register/confirmation", "provider_register_confirmation", _view(views, "provider_register_confirmation"))
    _add(bp, "/api/provider/register", "api_provider_register", _view(views, "api_provider_register"), methods=["POST"])
    _add(bp, "/api/provider/login", "api_provider_login", _view(views, "api_provider_login"), methods=["POST"])
    _add(bp, "/api/provider/logout", "api_provider_logout", _view(views, "api_provider_logout"), methods=["POST"])
    _add(bp, "/api/provider/me", "api_provider_me", _view(views, "api_provider_me"), methods=["GET"])
    _add(bp, "/api/provider/roster", "api_provider_roster", _view(views, "api_provider_roster"), methods=["GET"])
    _add(bp, "/api/provider/clients/<path:phone>", "api_provider_client_detail", _view(views, "api_provider_client_detail"), methods=["GET"])
    _add(bp, "/api/provider/side_effects", "api_provider_side_effects", _view(views, "api_provider_side_effects"), methods=["GET"])
    _add(bp, "/api/provider/methods", "api_provider_methods", _view(views, "api_provider_methods"), methods=["GET"])
    _add(bp, "/api/provider/clients/<path:phone>/methods/question", "api_provider_method_question", _view(views, "api_provider_method_question"), methods=["POST"])
    _add(bp, "/api/provider/clients/<path:phone>/select_method", "api_provider_select_method", _view(views, "api_provider_select_method"), methods=["POST"])
    _add(bp, "/api/provider/clients/<path:phone>/referral", "api_provider_create_referral", _view(views, "api_provider_create_referral"), methods=["POST"])
    _add(
        bp,
        "/api/provider/clients/<path:phone>/referrals/<referral_id>",
        "api_provider_update_referral",
        _view(views, "api_provider_update_referral"),
        methods=["PATCH"],
    )
    _add(
        bp,
        "/api/provider/clients/<path:phone>/send_selection_message",
        "api_provider_send_selection_message",
        _view(views, "api_provider_send_selection_message"),
        methods=["POST"],
    )
    _add(bp, "/api/provider/clients/<path:phone>/compose_followup", "api_provider_compose_followup", _view(views, "api_provider_compose_followup"), methods=["POST"])
    _add(bp, "/api/provider/clients/<path:phone>/followups", "api_provider_client_followups", _view(views, "api_provider_client_followups"), methods=["GET"])
    _add(bp, "/api/provider/followups", "api_provider_followups", _view(views, "api_provider_followups"), methods=["GET"])
    _add(bp, "/api/provider/followups/run_automation", "api_provider_run_followup_automation", _view(views, "api_provider_run_followup_automation"), methods=["POST"])
    _add(bp, "/api/provider/analytics/summary", "api_provider_analytics_summary", _view(views, "api_provider_analytics_summary"), methods=["GET"])
    _add(bp, "/api/provider/analytics/model_training_events", "api_provider_model_training_events", _view(views, "api_provider_model_training_events"), methods=["GET"])
    _add(bp, "/api/provider/clients/<path:phone>/clinical_review", "api_provider_clinical_review", _view(views, "api_provider_clinical_review"), methods=["GET"])
    _add(bp, "/api/provider/followups/<task_id>/outcome", "api_provider_followup_outcome", _view(views, "api_provider_followup_outcome"), methods=["POST"])
    _add(bp, "/api/provider/mec_query", "api_provider_mec_query", _view(views, "api_provider_mec_query"), methods=["POST"])
    _add(bp, "/api/provider/submit_triage", "api_provider_submit_triage", _view(views, "api_provider_submit_triage"), methods=["POST"])
    _add(bp, "/api/provider/triage_result/<job_id>", "api_provider_triage_result", _view(views, "api_provider_triage_result"), methods=["GET"])
    return bp


def register_blueprints(app, views):
    """Register all application blueprints."""
    app.register_blueprint(create_public_blueprint(views))
    app.register_blueprint(create_admin_blueprint(views))
    app.register_blueprint(create_provider_blueprint(views))
