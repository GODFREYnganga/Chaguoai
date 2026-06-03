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

from client_messages import compose_selection_message
from method_categories import classify_method_category_primary
from method_library import build_followup_dates, get_method_info, normalize_method_key


def _server_now():
    return firestore.SERVER_TIMESTAMP


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def assert_provider_can_access(client_doc, provider_id: str) -> dict[str, Any]:
    if not client_doc.exists:
        raise PermissionError("Client not found")
    data = client_doc.to_dict() or {}
    if data.get("assigned_provider_id") != provider_id:
        raise PermissionError("Forbidden")
    return data


def select_method(
    *,
    db,
    phone: str,
    provider_id: str,
    method_name: str,
    counseling: dict[str, Any] | None = None,
    referral: dict[str, Any] | None = None,
) -> dict[str, Any]:
    client_ref = db.collection("contraceptive_users").document(phone)
    client_data = assert_provider_can_access(client_ref.get(), provider_id)
    info = get_method_info(method_name)
    method_category = classify_method_category_primary(method_name) or info.get("category") or method_name
    referral_required = bool(referral or info.get("referral_required"))
    if info.get("referral_required") and not referral:
        raise ValueError("Referral facility is required for this method")

    event = {
        "method": info["display_name"],
        "method_key": normalize_method_key(method_name),
        "method_category": method_category,
        "selected_by_provider_id": provider_id,
        "selected_at": _server_now(),
        "selection_source": "provider_portal",
        "counseling": counseling or {},
        "referral_required": referral_required,
    }
    client_ref.collection("method_selection_events").add(event)

    update = {
        "selected_method": info["display_name"],
        "selected_method_key": info["key"],
        "selected_method_category": method_category,
        "selected_method_selected_at": _server_now(),
        "selected_by_provider_id": provider_id,
        "selection_source": "provider_portal",
        "continuation_status": "active",
        "referral_required": referral_required,
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

    record = {
        "method": method_name,
        "facility_name": str(referral.get("facility_name", "")).strip(),
        "appointment_at": referral.get("appointment_at") or "",
        "appointment_text": referral.get("appointment_text") or "",
        "note": str(referral.get("note", "")).strip(),
        "urgency": referral.get("urgency", "routine"),
        "status": "pending",
        "created_by_provider_id": provider_id,
        "created_at": _server_now(),
    }
    if not record["facility_name"]:
        raise ValueError("Referral facility is required")

    ref = client_ref.collection("referrals").document()
    ref.set(record)
    client_ref.set({
        "referral_required": True,
        "referral_status": "pending",
        "latest_referral_id": ref.id,
        "latest_referral_facility": record["facility_name"],
    }, merge=True)
    return {"id": ref.id, **record}


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
) -> dict[str, Any]:
    task_ref = db.collection("followup_tasks").document(task_id)
    snap = task_ref.get()
    if not snap.exists:
        raise ValueError("Follow-up task not found")
    data = snap.to_dict() or {}
    if data.get("provider_id") != provider_id:
        raise PermissionError("Forbidden")

    update = {
        "status": "completed",
        "outcome": outcome,
        "note": note,
        "completed_at": _server_now(),
    }
    task_ref.set(update, merge=True)
    phone = data.get("phone")
    if phone:
        db.collection("contraceptive_users").document(phone).collection("followup_events").add({
            "task_id": task_id,
            "method": data.get("method"),
            "outcome": outcome,
            "note": note,
            "provider_id": provider_id,
            "created_at": _server_now(),
        })
        db.collection("contraceptive_users").document(phone).set({
            "latest_followup_outcome": outcome,
            "latest_followup_at": _server_now(),
            "continuation_status": _continuation_status(outcome),
        }, merge=True)
    return {"success": True, "task_id": task_id, **update}


def _continuation_status(outcome: str) -> str:
    normalized = str(outcome or "").lower()
    if normalized in {"stopped", "switched"}:
        return normalized
    if normalized in {"unreachable", "referred"}:
        return normalized
    return "active"
