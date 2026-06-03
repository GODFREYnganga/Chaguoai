from firebase_admin import firestore

from app_config import METHOD_MATCH_FALLBACK, TWILIO_NUMBER
from clinical_pipeline import generate_whatsapp_recommendation
from method_categories import classify_method_category_primary
from db_client import get_db
from twilio_messaging import send_long_whatsapp_message, send_whatsapp_message


def process_whatsapp_method_match_job(user_phone, to_number, lang, user_snapshot=None):
    """
    RQ worker entry: generate Method Match and deliver via WhatsApp.
    user_snapshot avoids stale Firestore reads after Q13.
    """
    db = get_db()
    user = dict(user_snapshot or {})
    if not user:
        doc = db.collection("contraceptive_users").document(user_phone).get()
        user = doc.to_dict() if doc.exists else {}
    user["phone"] = user_phone
    user["language"] = lang or user.get("language", "english")
    user["stage"] = "REGISTERED"
    user["method_match_pending"] = True

    print(f"[{user_phone}] method_match_job: started")
    try:
        reply_text, mec_text = generate_whatsapp_recommendation(user)
        words = len(reply_text.split())
        print(f"[{user_phone}] method_match_job: sending reply ({words} words, {len(reply_text)} chars)")
        if words < 40:
            print(
                f"[{user_phone}] WARNING: reply still short after Gemini — "
                "check WHATSAPP_MAX_OUTPUT_TOKENS in .env (use 2048+) and restart worker"
            )
        send_long_whatsapp_message(send_whatsapp_message, to_number, user_phone, reply_text)

        db.collection("contraceptive_users").document(user_phone).update({
            "matched_method": reply_text,
            "method_category_primary": classify_method_category_primary(reply_text),
            "latest_mec_text": mec_text,
            "method_match_pending": False,
            "method_match_status": "completed",
            "stage": "MAIN_MENU",
            "method_match_completed_at": firestore.SERVER_TIMESTAMP,
        })
        print(f"[{user_phone}] method_match_job: completed")
        return {"success": True, "reply": reply_text}
    except Exception as exc:
        error_message = str(exc)
        print(f"[{user_phone}] method_match_job: failed — {error_message}")
        fallback = METHOD_MATCH_FALLBACK.get(lang, METHOD_MATCH_FALLBACK["english"])
        send_whatsapp_message(to_number, user_phone, fallback)
        db.collection("contraceptive_users").document(user_phone).update({
            "method_match_pending": False,
            "method_match_status": "failed",
            "method_match_error": error_message,
            "stage": "MAIN_MENU",
            "method_match_completed_at": firestore.SERVER_TIMESTAMP,
        })
        raise
