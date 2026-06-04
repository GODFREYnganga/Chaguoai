"""Admin portal and analytics routes."""

from __future__ import annotations

import json
import time

from flask import Blueprint, Response, jsonify, redirect, render_template, request, session, url_for

from admin_analytics import build_admin_stats, export_clients_csv
from app_config import ADMIN_CODE
from core.http_utils import require_db, sanitize_provider
from core.security_utils import require_admin
from db_client import get_db

admin_bp = Blueprint("admin", __name__)


def admin_login_page():
    return render_template("admin_login.html")


def admin_portal():
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin.admin_login_page"))
    return render_template("admin_portal.html")


def api_admin_login():
    if not ADMIN_CODE:
        return jsonify({"success": False, "error": "Admin access code is not configured"}), 503
    data = request.json
    code = data.get("access_code")
    if code == ADMIN_CODE:
        session["admin_logged_in"] = True
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Invalid Access Code"}), 401


def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin.admin_login_page"))


def admin_stats():
    denied = require_admin()
    if denied:
        return denied
    db, db_error = require_db()
    if db_error:
        return db_error
    try:
        cohort = request.args.get("cohort", "all")
        return jsonify(build_admin_stats(db, cohort=cohort))
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500


def admin_export_clients():
    denied = require_admin()
    if denied:
        return denied
    db, db_error = require_db()
    if db_error:
        return db_error
    try:
        limit = min(int(request.args.get("limit", "5000")), 20000)
        users = []
        for doc in db.collection("contraceptive_users").limit(limit).stream():
            data = doc.to_dict() or {}
            data["phone"] = doc.id
            users.append(data)
        csv_body = export_clients_csv(users)
        return Response(
            csv_body,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=chaguoai_clients.csv"},
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"error": f"Invalid export request: {exc}"}), 400
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500


def admin_events():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    cohort = request.args.get("cohort", "all")
    db = get_db()

    def event_stream():
        while True:
            try:
                payload = build_admin_stats(db, cohort=cohort)
                yield f"event: stats\ndata: {json.dumps(payload, default=str)}\n\n"
            except GeneratorExit:
                break
            except (RuntimeError, TypeError, ValueError) as exc:
                yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"
            time.sleep(15)

    return Response(event_stream(), mimetype="text/event-stream")


def admin_pending_providers():
    denied = require_admin()
    if denied:
        return denied
    db, db_error = require_db()
    if db_error:
        return db_error
    providers = []
    for doc in db.collection("providers").where("status", "==", "pending").limit(200).stream():
        payload = sanitize_provider(doc.to_dict())
        payload["id"] = doc.id
        providers.append(payload)
    return jsonify({"providers": providers})


def admin_approve_provider(provider_id):
    denied = require_admin()
    if denied:
        return denied
    db, db_error = require_db()
    if db_error:
        return db_error
    db.collection("providers").document(provider_id).update({"status": "approved"})
    return jsonify({"success": True})
