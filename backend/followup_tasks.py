"""
Automated follow-up sender and no-response escalation.

Run from a scheduler/cron with:
    python followup_tasks.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from firebase_admin import firestore

from app_config import TWILIO_NUMBER
from analytics_service import record_analytics_event, record_model_training_event
from audit_trail import record_audit_event
from care_plan import (
    transition_for_client_reply,
    transition_for_followup_sent,
    transition_for_no_response,
    utc_now,
)
from client_messages import compose_followup_reminder
from db_client import get_db
from twilio_messaging import send_whatsapp_with_sms_fallback


SENDABLE_STATUSES = {"due", "pending"}
FOLLOWUP_QUERY_MULTIPLIER = 5


def _to_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    return None


def _client_ref(db, phone: str):
    return db.collection("contraceptive_users").document(phone)


def _analytics_event(db, event_type: str, payload: dict[str, Any]) -> None:
    record_analytics_event(db, event_type, payload)


def _can_auto_send(client: dict[str, Any], task: dict[str, Any]) -> bool:
    return bool(
        client.get("automation_enabled", task.get("automation_enabled", True))
        and client.get("followup_consent", True)
    )


def send_due_followups(*, db=None, now: datetime | None = None, limit: int = 100) -> dict[str, int]:
    """Send at most ``limit`` due automated follow-up tasks."""
    db = db or get_db()
    now = now or utc_now()
    sent = 0
    skipped = 0
    failed = 0

    query_limit = max(limit * FOLLOWUP_QUERY_MULTIPLIER, limit)
    for status_to_send in sorted(SENDABLE_STATUSES):
        query = (
            db.collection("followup_tasks")
            .where(filter=firestore.FieldFilter("status", "==", status_to_send))
            .order_by("due_at")
            .limit(query_limit)
        )
        for snap in query.stream():
            if sent + skipped + failed >= limit:
                break
            task = snap.to_dict() or {}
            due_at = _to_dt(task.get("due_at"))
            if due_at and due_at > now:
                continue
            phone = task.get("phone")
            if not phone:
                skipped += 1
                continue
            client_doc = _client_ref(db, phone).get()
            client = client_doc.to_dict() if client_doc.exists else {}
            if not _can_auto_send(client, task):
                snap.reference.set({"status": "paused", "paused_reason": "automation_disabled_or_no_consent"}, merge=True)
                skipped += 1
                continue

            method = task.get("method") or client.get("selected_method") or "your method"
            message = compose_followup_reminder(
                client_name=client.get("name") or task.get("client_name") or "",
                method_name=method,
                reason=task.get("reason") or "routine follow-up",
            )
            delivery = send_whatsapp_with_sms_fallback(TWILIO_NUMBER, phone, message)
            sent_at = now
            update = {
                "status": "sent" if delivery.get("status") == "sent" else "send_failed",
                "attempts": int(task.get("attempts") or 0) + 1,
                "last_delivery": delivery,
                "latest_message": message,
                "sent_at": sent_at,
                "response_due_at": sent_at.replace(tzinfo=timezone.utc) + timedelta(hours=48),
            }
            snap.reference.set(update, merge=True)
            if delivery.get("status") == "sent":
                _client_ref(db, phone).set({
                    "latest_followup_message": message,
                    "latest_followup_sent_at": sent_at,
                    **transition_for_followup_sent(snap.id, sent_at),
                }, merge=True)
                _analytics_event(db, "followup_sent", {
                    "phone": phone,
                    "provider_id": task.get("provider_id"),
                    "task_id": snap.id,
                    "method": method,
                    "channel": delivery.get("channel"),
                    "automated": True,
                })
                record_audit_event(
                    db=db,
                    phone=phone,
                    actor="automation",
                    action="followup_sent",
                    metadata={"task_id": snap.id, "method": method, "channel": delivery.get("channel")},
                )
                sent += 1
            else:
                failed += 1
        if sent + skipped + failed >= limit:
            break
    return {"sent": sent, "skipped": skipped, "failed": failed}


def escalate_no_responses(*, db=None, now: datetime | None = None, limit: int = 100) -> dict[str, int]:
    """Mark sent follow-ups as no-response after their response deadline passes."""
    db = db or get_db()
    now = now or utc_now()
    escalated = 0

    for snap in db.collection("followup_tasks").where(
        filter=firestore.FieldFilter("status", "==", "sent")
    ).order_by("response_due_at").limit(max(limit * FOLLOWUP_QUERY_MULTIPLIER, limit)).stream():
        if escalated >= limit:
            break
        task = snap.to_dict() or {}
        due = _to_dt(task.get("response_due_at"))
        if not due or due > now or task.get("last_response_at") or task.get("outcome"):
            continue
        phone = task.get("phone")
        if not phone:
            continue
        client_ref = _client_ref(db, phone)
        client = client_ref.get().to_dict() or {}
        update = {
            "status": "no_response",
            "no_response_at": now,
            "chw_alert": True,
            "alert_reason": "Client did not respond to automated follow-up.",
        }
        snap.reference.set(update, merge=True)
        client_ref.set({
            **transition_for_no_response(client.get("no_response_count") or 0),
            "latest_chw_alert": "Client did not respond to automated follow-up.",
            "latest_chw_alert_task_id": snap.id,
        }, merge=True)
        _analytics_event(db, "followup_no_response", {
            "phone": phone,
            "provider_id": task.get("provider_id"),
            "task_id": snap.id,
            "method": task.get("method"),
        })
        record_audit_event(
            db=db,
            phone=phone,
            actor="automation",
            action="followup_no_response",
            metadata={"task_id": snap.id, "method": task.get("method")},
        )
        record_model_training_event(
            db,
            phone=phone,
            client=client,
            task={"id": snap.id, **task, **update},
            outcome={"outcome_type": "lost_to_followup", "continuation_status": "lost_to_followup"},
        )
        escalated += 1
    return {"escalated": escalated}


def attach_client_followup_reply(*, db=None, phone: str, reply_text: str) -> bool:
    db = db or get_db()
    client_ref = _client_ref(db, phone)
    client_doc = client_ref.get()
    if not client_doc.exists:
        return False
    client = client_doc.to_dict() or {}
    task_id = client.get("active_followup_task_id")
    if not task_id or client.get("care_plan_status") != "awaiting_response":
        return False
    task_ref = db.collection("followup_tasks").document(task_id)
    now = utc_now()
    task_ref.set({
        "status": "client_replied",
        "last_response": reply_text,
        "last_response_at": now,
        "chw_alert": True,
        "alert_reason": "Client replied to follow-up.",
    }, merge=True)
    client_ref.collection("followup_events").add({
        "task_id": task_id,
        "type": "client_replied",
        "reply": reply_text,
        "created_at": firestore.SERVER_TIMESTAMP,
    })
    _analytics_event(db, "followup_client_replied", {
        "phone": phone,
        "task_id": task_id,
    })
    record_audit_event(
        db=db,
        phone=phone,
        actor="client",
        action="client_reply_received",
        metadata={"task_id": task_id, "reply": reply_text},
    )
    client_ref.set(transition_for_client_reply(task_id, reply_text), merge=True)
    return True


def run_followup_automation(*, db=None) -> dict[str, int]:
    db = db or get_db()
    sent = send_due_followups(db=db)
    escalated = escalate_no_responses(db=db)
    return {**sent, **escalated}


if __name__ == "__main__":
    print(run_followup_automation())
