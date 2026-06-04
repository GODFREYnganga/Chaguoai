import unittest

from flask import Flask

from route_blueprints import register_blueprints


def _handler(*args, **kwargs):
    return "ok"


class TestRouteBlueprints(unittest.TestCase):
    def test_registers_expected_route_groups(self):
        app = Flask(__name__)
        handler_names = [
            "index",
            "health",
            "webhook",
            "ussd",
            "api_geography_countries",
            "admin_login_page",
            "admin_portal",
            "api_admin_login",
            "admin_logout",
            "admin_stats",
            "admin_export_clients",
            "admin_events",
            "admin_pending_providers",
            "admin_approve_provider",
            "provider_dashboard",
            "provider_login",
            "provider_register",
            "api_provider_register",
            "api_provider_login",
            "api_provider_logout",
            "api_provider_me",
            "api_provider_roster",
            "api_provider_client_detail",
            "api_provider_side_effects",
            "api_provider_methods",
            "api_provider_method_question",
            "api_provider_select_method",
            "api_provider_create_referral",
            "api_provider_update_referral",
            "api_provider_send_selection_message",
            "api_provider_compose_followup",
            "api_provider_client_followups",
            "api_provider_followups",
            "api_provider_run_followup_automation",
            "api_provider_analytics_summary",
            "api_provider_model_training_events",
            "api_provider_clinical_review",
            "api_provider_followup_outcome",
            "api_provider_mec_query",
            "api_provider_submit_triage",
            "api_provider_triage_result",
        ]
        register_blueprints(app, {name: _handler for name in handler_names})

        rules = {str(rule) for rule in app.url_map.iter_rules()}
        self.assertIn("/webhook", rules)
        self.assertIn("/api/admin/stats", rules)
        self.assertIn("/api/provider/clients/<path:phone>/select_method", rules)
        self.assertIn("/api/provider/triage_result/<job_id>", rules)


if __name__ == "__main__":
    unittest.main()
