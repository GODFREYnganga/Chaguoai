"""Provider portal, client care, follow-up, and triage routes."""

from __future__ import annotations

import datetime
import json
import re

from firebase_admin import firestore
from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from admin_analytics import collect_safety_items
from analytics_service import build_analytics_summary, export_model_training_events
from app_config import WEB_PROVIDER_MAX_OUTPUT_TOKENS
from audit_trail import fetch_audit_trail, record_audit_event
from care_plan import build_client_timeline, transition_for_followup_sent
from client_messages import compose_followup_reminder
from core.http_utils import (
    extract_method_snippet,
    format_client_phone,
    provider_client_summary,
    require_db,
    resolve_client_phone,
    sanitize_provider,
    serialize_firestore_value,
)
from geography import admin_area_label, normalize_admin_area, normalize_country
from db_client import get_db
from followup_tasks import run_followup_automation
from fhir_utils import to_fhir_patient
from gemini_client import generate_gemini_text
from method_library import all_methods, get_method_info
from method_selection import (
    build_selection_client_message,
    create_referral,
    record_followup_outcome,
    select_method,
    update_referral_status,
)
from rag_ingestor import get_retriever
from rag_prompt import build_system_prompt, build_web_clinical_instruction
from recommendation_packet import build_recommendation_packet
from response_cards import resolve_method_cards
from task_queue import (
    TRIAGE_JOB_FAILURE_TTL_SECONDS,
    TRIAGE_JOB_RESULT_TTL_SECONDS,
    TRIAGE_JOB_TIMEOUT_SECONDS,
    get_triage_queue,
)
from twilio_messaging import TWILIO_NUMBER, send_whatsapp_with_sms_fallback

provider_bp = Blueprint("provider", __name__)


def provider_role(provider_id: str) -> str:
    doc = get_db().collection("providers").document(provider_id).get()
    return (doc.to_dict() or {}).get("role", "")


def provider_dashboard():
    if not session.get("provider_id"):
        return redirect("/provider/login")
    return render_template('provider_portal.html')

def provider_login():
    return render_template('provider_login.html')

def provider_register():
    return render_template('provider_register.html')


def provider_register_confirmation():
    return render_template('provider_register_confirmation.html')


def api_provider_register():
    db, db_error = require_db()
    if db_error:
        return db_error
    data = request.json or {}
    required = ("fullName", "email", "phone", "role", "credentials", "password")
    missing = [field for field in required if not str(data.get(field) or "").strip()]
    if missing:
        return jsonify({"success": False, "error": f"Missing required field(s): {', '.join(missing)}"}), 400
    password = str(data.get("password") or "")
    if len(password) < 8:
        return jsonify({"success": False, "error": "Password must be at least 8 characters"}), 400
    email = str(data.get("email") or "").strip().lower()
    existing = list(get_db().collection('providers').where(filter=firestore.FieldFilter('email', '==', email)).limit(1).stream())
    if existing:
        return jsonify({"success": False, "error": "A provider account already exists for this email"}), 409
    provider = {
        "fullName": str(data.get("fullName")).strip(),
        "email": email,
        "phone": str(data.get("phone")).strip(),
        "role": str(data.get("role")).strip(),
        "credentials": str(data.get("credentials")).strip(),
        "password_hash": generate_password_hash(password),
        "status": "pending",
        "created_at": firestore.SERVER_TIMESTAMP,
    }
    get_db().collection('providers').add(provider)
    return jsonify({
        "success": True,
        "message": "Application submitted. An administrator will review your account shortly.",
        "redirect": "/provider/register/confirmation",
    })

def api_provider_login():
    db, db_error = require_db()
    if db_error:
        return db_error
    data = request.json or {}
    email = str(data.get('email') or "").strip().lower()
    password = str(data.get("password") or "")
    if not email or not password:
        return jsonify({"success": False, "error": "Email and password are required"}), 400
    approved_docs = list(
        get_db().collection('providers')
        .where(filter=firestore.FieldFilter('email', '==', email))
        .where(filter=firestore.FieldFilter('status', '==', 'approved'))
        .limit(1)
        .stream()
    )
    if approved_docs:
        provider = approved_docs[0].to_dict() or {}
        password_hash = provider.get("password_hash")
        if password_hash and check_password_hash(password_hash, password):
            session['provider_id'] = approved_docs[0].id
            session.permanent = True
            return jsonify({"success": True, "role": provider.get('role')})

    pending_docs = list(
        get_db().collection('providers')
        .where(filter=firestore.FieldFilter('email', '==', email))
        .where(filter=firestore.FieldFilter('status', '==', 'pending'))
        .limit(1)
        .stream()
    )
    if pending_docs:
        provider = pending_docs[0].to_dict() or {}
        password_hash = provider.get("password_hash")
        if password_hash and check_password_hash(password_hash, password):
            return jsonify({
                "success": False,
                "error": "Your account is pending admin approval. Ask an admin to approve you at /admin.",
            }), 401

    return jsonify({"success": False, "error": "Invalid email or password"}), 401

def api_provider_logout():
    session.clear()
    return jsonify({"success": True})

def api_provider_me():
    pid = session.get('provider_id')
    if not pid: return jsonify({"error": "Unauthorized"}), 401
    db, db_error = require_db()
    if db_error:
        return db_error
    doc = get_db().collection('providers').document(pid).get()
    if not doc.exists: return jsonify({"error": "Not Found"}), 404
    return jsonify(sanitize_provider(doc.to_dict()))


def api_provider_roster():
    pid = session.get('provider_id')
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401

    users = []
    for doc in get_db().collection('contraceptive_users').where(
        filter=firestore.FieldFilter('assigned_provider_id', '==', pid)
    ).limit(500).stream():
        users.append(provider_client_summary(doc))
    return jsonify({"clients": users})


def api_provider_client_detail(phone):
    pid = session.get("provider_id")
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401

    phone = resolve_client_phone(phone)
    doc = get_db().collection("contraceptive_users").document(phone).get()
    if not doc.exists:
        return jsonify({"error": "Client not found"}), 404

    data = doc.to_dict() or {}
    if data.get("assigned_provider_id") != pid:
        return jsonify({"error": "Forbidden"}), 403

    client = provider_client_summary(doc)
    side_effects = []
    try:
        se_query = doc.reference.collection("side_effects").order_by(
            "timestamp", direction=firestore.Query.DESCENDING
        ).limit(10)
    except Exception:
        se_query = doc.reference.collection("side_effects").limit(10)
    for se in se_query.stream():
        item = serialize_firestore_value(se.to_dict())
        item["id"] = se.id
        item["at"] = serialize_firestore_value(item.get("timestamp"))
        side_effects.append(item)
    side_effects.sort(key=lambda x: x.get("at") or "", reverse=True)
    recommendation_text = client.get("matched_method") or client.get("latest_recommendation") or ""
    mec_summary = client.get("latest_mec_text") or client.get("latest_mec_result") or ""
    citations = client.get("recommendation_citations") or []
    stored_cards = client.get("method_cards") or []
    if stored_cards:
        method_cards = stored_cards
    else:
        method_cards, recommendation_text = resolve_method_cards(
            recommendation_text, mec_summary, citations
        )
    followups = []
    for task in get_db().collection("followup_tasks").where(
        filter=firestore.FieldFilter("phone", "==", phone)
    ).limit(200).stream():
        item = serialize_firestore_value(task.to_dict())
        item["id"] = task.id
        followups.append(item)
    followups.sort(key=lambda x: str(x.get("due_at") or ""))
    referrals = []
    for referral in doc.reference.collection("referrals").limit(50).stream():
        item = serialize_firestore_value(referral.to_dict())
        item["id"] = referral.id
        referrals.append(item)
    referrals.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    audit_trail = [serialize_firestore_value(event) for event in fetch_audit_trail(db=get_db(), phone=phone, limit=75)]
    packet = client.get("recommendation_packet") or build_recommendation_packet(
        client=client,
        recommendation_text=recommendation_text,
        mec_text=mec_summary,
        citations=citations,
        method_cards=method_cards,
    )
    timeline = build_client_timeline(
        client=client,
        followups=followups,
        side_effects=side_effects,
        referrals=referrals,
        audit_events=audit_trail,
    )

    return jsonify({
        "client": client,
        "recommendation": recommendation_text,
        "method_cards": method_cards,
        "recommendation_citations": client.get("recommendation_citations") or [],
        "mec_summary": client.get("latest_mec_text") or client.get("latest_mec_result") or "",
        "side_effects": side_effects,
        "followups": followups,
        "referrals": referrals,
        "audit_trail": audit_trail,
        "recommendation_packet": packet,
        "timeline": timeline,
    })


def api_provider_side_effects():
    pid = session.get("provider_id")
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401
    db, db_error = require_db()
    if db_error:
        return db_error
    items = collect_safety_items(db, provider_id=pid, limit=50)
    reports = [i for i in items if i.get("type") == "side_effect"]
    return jsonify({"reports": reports})


def api_provider_methods():
    pid = session.get("provider_id")
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"methods": all_methods()})


def api_provider_method_question(phone):
    pid = session.get("provider_id")
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json or {}
    method_name = data.get("method_name") or data.get("method") or ""
    question = data.get("question") or ""
    if not method_name or not question:
        return jsonify({"error": "method_name and question are required"}), 400

    phone = resolve_client_phone(phone)
    doc = get_db().collection("contraceptive_users").document(phone).get()
    if not doc.exists:
        return jsonify({"error": "Client not found"}), 404
    client = serialize_firestore_value(doc.to_dict())
    if client.get("assigned_provider_id") != pid:
        return jsonify({"error": "Forbidden"}), 403

    method = get_method_info(method_name)
    mec_text = client.get("latest_mec_text") or client.get("latest_mec_result") or ""
    try:
        retriever = get_retriever()
        chunks = retriever.retrieve(f"{method_name} {question} contraception counseling", top_k=3)
        context = retriever.format_context_for_llm(chunks)
        prompt = (
            "Answer this CHW clarification question concisely using the method facts, WHO MEC context, "
            "and retrieved guideline context. Keep it under 120 words. Include one source line.\n\n"
            f"Client: {json.dumps({k: client.get(k) for k in ['age', 'baby_under_6m', 'breastfeeding_only', 'health_conditions', 'hiv_status', 'smoke', 'sti_concern']})}\n"
            f"Method facts: {json.dumps(method)}\n"
            f"MEC context: {mec_text}\n"
            f"Guidelines: {context}\n"
            f"Question: {question}"
        )
        answer = generate_gemini_text(prompt, max_output_tokens=600, disable_thinking=True)
    except Exception as exc:
        print(f"Method question fallback: {exc}")
        answer = (
            f"{method['display_name']}: {method.get('how_it_works')} "
            f"Common side effects: {method.get('common_side_effects')} "
            f"Warning signs: {method.get('warning_signs')} "
            "Source: method counseling library and WHO MEC context."
        )
    return jsonify({
        "success": True,
        "method": method,
        "question": question,
        "answer": answer,
    })


def api_provider_select_method(phone):
    pid = session.get("provider_id")
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json or {}
    method_name = data.get("method") or data.get("method_name")
    if not method_name:
        return jsonify({"error": "Method is required"}), 400
    try:
        phone = resolve_client_phone(phone)
        result = select_method(
            db=get_db(),
            phone=phone,
            provider_id=pid,
            method_name=method_name,
            counseling=data.get("counseling") or {},
            referral=data.get("referral") or None,
            override_reason=data.get("override_reason") or "",
            safety_override_reason=data.get("safety_override_reason") or "",
            clinician_acknowledgment=bool(data.get("clinician_acknowledgment")),
        )
        return jsonify(serialize_firestore_value(result))
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def api_provider_create_referral(phone):
    pid = session.get("provider_id")
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json or {}
    method_name = data.get("method") or data.get("method_name") or "Selected method"
    try:
        phone = resolve_client_phone(phone)
        referral = create_referral(
            db=get_db(),
            phone=phone,
            provider_id=pid,
            method_name=method_name,
            referral=data,
        )
        return jsonify({"success": True, "referral": serialize_firestore_value(referral)})
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def api_provider_update_referral(phone, referral_id):
    pid = session.get("provider_id")
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json or {}
    try:
        result = update_referral_status(
            db=get_db(),
            phone=resolve_client_phone(phone),
            provider_id=pid,
            referral_id=referral_id,
            status=data.get("status") or "",
            note=data.get("note") or "",
        )
        return jsonify(serialize_firestore_value(result))
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def api_provider_send_selection_message(phone):
    pid = session.get("provider_id")
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json or {}
    phone = resolve_client_phone(phone)
    doc_ref = get_db().collection("contraceptive_users").document(phone)
    doc = doc_ref.get()
    if not doc.exists:
        return jsonify({"error": "Client not found"}), 404
    client = doc.to_dict() or {}
    if client.get("assigned_provider_id") != pid:
        return jsonify({"error": "Forbidden"}), 403

    method_name = data.get("method") or client.get("selected_method")
    if not method_name:
        return jsonify({"error": "Select a method before sending a message"}), 400

    referral = data.get("referral")
    if not referral and client.get("latest_referral_facility"):
        referral = {"facility_name": client.get("latest_referral_facility")}

    message = build_selection_client_message(
        client=client,
        method_name=method_name,
        referral=referral,
        next_followup=serialize_firestore_value(client.get("next_followup_at")),
    )
    delivery = send_whatsapp_with_sms_fallback(TWILIO_NUMBER, phone, message)
    doc_ref.set({
        "selection_message_status": delivery.get("status"),
        "selection_message_channel": delivery.get("channel"),
        "selection_message_error": delivery.get("error") or delivery.get("whatsapp_error") or "",
        "selection_message_sent_at": firestore.SERVER_TIMESTAMP,
        "latest_selection_message": message,
    }, merge=True)
    record_audit_event(
        db=get_db(),
        phone=phone,
        actor=pid,
        action="selection_message_sent",
        metadata={"method": method_name, "channel": delivery.get("channel"), "status": delivery.get("status")},
    )
    return jsonify({"success": delivery.get("status") == "sent", "delivery": delivery, "message": message})


def api_provider_compose_followup(phone):
    """Send one composed follow-up message to a client (WhatsApp/SMS)."""
    pid = session.get("provider_id")
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json or {}
    phone = resolve_client_phone(phone)
    doc_ref = get_db().collection("contraceptive_users").document(phone)
    doc = doc_ref.get()
    if not doc.exists:
        return jsonify({"error": "Client not found"}), 404
    client = doc.to_dict() or {}
    if client.get("assigned_provider_id") != pid:
        return jsonify({"error": "Forbidden"}), 403

    custom = (data.get("message") or "").strip()
    method_name = data.get("method") or client.get("selected_method") or "your method"
    reason = (data.get("reason") or "routine check-in").strip()
    if custom:
        message = custom
    else:
        message = compose_followup_reminder(
            client_name=client.get("name") or "",
            method_name=method_name,
            reason=reason,
        )

    delivery = send_whatsapp_with_sms_fallback(TWILIO_NUMBER, phone, message)
    active_task_id = ""
    for task in get_db().collection("followup_tasks").where(
        filter=firestore.FieldFilter("phone", "==", phone)
    ).limit(50).stream():
        task_data = task.to_dict() or {}
        if (task_data.get("status") or "due") in ("due", "pending"):
            active_task_id = task.id
            sent_at = datetime.datetime.now(datetime.timezone.utc)
            task.reference.set({
                "status": "sent" if delivery.get("status") == "sent" else "send_failed",
                "sent_at": sent_at,
                "response_due_at": sent_at + datetime.timedelta(hours=48),
                "attempts": int(task_data.get("attempts") or 0) + 1,
                "latest_message": message,
                "last_delivery": delivery,
            }, merge=True)
            break
    care_update = transition_for_followup_sent(
        active_task_id,
        datetime.datetime.now(datetime.timezone.utc),
    ) if active_task_id and delivery.get("status") == "sent" else {}
    doc_ref.set({
        "latest_followup_message": message,
        "latest_followup_sent_at": firestore.SERVER_TIMESTAMP,
        "latest_followup_sent_by": pid,
        **care_update,
    }, merge=True)
    try:
        get_db().collection("analytics_events").add({
            "type": "followup_sent",
            "phone": phone,
            "provider_id": pid,
            "task_id": active_task_id,
            "method": method_name,
            "channel": delivery.get("channel"),
            "automated": False,
            "created_at": firestore.SERVER_TIMESTAMP,
        })
    except Exception as exc:
        print(f"Analytics event failed (manual followup): {exc}")
    record_audit_event(
        db=get_db(),
        phone=phone,
        actor=pid,
        action="followup_sent",
        metadata={"task_id": active_task_id, "method": method_name, "channel": delivery.get("channel"), "automated": False},
    )
    return jsonify({
        "success": delivery.get("status") == "sent",
        "delivery": delivery,
        "message": message,
    })


def api_provider_client_followups(phone):
    pid = session.get("provider_id")
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401
    phone = resolve_client_phone(phone)
    doc = get_db().collection("contraceptive_users").document(phone).get()
    if not doc.exists:
        return jsonify({"error": "Client not found"}), 404
    if (doc.to_dict() or {}).get("assigned_provider_id") != pid:
        return jsonify({"error": "Forbidden"}), 403
    tasks = []
    for task in get_db().collection("followup_tasks").where(
        filter=firestore.FieldFilter("phone", "==", phone)
    ).limit(200).stream():
        item = serialize_firestore_value(task.to_dict())
        item["id"] = task.id
        tasks.append(item)
    tasks.sort(key=lambda x: str(x.get("due_at") or ""))
    return jsonify({"followups": tasks})


def api_provider_followups():
    pid = session.get("provider_id")
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401
    status = request.args.get("status")
    tasks = []
    query = get_db().collection("followup_tasks").where(
        filter=firestore.FieldFilter("provider_id", "==", pid)
    ).limit(500)
    for task in query.stream():
        item = serialize_firestore_value(task.to_dict())
        item["id"] = task.id
        if status and item.get("status") != status:
            continue
        tasks.append(item)
    tasks.sort(key=lambda x: str(x.get("due_at") or ""))
    return jsonify({"followups": tasks})


def api_provider_run_followup_automation():
    pid = session.get("provider_id")
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        result = run_followup_automation(db=get_db())
        return jsonify({"success": True, **result})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def api_provider_analytics_summary():
    pid = session.get("provider_id")
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401
    provider_scope = None if provider_role(pid) == "clinician" else pid
    return jsonify(build_analytics_summary(db, provider_id=provider_scope))


def api_provider_model_training_events():
    pid = session.get("provider_id")
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401
    if provider_role(pid) != "clinician":
        return jsonify({"error": "Clinician access required"}), 403
    limit = int(request.args.get("limit") or 1000)
    return jsonify({
        "events": [serialize_firestore_value(row) for row in export_model_training_events(db, limit=limit)],
        "governance": {
            "minimum_labeled_rows_for_retraining": 500,
            "preferred_labeled_rows_for_subgroup_audit": 2000,
            "promotion_checks": ["auc_roc", "calibration_error", "recall", "subgroup_bias", "geography_drift"],
            "label_warning": "lost_to_followup rows are censored and must not be treated as discontinued without confirmation.",
        },
    })


def api_provider_clinical_review(phone):
    pid = session.get("provider_id")
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401
    phone = resolve_client_phone(phone)
    doc = get_db().collection("contraceptive_users").document(phone).get()
    if not doc.exists:
        return jsonify({"error": "Client not found"}), 404
    client = serialize_firestore_value(doc.to_dict() or {})
    role = provider_role(pid)
    if role != "clinician" and client.get("assigned_provider_id") != pid:
        return jsonify({"error": "Forbidden"}), 403

    referrals = []
    for referral in doc.reference.collection("referrals").limit(50).stream():
        item = serialize_firestore_value(referral.to_dict())
        item["id"] = referral.id
        referrals.append(item)
    audit_trail = [serialize_firestore_value(event) for event in fetch_audit_trail(db=get_db(), phone=phone, limit=100)]
    packet = client.get("recommendation_packet") or build_recommendation_packet(
        client=client,
        recommendation_text=client.get("matched_method") or client.get("latest_recommendation") or "",
        mec_text=client.get("latest_mec_text") or client.get("latest_mec_result") or "",
        citations=client.get("recommendation_citations") or [],
        method_cards=client.get("method_cards") or [],
    )
    return jsonify({
        "client": client,
        "mec_rationale": client.get("latest_mec_text") or client.get("latest_mec_result") or "",
        "confidence_reasoning": packet.get("recommendation_confidence") or {},
        "recommended_methods": packet.get("recommended_methods") or [],
        "methods_excluded": packet.get("methods_not_recommended") or [],
        "contraindications": [
            item for item in packet.get("methods_not_recommended") or []
            if item.get("severity") == "contraindicated" or item.get("mec_category") == 4
        ],
        "override_history": [
            event for event in audit_trail
            if (event.get("action") or "") in {"provider_override_recorded", "client_choice_confirmed"}
        ],
        "referral_history": referrals,
        "audit_trail": audit_trail,
    })


def api_provider_followup_outcome(task_id):
    pid = session.get("provider_id")
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json or {}
    structured_outcome = data.get("structured_outcome") or {}
    outcome = data.get("outcome") or structured_outcome.get("outcome_type")
    if not outcome:
        return jsonify({"error": "Outcome is required"}), 400
    try:
        result = record_followup_outcome(
            db=get_db(),
            task_id=task_id,
            provider_id=pid,
            outcome=outcome,
            note=data.get("note", ""),
            structured_outcome=structured_outcome,
        )
        return jsonify(serialize_firestore_value(result))
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

def api_provider_mec_query():
    pid = session.get('provider_id')
    if not pid: return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    query = data.get('query')
    if not query: return jsonify({"error": "Query required"}), 400
    
    try:
        retriever = get_retriever()
        chunks = retriever.retrieve(query, top_k=5)
        context = retriever.format_context_for_llm(chunks)
        
        sys_prompt = build_system_prompt(
            mec_result_text="[Clinician query — apply WHO MEC categories to the methods discussed in the question.]",
            retrieved_context=context,
            user_profile_summary=f"Clinician portal query from provider {pid}.",
            channel="web",
            language="english",
        )
        full_prompt = (
            f"{sys_prompt}\n\n{build_web_clinical_instruction()}\n\n"
            f"Clinician Query: {query}"
        )
        
        response_text = generate_gemini_text(full_prompt, max_output_tokens=WEB_PROVIDER_MAX_OUTPUT_TOKENS)
        return jsonify({"success": True, "response": response_text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def api_provider_submit_triage():
    pid = session.get('provider_id')
    if not pid: return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json or {}
    phone = data.get('phone')
    if not phone: return jsonify({"error": "Phone required"}), 400
    
    if data.get('country') or data.get('admin_area'):
        data['location_capture_purpose'] = 'analytics_only'
        data['location_source'] = 'provider'
        data['admin_area_type'] = data.get('admin_area_type') or admin_area_label(data.get('country'))
        if data.get('country') and not data.get('country_raw'):
            normalized = normalize_country(str(data['country']), allow_legacy_index=False)
            data['country'] = normalized.canonical
            data['country_raw'] = normalized.raw
            data['country_match_confidence'] = normalized.confidence
        if data.get('admin_area') and not data.get('admin_area_raw'):
            data['admin_area_raw'] = str(data['admin_area']).strip()
            data['admin_area'] = normalize_admin_area(data['admin_area'], data.get('country'))

    phone = resolve_client_phone(phone, country_hint=data.get('country'))
    data['phone'] = phone
    data['assigned_provider_id'] = pid
    data['stage'] = 'REGISTERED'
    data['registered_at'] = firestore.SERVER_TIMESTAMP

    get_db().collection('contraceptive_users').document(phone).set(data, merge=True)
    job_ref = get_db().collection('triage_jobs').document()
    job_ref.set({
        "status": "queued",
        "phone": phone,
        "assigned_provider_id": pid,
        "created_at": firestore.SERVER_TIMESTAMP,
    })
    get_db().collection('contraceptive_users').document(phone).set({
        "triage_status": "queued",
        "latest_triage_job_id": job_ref.id,
        "triage_queued_at": firestore.SERVER_TIMESTAMP,
    }, merge=True)

    triage_payload = {k: v for k, v in data.items() if k != 'registered_at'}
    try:
        rq_job = get_triage_queue().enqueue_call(
            func="triage_tasks.process_triage_job",
            args=(job_ref.id, triage_payload),
            job_id=f"triage_{job_ref.id}",
            timeout=TRIAGE_JOB_TIMEOUT_SECONDS,
            result_ttl=TRIAGE_JOB_RESULT_TTL_SECONDS,
            failure_ttl=TRIAGE_JOB_FAILURE_TTL_SECONDS,
        )
        job_ref.update({
            "rq_job_id": rq_job.id,
            "queued_at": firestore.SERVER_TIMESTAMP,
        })
    except Exception as e:
        error_message = str(e)
        print(f"Triage enqueue failed: {error_message}")
        job_ref.update({
            "status": "failed",
            "error": f"Could not queue triage job: {error_message}",
            "completed_at": firestore.SERVER_TIMESTAMP,
        })
        get_db().collection('contraceptive_users').document(phone).set({
            "triage_status": "failed",
            "latest_triage_job_id": job_ref.id,
            "triage_error": error_message,
            "triage_completed_at": firestore.SERVER_TIMESTAMP,
        }, merge=True)
        return jsonify({
            "success": False,
            "error": "Could not queue triage job. Please try again.",
            "job_id": job_ref.id,
        }), 503
    
    return jsonify({
        "success": True,
        "status": "queued",
        "job_id": job_ref.id,
        "phone": phone,
        "poll_url": url_for('provider.api_provider_triage_result', job_id=job_ref.id)
    }), 202

def api_provider_triage_result(job_id):
    pid = session.get('provider_id')
    if not pid: return jsonify({"error": "Unauthorized"}), 401

    doc = get_db().collection('triage_jobs').document(job_id).get()
    if not doc.exists:
        return jsonify({"error": "Job not found"}), 404

    result = serialize_firestore_value(doc.to_dict())
    if result.get('assigned_provider_id') != pid:
        return jsonify({"error": "Forbidden"}), 403

    recommendation = result.get("recommendation") or ""
    method_cards = result.get("method_cards") or []
    if not method_cards and recommendation:
        method_cards, recommendation = resolve_method_cards(
            recommendation,
            result.get("mec_result") or "",
            result.get("recommendation_citations") or [],
        )
        result["recommendation"] = recommendation
        result["method_cards"] = method_cards
    packet = result.get("recommendation_packet")
    if not packet:
        client_context = {}
        phone = result.get("phone")
        if phone:
            client_doc = get_db().collection("contraceptive_users").document(phone).get()
            if client_doc.exists:
                client_context = serialize_firestore_value(client_doc.to_dict())
                client_context["phone"] = phone
        packet = build_recommendation_packet(
            client=client_context,
            recommendation_text=recommendation,
            mec_text=result.get("mec_result") or "",
            citations=result.get("recommendation_citations") or [],
            method_cards=method_cards,
        )
        result["recommendation_packet"] = packet

    payload = {"success": True, **result}
    payload["method_cards_count"] = len(method_cards or [])
    return jsonify(payload)
