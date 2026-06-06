"""
CHW method selection, referral, and follow-up workflow services.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

try:
    from firebase_admin import firestore
except ModuleNotFoundError:  # Allows message/unit tests outside the Firebase venv.
    class _FirestoreFallback:
        SERVER_TIMESTAMP = "__SERVER_TIMESTAMP__"

    firestore = _FirestoreFallback()

from analytics_service import record_analytics_event, record_model_training_event
from audit_trail import record_audit_event
from client_messages import compose_selection_message
from care_plan import default_care_plan_update, transition_for_outcome
from method_categories import classify_method_category_primary
from method_library import build_followup_dates, get_method_info, normalize_method_key


def _server_now():
    return firestore.SERVER_TIMESTAMP


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _analytics_event(db, event_type: str, payload: dict[str, Any]) -> None:
    record_analytics_event(db, event_type, payload)


def _method_names_from_packet(client_data: dict[str, Any]) -> set[str]:
    packet = client_data.get("recommendation_packet") or {}
    names = set()
    for method in packet.get("recommended_methods") or []:
        names.add(normalize_method_key(method.get("name") or method.get("method_name") or ""))
    for card in client_data.get("method_cards") or []:
        names.add(normalize_method_key(card.get("name") or ""))
    return {name for name in names if name}


def _excluded_method_context(client_data: dict[str, Any], method_name: str) -> dict[str, Any] | None:
    selected = normalize_method_key(method_name)
    packet = client_data.get("recommendation_packet") or {}
    for item in packet.get("methods_not_recommended") or []:
        item_name = normalize_method_key(item.get("method_name") or "")
        if item_name and (item_name == selected or item_name in selected or selected in item_name):
            return item
    return None


def assert_provider_can_access(
    client_doc,
    provider_id: str,
    *,
    client_ref=None,
    allow_claim_unassigned: bool = False,
) -> dict[str, Any]:
    if not client_doc.exists:
        raise PermissionError(
            "Client not found for this phone number. Register them via Method Match first."
        )
    data = client_doc.to_dict() or {}
    assigned = data.get("assigned_provider_id")
    if not assigned and allow_claim_unassigned:
        if client_ref is not None:
            client_ref.update({"assigned_provider_id": provider_id})
        data["assigned_provider_id"] = provider_id
        return data
    if assigned != provider_id:
        raise PermissionError(
            "This client is not linked to your provider account. "
            "Open them from your roster or run Method Match to assign them to you."
        )
    return data


def select_method(
    *,
    db,
    phone: str,
    provider_id: str,
    method_name: str,
    counseling: dict[str, Any] | None = None,
    referral: dict[str, Any] | None = None,
    override_reason: str = "",
    safety_override_reason: str = "",
    clinician_acknowledgment: bool = False,
) -> dict[str, Any]:
    client_ref = db.collection("contraceptive_users").document(phone)
    client_data = assert_provider_can_access(
        client_ref.get(),
        provider_id,
        client_ref=client_ref,
        allow_claim_unassigned=True,
    )
    info = get_method_info(method_name)
    method_category = classify_method_category_primary(method_name) or info.get("category") or method_name
    referral_required = bool(referral or info.get("referral_required"))
    if info.get("referral_required") and not referral:
        raise ValueError("Referral facility is required for this method")

    recommended_names = _method_names_from_packet(client_data)
    selected_key = normalize_method_key(method_name)
    excluded = _excluded_method_context(client_data, method_name)
    override_required = bool(recommended_names and selected_key not in recommended_names)
    high_risk_override = bool(excluded and (excluded.get("mec_category") == 4 or excluded.get("severity") == "contraindicated"))
    if override_required and not override_reason:
        raise ValueError("Clinical Override Required: provide override_reason before confirming this client choice.")
    if high_risk_override and (not safety_override_reason or not clinician_acknowledgment):
        raise ValueError("High-Risk Clinical Decision: safety_override_reason and clinician_acknowledgment are required.")

    event = {
        "method": info["display_name"],
        "method_key": normalize_method_key(method_name),
        "method_category": method_category,
        "selected_by_provider_id": provider_id,
        "selected_at": _server_now(),
        "selection_source": "provider_portal",
        "counseling": counseling or {},
        "referral_required": referral_required,
        "client_choice_confirmed": True,
        "override_required": override_required,
        "override_reason": override_reason,
        "high_risk_override": high_risk_override,
        "safety_override_reason": safety_override_reason,
        "clinician_acknowledgment": clinician_acknowledgment,
    }
    client_ref.collection("method_selection_events").add(event)
    _analytics_event(db, "method_selected", {
        "phone": phone,
        "provider_id": provider_id,
        "method": info["display_name"],
        "method_category": method_category,
        "referral_required": referral_required,
        "override_required": override_required,
        "high_risk_override": high_risk_override,
    })
    record_audit_event(
        db=db,
        phone=phone,
        actor=provider_id,
        action="client_choice_confirmed" if not override_required else "provider_override_recorded",
        metadata={
            "method": info["display_name"],
            "override_required": override_required,
            "override_reason": override_reason,
            "high_risk_override": high_risk_override,
            "safety_override_reason": safety_override_reason,
        },
    )

    update = {
        "selected_method": info["display_name"],
        "selected_method_key": info["key"],
        "selected_method_category": method_category,
        "selected_method_selected_at": _server_now(),
        "selected_by_provider_id": provider_id,
        "selection_source": "provider_portal",
        "continuation_status": "active",
        "referral_required": referral_required,
        "latest_override_required": override_required,
        "latest_override_reason": override_reason,
        "latest_high_risk_override": high_risk_override,
    }

    if counseling:
        update["latest_counseling_checklist"] = counseling

    referral_record = None
    if referral:
        referral_record = create_referral(
            db=db,
            phone=phone,
            provider_id=provider_id,
            method_name=info["display_name"],
            referral=referral,
            validate_access=False,
        )
        update["referral_status"] = referral_record["status"]

    tasks = create_followup_tasks(
        db=db,
        phone=phone,
        provider_id=provider_id,
        method_name=info["display_name"],
        client_name=client_data.get("name", ""),
    )
    if tasks:
        update["next_followup_at"] = tasks[0]["due_at"]
    update.update(default_care_plan_update(
        selected_method=info["display_name"],
        referral_status=update.get("referral_status") or ("pending" if referral_required else "not_required"),
        next_followup_at=update.get("next_followup_at"),
        automation_enabled=bool((counseling or {}).get("automation_enabled", True)),
        followup_consent=bool((counseling or {}).get("followup_consent", True)),
        status="active",
    ))

    client_ref.set(update, merge=True)
    return {
        "success": True,
        "client": {"phone": phone, "name": client_data.get("name", "")},
        "method": info,
        "referral": referral_record,
        "followup_tasks": tasks,
    }


def create_referral(
    *,
    db,
    phone: str,
    provider_id: str,
    method_name: str,
    referral: dict[str, Any],
    validate_access: bool = True,
) -> dict[str, Any]:
    client_ref = db.collection("contraceptive_users").document(phone)
    if validate_access:
        assert_provider_can_access(client_ref.get(), provider_id)

    destination = str(referral.get("referral_destination") or referral.get("facility_name") or "").strip()
    record = {
        "referral_id": "",
        "method": method_name,
        "referral_reason": str(referral.get("referral_reason") or referral.get("note") or "Requires provider support").strip(),
        "referral_type": referral.get("referral_type") or ("procedure" if destination else "clinical_review"),
        "referral_destination": destination,
        "facility_name": destination,
        "appointment_at": referral.get("appointment_at") or "",
        "appointment_text": referral.get("appointment_text") or "",
        "note": str(referral.get("note", "")).strip(),
        "urgency": referral.get("urgency", "routine"),
        "status": "pending",
        "completed_at": None,
        "cancelled_at": None,
        "referred_by": provider_id,
        "created_by_provider_id": provider_id,
        "created_at": _server_now(),
    }
    if not record["facility_name"]:
        raise ValueError("Referral facility is required")

    ref = client_ref.collection("referrals").document()
    record["referral_id"] = ref.id
    ref.set(record)
    _analytics_event(db, "referral_created", {
        "phone": phone,
        "provider_id": provider_id,
        "method": method_name,
        "facility_name": record["facility_name"],
        "status": record["status"],
    })
    client_ref.set({
        "referral_required": True,
        "referral_status": "pending",
        "latest_referral_id": ref.id,
        "latest_referral_facility": record["facility_name"],
        "latest_referral_reason": record["referral_reason"],
        "care_plan_status": "referred",
    }, merge=True)
    record_audit_event(
        db=db,
        phone=phone,
        actor=provider_id,
        action="referral_created",
        metadata=record,
    )
    return {"id": ref.id, **record}


def update_referral_status(
    *,
    db,
    phone: str,
    provider_id: str,
    referral_id: str,
    status: str,
    note: str = "",
) -> dict[str, Any]:
    if status not in {"pending", "scheduled", "completed", "cancelled"}:
        raise ValueError("Invalid referral status")
    client_ref = db.collection("contraceptive_users").document(phone)
    assert_provider_can_access(client_ref.get(), provider_id)
    referral_ref = client_ref.collection("referrals").document(referral_id)
    snap = referral_ref.get()
    if not snap.exists:
        raise ValueError("Referral not found")
    update = {"status": status, "status_note": note, "updated_at": _server_now()}
    if status == "completed":
        update["completed_at"] = _server_now()
    if status == "cancelled":
        update["cancelled_at"] = _server_now()
    referral_ref.set(update, merge=True)
    client_ref.set({
        "referral_status": status,
        "care_plan_status": "active" if status == "completed" else "referred",
    }, merge=True)
    record_audit_event(
        db=db,
        phone=phone,
        actor=provider_id,
        action=f"referral_{status}",
        metadata={"referral_id": referral_id, "note": note},
    )
    _analytics_event(db, "referral_status_updated", {
        "phone": phone,
        "provider_id": provider_id,
        "referral_id": referral_id,
        "status": status,
    })
    return {"success": True, "referral_id": referral_id, **update}


def create_followup_tasks(
    *,
    db,
    phone: str,
    provider_id: str,
    method_name: str,
    client_name: str = "",
) -> list[dict[str, Any]]:
    now = _utc_now()
    tasks = []
    for item in build_followup_dates(method_name, now):
        payload = {
            "phone": phone,
            "client_name": client_name,
            "provider_id": provider_id,
            "method": method_name,
            "due_at": item["due_at"],
            "status": "due",
            "reason": item["reason"],
            "days_after_start": item["days_after_start"],
            "attempts": 0,
            "outcome": None,
            "automation_enabled": True,
            "response_due_at": None,
            "sent_at": None,
            "last_response_at": None,
            "created_at": _server_now(),
        }
        doc_ref = db.collection("followup_tasks").document()
        doc_ref.set(payload)
        tasks.append({"id": doc_ref.id, **payload})
    return tasks


def build_selection_client_message(
    *,
    client: dict[str, Any],
    method_name: str,
    referral: dict[str, Any] | None = None,
    next_followup: Any = None,
) -> str:
    return compose_selection_message(
        client_name=client.get("name", ""),
        method_name=method_name,
        referral=referral,
        next_followup=next_followup,
    )


def record_followup_outcome(
    *,
    db,
    task_id: str,
    provider_id: str,
    outcome: str,
    note: str = "",
    structured_outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_ref = db.collection("followup_tasks").document(task_id)
    snap = task_ref.get()
    if not snap.exists:
        raise ValueError("Follow-up task not found")
    data = snap.to_dict() or {}
    if data.get("provider_id") != provider_id:
        raise PermissionError("Forbidden")

    structured_outcome = structured_outcome or {}
    outcome_type = structured_outcome.get("outcome_type") or outcome
    outcome_record = {
        "outcome_type": outcome_type,
        "selected_method": structured_outcome.get("selected_method") or data.get("method") or "",
        "switched_to_method": structured_outcome.get("switched_to_method") or "",
        "side_effects": structured_outcome.get("side_effects") or [],
        "pregnancy_status": structured_outcome.get("pregnancy_status") or "",
        "continuation_status": structured_outcome.get("continuation_status") or _continuation_status(outcome_type),
        "notes": structured_outcome.get("notes") or note,
    }
    update = {
        "status": "completed",
        "outcome": outcome_type,
        "structured_outcome": outcome_record,
        "note": note,
        "completed_at": _server_now(),
    }
    task_ref.set(update, merge=True)
    phone = data.get("phone")
    if phone:
        client_ref = db.collection("contraceptive_users").document(phone)
        client_snapshot = client_ref.get().to_dict() or {}
        db.collection("contraceptive_users").document(phone).collection("followup_events").add({
            "task_id": task_id,
            "method": data.get("method"),
            "outcome": outcome_type,
            "structured_outcome": outcome_record,
            "note": note,
            "provider_id": provider_id,
            "created_at": _server_now(),
        })
        _analytics_event(db, "followup_outcome_recorded", {
            "phone": phone,
            "provider_id": provider_id,
            "task_id": task_id,
            "method": data.get("method"),
            "outcome": outcome_type,
            "continuation_status": _continuation_status(outcome_type),
        })
        record_audit_event(
            db=db,
            phone=phone,
            actor=provider_id,
            action="outcome_recorded",
            metadata={"task_id": task_id, **outcome_record},
        )
        record_model_training_event(
            db,
            phone=phone,
            client={**client_snapshot, "continuation_status": _continuation_status(outcome_type)},
            task={"id": task_id, **data, **update},
            outcome=outcome_record,
        )
        client_ref.set({
            "latest_followup_outcome": outcome_type,
            "latest_structured_outcome": outcome_record,
            "latest_followup_at": _server_now(),
            "continuation_status": _continuation_status(outcome_type),
            **transition_for_outcome(outcome_type),
        }, merge=True)
    return {"success": True, "task_id": task_id, **update}


def _continuation_status(outcome: str) -> str:
    normalized = str(outcome or "").lower()
    if normalized in {"continuing", "stopped", "switched", "pregnancy_reported", "lost_to_followup"}:
        return normalized
    if normalized in {"unreachable", "referred"}:
        return normalized
    return "active"
