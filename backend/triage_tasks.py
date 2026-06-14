import json

from firebase_admin import firestore

from clinical_pipeline import generate_provider_triage_recommendation, generate_ussd_recommendation
from db_client import get_db
from fhir_utils import to_fhir_patient
from twilio_messaging import send_whatsapp_with_sms_fallback, TWILIO_NUMBER
from method_categories import classify_method_category_primary
from recommendation_packet import build_recommendation_packet
from user_profile_mapper import map_triage_form_to_user
from whatsapp_helpers import format_recommendation_for_whatsapp
from audit_trail import record_audit_event


from geography import strip_analytics_fields


def clinical_prompt_data(data):
    return strip_analytics_fields(data)


def process_triage_job(job_id, data):
    job_ref = get_db().collection("triage_jobs").document(job_id)
    phone = data.get("phone")

    try:
        job_ref.update({"status": "processing", "started_at": firestore.SERVER_TIMESTAMP})
        if phone:
            get_db().collection("contraceptive_users").document(phone).set({
                "triage_status": "processing",
                "latest_triage_job_id": job_id,
                "triage_started_at": firestore.SERVER_TIMESTAMP,
            }, merge=True)

        user = map_triage_form_to_user(data)
        recommendation, mec_text, citations, method_cards = generate_provider_triage_recommendation(
            user, json.dumps(clinical_prompt_data(data))
        )

        sms_intro = f"Habari {data.get('name')}! Your ChaguoAI Method Match:"
        sms_body = f"{sms_intro}\n\n{format_recommendation_for_whatsapp(recommendation)}"
        delivery = send_whatsapp_with_sms_fallback(TWILIO_NUMBER, phone, sms_body)

        fhir_view = to_fhir_patient(data)
        client_context = {**data, **user, "phone": phone}
        packet = build_recommendation_packet(
            client=client_context,
            recommendation_text=recommendation,
            mec_text=mec_text,
            citations=citations,
            method_cards=method_cards,
        )
        job_ref.update({
            "status": "completed",
            "recommendation": recommendation,
            "mec_result": mec_text,
            "recommendation_citations": citations,
            "method_cards": method_cards,
            "recommendation_packet": packet,
            "fhir_view": fhir_view,
            "completed_at": firestore.SERVER_TIMESTAMP,
        })
        get_db().collection("contraceptive_users").document(phone).set({
            "triage_status": "completed",
            "latest_triage_job_id": job_id,
            "latest_recommendation": recommendation,
            "matched_method": recommendation,
            "method_category_primary": classify_method_category_primary(recommendation),
            "recommendation_citations": citations,
            "method_cards": method_cards,
            "recommendation_packet": packet,
            "latest_mec_result": mec_text,
            "triage_completed_at": firestore.SERVER_TIMESTAMP,
            "triage_delivery_channel": delivery.get("channel"),
            "triage_delivery_status": delivery.get("status"),
            "triage_delivery_error": delivery.get("error") or delivery.get("whatsapp_error") or "",
        }, merge=True)
        record_audit_event(
            db=get_db(),
            phone=phone,
            actor=data.get("assigned_provider_id") or "system",
            action="recommendation_generated",
            metadata={"job_id": job_id, "channel": "provider", "method_count": len(method_cards or [])},
        )
    except Exception as exc:
        error_message = str(exc)
        print(f"Triage job {job_id} failed: {error_message}")
        job_ref.update({
            "status": "failed",
            "error": error_message,
            "completed_at": firestore.SERVER_TIMESTAMP,
        })
        if phone:
            get_db().collection("contraceptive_users").document(phone).set({
                "triage_status": "failed",
                "latest_triage_job_id": job_id,
                "triage_error": error_message,
                "triage_completed_at": firestore.SERVER_TIMESTAMP,
            }, merge=True)
        raise
