"""
Immutable clinical audit trail helpers.
"""

from __future__ import annotations

from typing import Any

try:
    from firebase_admin import firestore
except ModuleNotFoundError:
    class _FirestoreFallback:
        SERVER_TIMESTAMP = "__SERVER_TIMESTAMP__"

    firestore = _FirestoreFallback()


def record_audit_event(
    *,
    db,
    phone: str,
    actor: str,
    action: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = {
        "actor": actor or "system",
        "action": action,
        "metadata": metadata or {},
        "timestamp": firestore.SERVER_TIMESTAMP,
    }
    db.collection("contraceptive_users").document(phone).collection("audit_trail").add(event)
    return event


def fetch_audit_trail(*, db, phone: str, limit: int = 50) -> list[dict[str, Any]]:
    ref = db.collection("contraceptive_users").document(phone).collection("audit_trail")
    try:
        query = ref.order_by("timestamp", direction=firestore.Query.DESCENDING).limit(limit)
    except Exception:
        query = ref.limit(limit)
    events = []
    for snap in query.stream():
        item = snap.to_dict() or {}
        item["id"] = snap.id
        events.append(item)
    return events
