import json
import os
import re
from who_mec_engine import UserProfile, run_mec_assessment, format_mec_result_for_llm
from rag_ingestor import get_retriever
from rag_prompt import build_system_prompt, format_user_profile_for_prompt

def process_method_match(answers, phone_number, db, client):
    ans_index = 0
    responses = {}
    
    # Q1
    if ans_index >= len(answers): return "CON Q1/13: How old are you? (Reply with number e.g. 25)"
    responses['age'] = answers[ans_index]
    ans_index += 1
    
    # Q2
    if ans_index >= len(answers): return "CON Q2/13: Date of last period / pregnancy status:\n1. Period within last 4 weeks\n2. Unsure\n3. Currently pregnant"
    responses['last_period'] = answers[ans_index]
    ans_index += 1
    
    # Q3
    if ans_index >= len(answers): return "CON Q3/13: Do you have a baby under 6 months?\n1. Yes\n2. No"
    q3_ans = answers[ans_index]
    responses['baby_under_6m'] = q3_ans
    ans_index += 1
    
    # Q3a
    if q3_ans == "1":
        if ans_index >= len(answers): return "CON Q3a: Are you breastfeeding only breast milk?\n1. Yes\n2. No"
        responses['breastfeeding'] = answers[ans_index]
        ans_index += 1
        
    # Q4
    if ans_index >= len(answers): return "CON Q4/13: Number of living children (Reply with number e.g. 0)"
    responses['children'] = answers[ans_index]
    ans_index += 1
    
    # Q5
    if ans_index >= len(answers): return "CON Q5/13: Do you want more children?\n1. Yes, within 2 yrs\n2. Yes, later\n3. No more"
    responses['more_children'] = answers[ans_index]
    ans_index += 1
    
    # Q6
    if ans_index >= len(answers): return "CON Q6/13: Health conditions (Comma-separated, e.g. 1,2 or 7 for none):\n1.High BP 2.Diabetes 3.Heart disease 4.Liver 5.Cancer 6.Migraines 7.None"
    responses['health'] = answers[ans_index]
    ans_index += 1
    
    # Q7
    if ans_index >= len(answers): return "CON Q7/13: Are you living with HIV?\n1. Yes\n2. No\n3. Prefer not to say"
    responses['hiv'] = answers[ans_index]
    ans_index += 1
    
    # Q8
    if ans_index >= len(answers): return "CON Q8/13: Do you smoke?\n1. Yes\n2. No"
    responses['smoke'] = answers[ans_index]
    ans_index += 1
    
    # Q9
    if ans_index >= len(answers): return "CON Q9/13: Have you used contraception before?\n1. Yes\n2. No"
    q9_ans = answers[ans_index]
    responses['used_before'] = q9_ans
    ans_index += 1
    
    # Q9a
    if q9_ans == "1":
        if ans_index >= len(answers): return "CON Q9a: Did you stop?\n1. Still using\n2. Stopped (had side effects)\n3. Stopped (other reason)\n4. Switched to another"
        responses['stop_reason'] = answers[ans_index]
        ans_index += 1
        
    # Q10
    if ans_index >= len(answers): return "CON Q10/13: Partner support contraception?\n1. Yes\n2. No\n3. No partner"
    responses['partner'] = answers[ans_index]
    ans_index += 1
    
    # Q11
    if ans_index >= len(answers): return "CON Q11/13: How hard is it to visit a health facility?\n1. Easy\n2. Sometimes hard\n3. Very hard"
    responses['facility_access'] = answers[ans_index]
    ans_index += 1
    
    # Q12
    if ans_index >= len(answers): return "CON Q12/13: Are you concerned about STI protection too?\n1. Yes\n2. No"
    responses['sti'] = answers[ans_index]
    ans_index += 1
    
    # Q13
    if ans_index >= len(answers): return "CON Q13/13: Methods you prefer not to use? (Comma-separated, e.g. 1,2 or 5 for None):\n1.Pills 2.Injectables 3.IUD 4.Implants 5.None"
    responses['prefer_not'] = answers[ans_index]
    ans_index += 1
    
    # Execution Block
    if client:
        try:
            print(f"[{phone_number}] USSD: Mapping profile to MEC...")
            prof = UserProfile()
            prof.age_years = int(responses.get('age', 25))
            
            lp = str(responses.get('last_period', ''))
            if '3' in lp: prof.pregnancy_status = 'pregnant'
            
            bb = str(responses.get('baby_under_6m', ''))
            if '1' in bb:
                prof.postpartum_days = 90
                bf = str(responses.get('breastfeeding', ''))
                if '1' in bf:
                    prof.breastfeeding = True
                    prof.breastfeeding_exclusively = True
                    prof.baby_age_months = 3.0
                    
            hc = str(responses.get('health', ''))
            if '1' in hc: prof.hypertension = True
            if '2' in hc: prof.diabetes = True
            if '3' in hc: prof.heart_disease = True
            if '4' in hc: prof.liver_disease = True
            if '5' in hc: prof.breast_cancer_current = True
            if '6' in hc: prof.migraine_without_aura = True
            
            if '1' in str(responses.get('hiv', '')): prof.hiv_positive = True
            if '1' in str(responses.get('smoke', '')): prof.smoker = True
            if '1' in str(responses.get('sti', '')): prof.high_sti_risk = True

            mec_result = run_mec_assessment(prof)
            mec_text = format_mec_result_for_llm(mec_result, language='english')
            
            retriever = get_retriever()
            chunks = retriever.retrieve("Top contraceptive method options based on guidelines.")
            context_str = retriever.format_context_for_llm(chunks)
            
            sys_prompt = build_system_prompt(
                mec_result_text=mec_text,
                retrieved_context=context_str,
                user_profile_summary="USSD User Profile",
                channel="ussd",
                language="english"
            )
            
            print(f"[{phone_number}] USSD: Generating Final Decision with Gemini...")
            ai_response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=f"{sys_prompt}\n\nInstruction: Write the top Tier-1 safe method for this user based strictly on the MEC Results. Use a maximum of 140 characters."
            )
            response_text = ai_response.text.strip()
            
            if db:
                db.collection('contraceptive_users').document(phone_number).set({'matched_method': response_text, 'stage': 'REGISTERED'}, merge=True)
            return f"END Match: {response_text}"
        except Exception as e:
            print(f"USSD ERROR: {e}")
            return "END We received your data, but couldn't analyze the match right now. An SMS will follow."
            
    return "END We have received your responses. We will SMS you shortly."

def handle_ussd_request(session_id, service_code, phone_number, text, db=None, client=None):
    text_array = text.split('*') if text else []
    if text == "": text_array = []
    
    if len(text_array) == 0:
        response = "CON Welcome to Contraceptive DSS\n1. Method Match\n2. Report Side Effects\n3. Check Method\n4. Contact a Health Worker"
        return response

    choice = text_array[0]
    
    if choice == "1":
        return process_method_match(text_array[1:], phone_number, db, client)
    elif choice == "2":
        if len(text_array) == 1:
            return "CON Please type a brief description of your side effects below:"
        else:
            side_effect_text = text_array[1]
            if db:
                try:
                    db.collection('contraceptive_users').document(phone_number).collection('side_effects').add({
                        'report': side_effect_text,
                        'timestamp': 'CURRENT_TIMESTAMP'
                    })
                except Exception: pass
            return "END Your side effects have been recorded securely. A health worker will review them on the DSS portal."
    elif choice == "3":
        if db:
            try:
                user_doc = db.collection('contraceptive_users').document(phone_number).get()
                if user_doc.exists:
                    data = user_doc.to_dict()
                    method = data.get('matched_method')
                    if method:
                        return f"END Your active matched method info:\n{method[:120]}..."
            except Exception: pass
        return "END We could not find an active matched method for your number. Please dial Menu 1 for a Method Match."
    elif choice == "4":
        return "END For immediate clinical support, please call our toll-free DSS hotline at 0800-720-123."
    else:
        return "END Invalid choice. Please try again."
