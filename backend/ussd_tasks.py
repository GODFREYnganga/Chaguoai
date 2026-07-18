"""Background jobs for USSD Method Match (avoids Africa's Talking session timeouts)."""

from firebase_admin import firestore

from audit_trail import record_audit_event
from clinical_pipeline import generate_ussd_fast_mec_summary, generate_ussd_recommendation
from db_client import get_db
from method_categories import classify_method_category_primary


def process_ussd_method_match_job(phone_number: str, lang: str, user_snapshot: dict | None = None):
    """
    RQ worker entry: run MEC + RAG + Gemini off the USSD HTTP request thread.
    Falls back to fast MEC-only summary if the full pipeline fails.
    """
    db = get_db()
    user = dict(user_snapshot or {})
    user["phone"] = phone_number
    user["language"] = lang or user.get("language", "english")
    user["source"] = "ussd"

    print(f"[{phone_number}] ussd_method_match_job: started")
    reply_text = ""
    mec_text = ""
    status = "completed"
    error_message = ""

    try:
        reply_text, mec_text = generate_ussd_recommendation(user)
    except Exception as exc:
        error_message = str(exc)
        print(f"[{phone_number}] ussd_method_match_job: full pipeline failed — {error_message}")
        try:
            reply_text, mec_text = generate_ussd_fast_mec_summary(user)
        except Exception as fallback_exc:
            status = "failed"
            error_message = f"{error_message}; fallback: {fallback_exc}"
            print(f"[{phone_number}] ussd_method_match_job: fallback failed — {fallback_exc}")
        else:
            status = "completed"

    update = {
        "method_match_pending": False,
        "method_match_completed_at": firestore.SERVER_TIMESTAMP,
        "source": "ussd",
    }
    if status == "completed" and reply_text:
        update.update({
            "matched_method": reply_text,
            "method_category_primary": classify_method_category_primary(reply_text),
            "latest_mec_text": mec_text,
            "method_match_status": "completed",
            "stage": "REGISTERED",
        })
        record_audit_event(
            db=db,
            phone=phone_number,
            actor="system",
            action="recommendation_generated",
            metadata={"channel": "ussd", "async": True},
        )
        print(f"[{phone_number}] ussd_method_match_job: completed")
    else:
        update.update({
            "method_match_status": "failed",
            "method_match_error": error_message or "unknown error",
            "stage": "REGISTERED",
        })
        print(f"[{phone_number}] ussd_method_match_job: failed")

    db.collection("contraceptive_users").document(phone_number).set(update, merge=True)
    return {"success": status == "completed", "reply": reply_text, "status": status}
