import json

from firebase_admin import firestore

from rag_ingestor import get_retriever
from rag_prompt import build_system_prompt
from who_mec_engine import UserProfile, run_mec_assessment, format_mec_result_for_llm
from main import (
    TWILIO_NUMBER,
    db,
    generate_gemini_text,
    send_whatsapp_message,
    to_fhir_patient,
)


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

        prof = UserProfile()
        prof.age_years = int(data.get('age', 18))
        prof.number_of_children = int(data.get('parity', 0))
        prof.breastfeeding = "Yes" in data.get('nursing', 'No')
        prof.smoker = "Yes" in data.get('smoking', 'No')

        prof.fertility_intention = data.get('future_children')
        if "High" in data.get('blood_pressure', ''):
            prof.hypertension = True
        if "Positive" in data.get('hiv_status', ''):
            prof.hiv_positive = True
        if "High" in data.get('sti_risk', ''):
            prof.high_sti_risk = True

        mec_result = run_mec_assessment(prof)
        mec_text = format_mec_result_for_llm(mec_result)

        search_query = (
            f"Contraception for {data.get('age')}yo, parity {data.get('parity')}, "
            f"{data.get('health_history')}. Preference: {data.get('preference')}"
        )
        retriever = get_retriever()
        chunks = retriever.retrieve(search_query, top_k=3)
        context = retriever.format_context_for_llm(chunks)

        sys_prompt = build_system_prompt(
            mec_result_text=mec_text,
            retrieved_context=context,
            user_profile_summary=f"Clinical Web Triage for {data.get('name')} ({phone})",
            channel="web",
            language="english"
        )

        full_query = (
            f"{sys_prompt}\n\nClient Data: {json.dumps(data)}\n\n"
            "Please provide a final recommendation. IMPORTANT: If you recommend Long-Acting methods "
            "(Implants/IUDs/Sterilization), you MUST include a 'Referral Note' section explaining that "
            "the client needs to visit a level 4+ hospital for the procedure."
        )

        recommendation = generate_gemini_text(full_query, max_output_tokens=900)

        sms_body = (
            f"Habari {data.get('name')}! Nimerecord registration yako ya ChaguoAI. "
            f"Recommendation yako: {recommendation[:200]}... "
            "Unaweza kuendelea kunitumia message hapa kwa maelezo zaidi."
        )
        send_whatsapp_message(TWILIO_NUMBER, phone, sms_body)

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
