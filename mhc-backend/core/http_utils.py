"""HTTP and Firestore serialization helpers."""

from __future__ import annotations

import datetime
import re

from flask import jsonify

from db_client import get_db
from method_categories import classify_method_category_primary


def format_to_e164(phone, country_code="+254"):
    """Convert local phone formats (e.g. 07...) to E.164 (+254...)."""
    if not phone:
        return phone
    cleaned = re.sub(r"[^\d+]", "", phone)
    if cleaned.startswith("0") and len(cleaned) == 10:
        return f"{country_code}{cleaned[1:]}"
    if cleaned.startswith(country_code[1:]) and not cleaned.startswith("+"):
        return f"+{cleaned}"
    if len(cleaned) <= 10 and not cleaned.startswith("+"):
        return f"{country_code}{cleaned}"
    return cleaned


def require_db():
    """Return ``(db, error_response)`` where one of the tuple entries is None."""
    db = get_db()
    if db is None:
        return None, (jsonify({"error": "Database is not initialized"}), 503)
    return db, None


def sanitize_provider(data):
    """Remove credential fields before returning provider JSON."""
    cleaned = dict(data or {})
    for field in ("password", "password_hash", "passwordHash"):
        cleaned.pop(field, None)
    return cleaned


def serialize_firestore_value(value):
    """Convert Firestore types to JSON-safe values for dashboard APIs."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError, OSError):
            pass
    if hasattr(value, "timestamp"):
        try:
            return datetime.datetime.utcfromtimestamp(value.timestamp()).isoformat() + "Z"
        except (TypeError, ValueError, OSError):
            pass
    if isinstance(value, dict):
        return {k: serialize_firestore_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [serialize_firestore_value(v) for v in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def extract_method_snippet(text, limit=120):
    """Extract a short method label from free-text recommendations."""
    if not text:
        return "Pending"
    cleaned = re.sub(r"\s+", " ", str(text)).strip()
    match = re.search(r"\*([^*]+)\*", cleaned)
    if match:
        return match.group(1).strip()[:limit]
    for keyword in ("Implant", "IUD", "Injection", "Pill", "Condom", "Injectable", "DIU"):
        if keyword.lower() in cleaned.lower():
            return keyword
    return cleaned[:limit] + ("…" if len(cleaned) > limit else "")


def provider_client_summary(doc) -> dict:
    """Serialize a contraceptive user document for provider roster views."""
    u = serialize_firestore_value(doc.to_dict())
    u["id"] = doc.id
    u["phone"] = doc.id
    matched = u.get("matched_method") or u.get("latest_recommendation") or ""
    u["method_snippet"] = extract_method_snippet(matched)
    u["method_category_primary"] = (
        u.get("method_category_primary") or classify_method_category_primary(matched)
    )
    u["channel"] = u.get("source") or ("provider" if u.get("triage_status") else "whatsapp")
    u["registered_at"] = serialize_firestore_value(u.get("registered_at") or u.get("created_at"))
    u["completed_at"] = serialize_firestore_value(
        u.get("method_match_completed_at") or u.get("triage_completed_at")
    )
    if u.get("method_match_status") == "completed" or u.get("triage_status") == "completed":
        u["match_status"] = "completed"
    elif u.get("method_match_status") == "failed" or u.get("triage_status") == "failed":
        u["match_status"] = "failed"
    elif u.get("triage_status") in ("queued", "processing"):
        u["match_status"] = u.get("triage_status")
    elif matched:
        u["match_status"] = "completed"
    else:
        u["match_status"] = "in_progress"
    return u
