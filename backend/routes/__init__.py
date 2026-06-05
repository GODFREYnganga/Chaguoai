"""Register HTTP route blueprints on the Flask application."""

from __future__ import annotations

from route_blueprints import register_blueprints as _register_blueprints

from routes import admin as admin_routes
from routes import provider as provider_routes
from routes import public as public_routes


def _build_views() -> dict:
    return {
        "index": public_routes.index,
        "health": public_routes.health,
        "webhook": public_routes.webhook,
        "ussd": public_routes.ussd,
        "api_geography_countries": public_routes.api_geography_countries,
        "admin_login_page": admin_routes.admin_login_page,
        "admin_portal": admin_routes.admin_portal,
        "api_admin_login": admin_routes.api_admin_login,
        "admin_logout": admin_routes.admin_logout,
        "admin_stats": admin_routes.admin_stats,
        "admin_export_clients": admin_routes.admin_export_clients,
        "admin_events": admin_routes.admin_events,
        "admin_pending_providers": admin_routes.admin_pending_providers,
        "admin_approve_provider": admin_routes.admin_approve_provider,
        "provider_dashboard": provider_routes.provider_dashboard,
        "provider_login": provider_routes.provider_login,
        "provider_register": provider_routes.provider_register,
        "provider_register_confirmation": provider_routes.provider_register_confirmation,
        "api_provider_register": provider_routes.api_provider_register,
        "api_provider_login": provider_routes.api_provider_login,
        "api_provider_logout": provider_routes.api_provider_logout,
        "api_provider_me": provider_routes.api_provider_me,
        "api_provider_roster": provider_routes.api_provider_roster,
        "api_provider_client_detail": provider_routes.api_provider_client_detail,
        "api_provider_side_effects": provider_routes.api_provider_side_effects,
        "api_provider_methods": provider_routes.api_provider_methods,
        "api_provider_method_question": provider_routes.api_provider_method_question,
        "api_provider_select_method": provider_routes.api_provider_select_method,
        "api_provider_create_referral": provider_routes.api_provider_create_referral,
        "api_provider_update_referral": provider_routes.api_provider_update_referral,
        "api_provider_send_selection_message": provider_routes.api_provider_send_selection_message,
        "api_provider_compose_followup": provider_routes.api_provider_compose_followup,
        "api_provider_client_followups": provider_routes.api_provider_client_followups,
        "api_provider_followups": provider_routes.api_provider_followups,
        "api_provider_run_followup_automation": provider_routes.api_provider_run_followup_automation,
        "api_provider_analytics_summary": provider_routes.api_provider_analytics_summary,
        "api_provider_model_training_events": provider_routes.api_provider_model_training_events,
        "api_provider_clinical_review": provider_routes.api_provider_clinical_review,
        "api_provider_followup_outcome": provider_routes.api_provider_followup_outcome,
        "api_provider_mec_query": provider_routes.api_provider_mec_query,
        "api_provider_submit_triage": provider_routes.api_provider_submit_triage,
        "api_provider_triage_result": provider_routes.api_provider_triage_result,
    }


def register_blueprints(app) -> None:
    """Wire route handlers from submodules onto the Flask app."""
    _register_blueprints(app, _build_views())
