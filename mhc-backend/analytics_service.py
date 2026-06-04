"""
Analytics service layer for contraceptive care workflows.

Stores event-level facts now and exposes simple aggregate summaries that future
dashboards can replace with richer cohort analytics.
"""

from __future__ import annotations

import hashlib
import os
from collections import Counter
from typing import Any

try:
    from firebase_admin import firestore
except ModuleNotFoundError:
    class _FirestoreFallback:
        SERVER_TIMESTAMP = "__SERVER_TIMESTAMP__"

    firestore = _FirestoreFallback()


def record_analytics_event(db, event_type: str, payload: dict[str, Any]) -> None:
    """Append one analytics event without blocking the clinical workflow."""
    try:
        db.collection("analytics_events").add({
            "type": event_type,
            **payload,
            "created_at": firestore.SERVER_TIMESTAMP,
        })
    except Exception as exc:
        print(f"Analytics event failed ({event_type}): {exc}")


def _hash_client_id(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:24]


def _first_present(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return ""


def discontinued_label(outcome_type: str, continuation_status: str = "") -> int | None:
    normalized = str(outcome_type or continuation_status or "").lower()
    if normalized in {"continuing", "active"}:
        return 0
    if normalized in {"switched", "stopped"}:
        return 1
    if normalized == "pregnancy_reported":
        return 1
    return None


def build_model_training_event(
    *,
    phone: str,
    client: dict[str, Any],
    task: dict[str, Any] | None = None,
    outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task = task or {}
    outcome = outcome or {}
    outcome_type = outcome.get("outcome_type") or task.get("outcome") or ""
    continuation_status = outcome.get("continuation_status") or client.get("continuation_status") or ""
    confirmed_method = outcome.get("selected_method") or client.get("selected_method") or task.get("method") or ""
    label = discontinued_label(outcome_type, continuation_status)
    return {
        "client_id_hash": _hash_client_id(phone),
        "country": client.get("country") or "",
        "admin_area": client.get("admin_area") or client.get("county") or "",
        "age": client.get("age") or "",
        "noofchildren": _first_present(client, "living_children", "parity", "noofchildren"),
        "education_level": _first_present(client, "education_level", "educationlevel"),
        "fertility_intention": _first_present(client, "more_children", "future_children", "fertility_intention"),
        "previous_method": _first_present(client, "previous_method", "previousmethod", "last_method"),
        "recommended_methods": [
            method.get("name") or method.get("method_name")
            for method in (client.get("recommendation_packet") or {}).get("recommended_methods", [])
            if method.get("name") or method.get("method_name")
        ],
        "confirmed_method": confirmed_method,
        "method_category": client.get("selected_method_category") or client.get("method_category_primary") or "",
        "counseled_binary": 1 if (client.get("latest_counseling_checklist") or {}).get("informed_choice_confirmed", True) else 0,
        "recommendation_generated_at": client.get("method_match_completed_at") or client.get("triage_completed_at") or "",
        "method_confirmed_at": client.get("selected_method_selected_at") or "",
        "followup_task_id": task.get("id") or task.get("task_id") or "",
        "followup_days_after_start": task.get("days_after_start"),
        "followup_status": task.get("status") or "",
        "side_effects_reported": bool(outcome.get("side_effects")),
        "referral_status": client.get("referral_status") or "",
        "outcome_type": outcome_type,
        "continuation_status": continuation_status,
        "switched_to_method": outcome.get("switched_to_method") or "",
        "lost_to_followup": outcome_type == "lost_to_followup" or task.get("status") == "no_response",
        "label_discontinued": label,
        "label_status": "labeled" if label is not None else "censored_or_pending",
        "created_at": firestore.SERVER_TIMESTAMP,
    }


def record_model_training_event(
    db,
    *,
    phone: str,
    client: dict[str, Any],
    task: dict[str, Any] | None = None,
    outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = build_model_training_event(phone=phone, client=client, task=task, outcome=outcome)
    db.collection("model_training_events").add(event)
    return event


def export_model_training_events(db, *, limit: int = 5000) -> list[dict[str, Any]]:
    """Return a bounded export of model retraining rows."""
    events = []
    for snap in db.collection("model_training_events").limit(limit).stream():
        item = snap.to_dict() or {}
        item["id"] = snap.id
        events.append(item)
    return events


def build_analytics_summary(db, *, provider_id: str | None = None, limit: int | None = None) -> dict[str, Any]:
    """Build a bounded dashboard summary from analytics and training events."""
    limit = limit or int(os.environ.get("ANALYTICS_SUMMARY_LIMIT", "5000"))
    counters = Counter()
    methods = Counter()
    referrals = Counter()
    outcomes = Counter()
    side_effects = 0
    training_rows = 0
    labeled_training_rows = 0

    for snap in db.collection("analytics_events").limit(limit).stream():
        event = snap.to_dict() or {}
        if provider_id and event.get("provider_id") != provider_id:
            continue
        event_type = event.get("type") or "unknown"
        counters[event_type] += 1
        if event.get("method"):
            methods[event.get("method")] += 1
        if event_type == "referral_created":
            referrals[event.get("facility_name") or event.get("referral_type") or "unknown"] += 1
        if event.get("outcome"):
            outcomes[event.get("outcome")] += 1
        if event_type == "side_effect_reported":
            side_effects += 1

    for snap in db.collection("model_training_events").limit(limit).stream():
        row = snap.to_dict() or {}
        training_rows += 1
        if row.get("label_status") == "labeled":
            labeled_training_rows += 1

    return {
        "event_counts": dict(counters),
        "method_selection_rates": dict(methods),
        "method_continuation_rates": {
            "continuing": outcomes.get("continuing", 0),
            "stopped": outcomes.get("stopped", 0),
            "switched": outcomes.get("switched", 0),
        },
        "method_switching_rates": {"switched": outcomes.get("switched", 0)},
        "referral_rates": dict(referrals),
        "no_response_rates": {"no_response": counters.get("followup_no_response", 0)},
        "followup_completion_rates": {"completed": counters.get("followup_outcome_recorded", 0)},
        "reported_side_effects": side_effects,
        "most_common_methods": methods.most_common(10),
        "most_common_referrals": referrals.most_common(10),
        "model_training_events": {
            "total_rows": training_rows,
            "labeled_rows": labeled_training_rows,
            "ready_for_retraining": labeled_training_rows >= 500,
            "preferred_retraining_threshold": 2000,
        },
    }
