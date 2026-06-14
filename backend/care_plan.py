"""
Client-centered contraceptive care plan and timeline helpers.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from firebase_admin import firestore
except ModuleNotFoundError:
    class _FirestoreFallback:
        SERVER_TIMESTAMP = "__SERVER_TIMESTAMP__"

    firestore = _FirestoreFallback()


CARE_PLAN_STATUSES = {
    "not_started",
    "active",
    "awaiting_response",
    "needs_chw_attention",
    "completed",
    "switched",
    "referred",
    "stopped",
    "pregnancy_reported",
    "lost_to_followup",
}

FOLLOWUP_RESPONSE_WINDOW_HOURS = 48


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def server_now():
    return firestore.SERVER_TIMESTAMP


def normalize_status(status: str | None, default: str = "active") -> str:
    value = str(status or "").strip().lower()
    return value if value in CARE_PLAN_STATUSES else default


def default_care_plan_update(
    *,
    selected_method: str = "",
    referral_status: str = "",
    next_followup_at: Any = None,
    automation_enabled: bool = True,
    followup_consent: bool = True,
    status: str = "active",
) -> dict[str, Any]:
    return {
        "care_plan_status": normalize_status(status),
        "selected_method": selected_method,
        "referral_status": referral_status or "not_required",
        "next_followup_at": next_followup_at,
        "no_response_count": 0,
        "automation_enabled": automation_enabled,
        "followup_consent": followup_consent,
        "care_plan_updated_at": server_now(),
    }


def transition_for_followup_sent(task_id: str, sent_at: datetime | None = None) -> dict[str, Any]:
    sent_at = sent_at or utc_now()
    return {
        "care_plan_status": "awaiting_response",
        "active_followup_task_id": task_id,
        "last_followup_sent_at": sent_at,
        "response_due_at": sent_at + timedelta(hours=FOLLOWUP_RESPONSE_WINDOW_HOURS),
        "care_plan_updated_at": server_now(),
    }


def transition_for_client_reply(task_id: str, reply_text: str) -> dict[str, Any]:
    return {
        "care_plan_status": "active",
        "active_followup_task_id": task_id,
        "last_followup_response": reply_text,
        "last_followup_response_at": server_now(),
        "care_plan_updated_at": server_now(),
    }


def transition_for_no_response(no_response_count: int = 0) -> dict[str, Any]:
    return {
        "care_plan_status": "needs_chw_attention",
        "no_response_count": int(no_response_count or 0) + 1,
        "last_no_response_at": server_now(),
        "care_plan_updated_at": server_now(),
    }


def transition_for_outcome(outcome: str) -> dict[str, Any]:
    normalized = str(outcome or "").lower()
    if normalized in {"stopped", "switched", "referred", "pregnancy_reported", "lost_to_followup"}:
        status = normalized
    elif normalized in {"unreachable", "no_response"}:
        status = "needs_chw_attention"
    else:
        status = "active"
    return {
        "care_plan_status": status,
        "latest_followup_outcome": outcome,
        "latest_followup_at": server_now(),
        "care_plan_updated_at": server_now(),
    }


def _as_sortable(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _timeline_item(event_type: str, label: str, at: Any = "", status: str = "completed", detail: str = "", meta: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "type": event_type,
        "label": label,
        "at": at,
        "status": status,
        "detail": detail,
        "meta": meta or {},
    }


def build_client_timeline(
    *,
    client: dict[str, Any],
    followups: list[dict[str, Any]] | None = None,
    side_effects: list[dict[str, Any]] | None = None,
    referrals: list[dict[str, Any]] | None = None,
    audit_events: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if client.get("method_match_completed_at") or client.get("triage_completed_at"):
        items.append(_timeline_item(
            "method_match_completed",
            "Method Match completed",
            client.get("method_match_completed_at") or client.get("triage_completed_at"),
            detail=client.get("method_category_primary") or "",
        ))
    if client.get("matched_method") or client.get("latest_recommendation"):
        items.append(_timeline_item("recommendation_generated", "Recommendation generated", client.get("method_match_completed_at") or client.get("triage_completed_at")))
    if client.get("selected_method"):
        items.append(_timeline_item(
            "method_selected",
            f"Client chose {client.get('selected_method')}",
            client.get("selected_method_selected_at"),
            detail=client.get("selected_method"),
        ))
    if client.get("latest_referral_facility"):
        items.append(_timeline_item(
            "referral_created",
            "Referral created",
            client.get("referral_created_at") or client.get("selected_method_selected_at"),
            status=client.get("referral_status") or "pending",
            detail=client.get("latest_referral_facility"),
        ))

    for referral in referrals or []:
        label = {
            "pending": "Referral created",
            "scheduled": "Referral scheduled",
            "completed": "Referral completed",
            "cancelled": "Referral cancelled",
        }.get(referral.get("status"), "Referral updated")
        items.append(_timeline_item(
            "referral",
            label,
            referral.get("completed_at") or referral.get("updated_at") or referral.get("created_at"),
            status=referral.get("status") or "pending",
            detail=referral.get("referral_destination") or referral.get("facility_name") or referral.get("referral_reason") or "",
            meta=referral,
        ))

    for task in followups or []:
        status = task.get("status") or "due"
        label = {
            "due": "Follow-up scheduled",
            "sent": "Follow-up sent",
            "completed": "Outcome recorded",
            "no_response": "No response",
            "needs_chw_attention": "CHW action needed",
        }.get(status, "Follow-up")
        items.append(_timeline_item(
            "followup",
            label,
            task.get("sent_at") or task.get("completed_at") or task.get("due_at"),
            status=status,
            detail=task.get("reason") or task.get("outcome") or "",
            meta={"task_id": task.get("id"), "method": task.get("method")},
        ))

        if task.get("structured_outcome"):
            outcome = task.get("structured_outcome") or {}
            items.append(_timeline_item(
                "outcome_recorded",
                f"Outcome recorded: {outcome.get('outcome_type') or task.get('outcome')}",
                task.get("completed_at"),
                status=outcome.get("continuation_status") or task.get("status") or "completed",
                detail=outcome.get("notes") or task.get("note") or "",
                meta=outcome,
            ))

    if client.get("last_followup_response"):
        items.append(_timeline_item(
            "client_replied",
            "Client replied",
            client.get("last_followup_response_at"),
            detail=client.get("last_followup_response"),
        ))

    for report in side_effects or []:
        items.append(_timeline_item(
            "side_effect_reported",
            "Side effect reported",
            report.get("at") or report.get("timestamp"),
            status="needs_review",
            detail=report.get("report") or "",
        ))

    action_labels = {
        "client_choice_confirmed": "Client choice confirmed",
        "provider_override_recorded": "Provider override recorded",
        "referral_created": "Referral created",
        "outcome_recorded": "Outcome recorded",
        "followup_sent": "Follow-up sent",
        "followup_no_response": "No response escalation",
        "client_reply_received": "Client reply received",
        "automation_paused": "Automation paused",
        "automation_resumed": "Automation resumed",
    }
    for event in audit_events or []:
        action = event.get("action") or "audit_event"
        metadata = event.get("metadata") or {}
        items.append(_timeline_item(
            "audit",
            action_labels.get(action, action.replace("_", " ").title()),
            event.get("timestamp"),
            status="completed",
            detail=metadata.get("method") or metadata.get("note") or metadata.get("referral_destination") or "",
            meta=event,
        ))

    for event in events or []:
        items.append(_timeline_item(
            event.get("type") or "event",
            event.get("label") or "Care event",
            event.get("created_at") or event.get("at"),
            status=event.get("status") or "completed",
            detail=event.get("detail") or event.get("note") or "",
            meta=event,
        ))

    return sorted(items, key=lambda item: _as_sortable(item.get("at")))
