"""
Admin dashboard aggregations — all metrics traceable to Firestore fields or /health.
"""

from __future__ import annotations

import csv
import datetime
import io
from collections import Counter, defaultdict
from typing import Any, Optional

try:
    from firebase_admin import firestore
except ModuleNotFoundError:  # Allows pure unit tests outside the Firebase venv.
    firestore = None

from geography import aggregate_geography_stats
from method_categories import classify_method_category_primary


def parse_timestamp(value: Any) -> Optional[datetime.datetime]:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value if value.tzinfo else value.replace(tzinfo=datetime.timezone.utc)
    if hasattr(value, "timestamp"):
        try:
            return datetime.datetime.fromtimestamp(value.timestamp(), tz=datetime.timezone.utc)
        except (TypeError, ValueError, OSError):
            return None
    if isinstance(value, str) and value.strip():
        try:
            cleaned = value.replace("Z", "+00:00")
            return datetime.datetime.fromisoformat(cleaned)
        except ValueError:
            return None
    return None


def format_timestamp(value: Any) -> str:
    dt = parse_timestamp(value)
    return dt.isoformat() if dt else ""


def infer_channel(data: dict) -> str:
    source = str(data.get("source") or data.get("location_source") or "").lower()
    if source in ("whatsapp", "ussd", "provider"):
        return source
    if data.get("assigned_provider_id") and data.get("triage_status"):
        return "provider"
    if data.get("latest_triage_job_id"):
        return "provider"
    return "whatsapp"


def user_completed_match(data: dict) -> bool:
    if data.get("method_match_status") == "completed":
        return True
    if data.get("triage_status") == "completed":
        return True
    return bool(data.get("matched_method"))


def user_failed_match(data: dict) -> bool:
    return data.get("method_match_status") == "failed" or data.get("triage_status") == "failed"


def user_started_match(data: dict) -> bool:
    if user_completed_match(data) or user_failed_match(data):
        return True
    stage = str(data.get("stage") or "")
    if stage.startswith("AWAITING_Q") or stage == "REGISTERED":
        return True
    return data.get("age") is not None


def filter_cohort(users: list[dict], cohort: str) -> list[dict]:
    cohort = (cohort or "all").lower()
    if cohort == "all":
        return users
    if cohort == "week":
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
        filtered = []
        for u in users:
            ts = parse_timestamp(
                u.get("method_match_completed_at")
                or u.get("registered_at")
                or u.get("created_at")
            )
            if ts and ts >= cutoff:
                filtered.append(u)
        return filtered
    if cohort in ("whatsapp", "ussd", "provider"):
        return [u for u in users if infer_channel(u) == cohort]
    return users


def build_registration_trend(users: list[dict], days: int = 30) -> list[dict]:
    today = datetime.datetime.now(datetime.timezone.utc).date()
    start = today - datetime.timedelta(days=days - 1)
    counts: dict[str, int] = defaultdict(int)

    for data in users:
        ts = parse_timestamp(
            data.get("method_match_completed_at")
            or data.get("registered_at")
            or data.get("created_at")
        )
        if not ts:
            continue
        day = ts.date()
        if start <= day <= today:
            counts[day.isoformat()] += 1

    trend = []
    cursor = start
    while cursor <= today:
        key = cursor.isoformat()
        trend.append({"date": key, "count": counts.get(key, 0)})
        cursor += datetime.timedelta(days=1)
    return trend


def build_breakdown(users: list[dict], field: str, default: str = "unknown") -> dict[str, int]:
    counter: Counter[str] = Counter()
    for data in users:
        val = data.get(field) or default
        if field == "channel":
            val = infer_channel(data)
        counter[str(val)] += 1
    return dict(counter.most_common())


def build_completion_stats(users: list[dict]) -> dict[str, Any]:
    started = sum(1 for u in users if user_started_match(u))
    completed = sum(1 for u in users if user_completed_match(u))
    failed = sum(1 for u in users if user_failed_match(u))
    pending = max(0, started - completed - failed)
    rate = round(100 * completed / started, 1) if started else 0.0
    return {
        "started": started,
        "completed": completed,
        "failed": failed,
        "pending": pending,
        "completion_rate_percent": rate,
    }


def build_method_distribution(users: list[dict]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for data in users:
        if not user_completed_match(data):
            continue
        primary = data.get("method_category_primary")
        if not primary:
            primary = classify_method_category_primary(data.get("matched_method", ""))
        if not primary:
            continue
        counter[str(primary)] += 1
    return dict(counter.most_common())


def build_recent_completions(users: list[dict], limit: int = 25) -> list[dict]:
    rows = []
    for data in users:
        if not user_completed_match(data):
            continue
        rows.append({
            "name": data.get("name") or "Unknown",
            "phone": data.get("phone") or data.get("id") or "",
            "channel": infer_channel(data),
            "language": data.get("language") or "—",
            "country": data.get("country") or "",
            "admin_area": data.get("admin_area") or "",
            "method_category_primary": (
                data.get("method_category_primary")
                or classify_method_category_primary(data.get("matched_method", ""))
                or "—"
            ),
            "completed_at": format_timestamp(
                data.get("method_match_completed_at")
                or data.get("triage_completed_at")
                or data.get("registered_at")
            ),
            "status": data.get("method_match_status") or data.get("triage_status") or "completed",
        })
    rows.sort(key=lambda r: r.get("completed_at") or "", reverse=True)
    return rows[:limit]


def collect_safety_items(db, *, provider_id: Optional[str] = None, limit: int = 40) -> list[dict]:
    """Side-effect reports and clinical pipeline failures."""
    assigned_phones: set[str] | None = None
    if provider_id:
        assigned_phones = set()
        if firestore is None:
            return []
        for doc in db.collection("contraceptive_users").where(
            filter=firestore.FieldFilter("assigned_provider_id", "==", provider_id)
        ).stream():
            assigned_phones.add(doc.id)

    items: list[dict] = []

    try:
        for doc in db.collection_group("side_effects").limit(200).stream():
            phone = doc.reference.parent.parent.id
            if assigned_phones is not None and phone not in assigned_phones:
                continue
            payload = doc.to_dict() or {}
            items.append({
                "type": "side_effect",
                "phone": phone,
                "report": (payload.get("report") or "")[:500],
                "source": payload.get("source") or infer_channel({}),
                "language": payload.get("language") or "",
                "at": format_timestamp(payload.get("timestamp")),
                "id": doc.id,
            })
    except Exception:
        pass

    for doc in db.collection("contraceptive_users").stream():
        data = doc.to_dict() or {}
        phone = doc.id
        if assigned_phones is not None and phone not in assigned_phones:
            continue
        if data.get("method_match_status") == "failed":
            items.append({
                "type": "method_match_failed",
                "phone": phone,
                "report": data.get("method_match_error") or "Method Match failed",
                "source": infer_channel(data),
                "language": data.get("language") or "",
                "at": format_timestamp(data.get("method_match_completed_at")),
                "id": phone,
            })
        if data.get("triage_status") == "failed":
            items.append({
                "type": "triage_failed",
                "phone": phone,
                "report": data.get("triage_error") or "Provider triage failed",
                "source": "provider",
                "language": data.get("language") or "",
                "at": format_timestamp(data.get("triage_completed_at")),
                "id": phone,
            })

    items.sort(key=lambda x: x.get("at") or "", reverse=True)
    return items[:limit]


def build_kpis(users: list[dict], providers: list[dict], health: dict) -> dict[str, Any]:
    now = datetime.datetime.now(datetime.timezone.utc)
    week_cutoff = now - datetime.timedelta(days=7)
    matches_week = 0
    pending_providers = 0

    for data in users:
        if user_completed_match(data):
            ts = parse_timestamp(data.get("method_match_completed_at") or data.get("registered_at"))
            if ts and ts >= week_cutoff:
                matches_week += 1

    for p in providers:
        if p.get("status") == "pending":
            pending_providers += 1

    approved_chw = sum(
        1 for p in providers if p.get("role") == "chw" and p.get("status") == "approved"
    )
    approved_clin = sum(
        1 for p in providers if p.get("role") == "clinician" and p.get("status") == "approved"
    )

    return {
        "total_clients": len(users),
        "matches_this_week": matches_week,
        "pending_provider_approvals": pending_providers,
        "active_chws": approved_chw,
        "active_clinicians": approved_clin,
        "system_health": "OK" if health.get("overall", {}).get("ok") else "DEGRADED",
    }


def build_admin_stats(
    db,
    *,
    cohort: str = "all",
    health: Optional[dict] = None,
) -> dict[str, Any]:
    if health is None:
        from health_check import run_health_checks
        health = run_health_checks()
    users_raw = []
    for doc in db.collection("contraceptive_users").stream():
        data = doc.to_dict() or {}
        data["phone"] = doc.id
        data["id"] = doc.id
        users_raw.append(data)

    providers = [doc.to_dict() | {"id": doc.id} for doc in db.collection("providers").stream()]
    users = filter_cohort(users_raw, cohort)

    return {
        "cohort": cohort,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "kpis": build_kpis(users_raw, providers, health),
        "completion": build_completion_stats(users),
        "registration_trend": build_registration_trend(users_raw),
        "channels": build_breakdown(users, "channel"),
        "languages": build_breakdown(users, "language"),
        "method_distribution": build_method_distribution(users),
        "geography": aggregate_geography_stats(users_raw),
        "geography_all_time": aggregate_geography_stats(users_raw),
        "geography_current_cohort": aggregate_geography_stats(users),
        "recent_completions": build_recent_completions(users),
        "safety_inbox": collect_safety_items(db, limit=30),
        "health_checks": health,
        "pending_providers_count": sum(1 for p in providers if p.get("status") == "pending"),
    }


def export_clients_csv(users: list[dict]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "phone", "name", "channel", "language", "country", "admin_area",
        "method_category_primary", "method_match_status", "completed_at", "registered_at",
    ])
    for data in sorted(users, key=lambda u: u.get("phone") or ""):
        writer.writerow([
            data.get("phone") or data.get("id") or "",
            data.get("name") or "",
            infer_channel(data),
            data.get("language") or "",
            data.get("country") or "",
            data.get("admin_area") or "",
            data.get("method_category_primary")
            or classify_method_category_primary(data.get("matched_method", ""))
            or "",
            data.get("method_match_status") or data.get("triage_status") or "",
            format_timestamp(data.get("method_match_completed_at")),
            format_timestamp(data.get("registered_at") or data.get("created_at")),
        ])
    return output.getvalue()
