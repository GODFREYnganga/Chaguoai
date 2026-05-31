import json

from firebase_admin import firestore

from rag_ingestor import get_retriever
from rag_prompt import build_system_prompt, format_user_profile_for_prompt
from user_profile_mapper import map_firestore_user_to_profile
from who_mec_engine import run_mec_assessment, format_mec_result_for_llm
from whatsapp_helpers import send_long_whatsapp_message, split_message_at_sentences
from main import (
    TWILIO_NUMBER,
    db,
    generate_gemini_text,
    send_whatsapp_message,
    to_fhir_patient,
)


def _map_triage_form_to_profile(data: dict):
    """Map provider triage wizard fields to a Firestore-like user dict."""
    user_like = {
        "age": data.get("age"),
        "last_period": data.get("last_period"),
        "baby_under_6m": "Yes" if "Yes" in str(data.get("nursing", "")) else "No",
        "breastfeeding_only": "Yes" if "Less than" in str(data.get("nursing", "")) else "No",
        "living_children": data.get("parity"),
        "more_children": data.get("future_children"),
        "health_conditions": "1" if "High" in str(data.get("blood_pressure", "")) else "7",
        "hiv_status": data.get("hiv_status"),
        "smoke": data.get("smoking"),
        "previous_use": "No",
        "partner_support": "Yes",
        "facility_access": "Easy",
        "sti_concern": "Yes" if "High" in str(data.get("sti_risk", "")) else "No",
        "prefer_not_to_use": data.get("preference", ""),
        "name": data.get("name"),
    }
    health = str(data.get("health_history", "")).lower()
    codes = []
    if "migraine" in health:
        codes.append("6")
    if "liver" in health:
        codes.append("4")
    if "heart" in health:
        codes.append("3")
    if codes:
        user_like["health_conditions"] = ",".join(codes)
    return map_firestore_user_to_profile(user_like)


def process_triage_job(job_id, data):
    job_ref = db.collection('triage_jobs').document(job_id)
    phone = data.get('phone')

    try:
        job_ref.update({
            "status": "processing",
            "started_at": firestore.SERVER_TIMESTAMP,
        })
        if phone:
            db.collection('contraceptive_users').document(phone).set({
                "triage_status": "processing",
                "latest_triage_job_id": job_id,
                "triage_started_at": firestore.SERVER_TIMESTAMP,
            }, merge=True)

        prof = _map_triage_form_to_profile(data)
        mec_result = run_mec_assessment(prof)
        mec_text = format_mec_result_for_llm(mec_result)
        prof_summary = format_user_profile_for_prompt({k: v for k, v in prof.__dict__.items() if v is not None})

        search_query = (
            f"Contraception for age {data.get('age')}, parity {data.get('parity')}, "
            f"history {data.get('health_history')}. Preference: {data.get('preference')}"
        )
        retriever = get_retriever()
        chunks = retriever.retrieve(search_query, top_k=4)
        context = retriever.format_context_for_llm(chunks)

        sys_prompt = build_system_prompt(
            mec_result_text=mec_text,
            retrieved_context=context,
            user_profile_summary=f"{prof_summary}\n\nProvider triage for {data.get('name')} ({phone})",
            channel="web",
            language="english",
            user_name=data.get("name", ""),
        )

        full_query = (
            f"{sys_prompt}\n\nClient Data: {json.dumps(data)}\n\n"
            "Provide a final recommendation for this client. You MUST output 2-3 methods "
            "using [METHOD_CARD] blocks (NAME, SUMMARY, DETAILS). Keep each SUMMARY to one sentence. "
            "If you recommend implants, IUDs, or sterilization, include a Referral Note that "
            "the client should visit a facility with trained providers for insertion."
        )

        recommendation = generate_gemini_text(full_query, max_output_tokens=900)

        sms_intro = f"Habari {data.get('name')}! Your ChaguoAI Method Match is ready."
        sms_body = f"{sms_intro}\n\n{split_message_at_sentences(recommendation, 1200)[0]}"
        send_long_whatsapp_message(send_whatsapp_message, TWILIO_NUMBER, phone, sms_body)

        fhir_view = to_fhir_patient(data)
        job_ref.update({
            "status": "completed",
            "recommendation": recommendation,
            "mec_result": mec_text,
            "fhir_view": fhir_view,
            "completed_at": firestore.SERVER_TIMESTAMP,
        })
        db.collection('contraceptive_users').document(phone).set({
            "triage_status": "completed",
            "latest_triage_job_id": job_id,
            "latest_recommendation": recommendation,
            "matched_method": recommendation,
            "latest_mec_result": mec_text,
            "triage_completed_at": firestore.SERVER_TIMESTAMP,
        }, merge=True)
    except Exception as e:
        error_message = str(e)
        print(f"Triage job {job_id} failed: {error_message}")
        job_ref.update({
            "status": "failed",
            "error": error_message,
            "completed_at": firestore.SERVER_TIMESTAMP,
        })
        if phone:
            db.collection('contraceptive_users').document(phone).set({
                "triage_status": "failed",
                "latest_triage_job_id": job_id,
                "triage_error": error_message,
                "triage_completed_at": firestore.SERVER_TIMESTAMP,
            }, merge=True)
        raise
