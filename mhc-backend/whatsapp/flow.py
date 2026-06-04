"""Inbound WhatsApp conversation state machine."""

from __future__ import annotations

from flask import session

from firebase_admin import firestore

from app_config import METHOD_MATCH_FALLBACK
from clinical_pipeline import generate_whatsapp_chat_reply
from db_client import get_db
from followup_tasks import attach_client_followup_reply
from geography import (
    admin_area_prompt,
    build_admin_area_firestore_fields,
    build_country_firestore_fields,
    country_confirm_prompt,
    country_prompt,
    invalid_location_prompt,
    is_valid_country_input,
    is_valid_location_input,
    normalize_admin_area,
    normalize_country,
)
from twilio_messaging import send_whatsapp_message
from whatsapp.constants import (
    CHILDREN_COUNT_OPTIONS,
    HEALTH_CONDITION_OPTIONS,
    LANGUAGE_ALIASES,
    LANGUAGES,
    METHOD_AVOID_OPTIONS,
    PARTNER_SUPPORT_OPTIONS,
    STRINGS,
    YES_NO_OPTIONS,
)
from whatsapp.helpers import (
    dispatch_whatsapp_method_match,
    extract_whatsapp_reply,
    get_user_state,
    option_selected,
    question_body,
    send_language_menu,
    send_main_menu,
    send_whatsapp_buttons,
    send_whatsapp_list_picker,
)
from whatsapp_helpers import send_long_whatsapp_message

def process_webhook_background(incoming_msg, user_phone, to_number):
    try:
        incoming_msg = str(incoming_msg or '').strip()
        user = get_user_state(user_phone)
        if not user:
            # First interaction - Ask for Language
            # Check if this person is being registered by a provider (session or web entry)
            provider_id = session.get('provider_id') # Fallback if being registered via webhook
            get_db().collection('contraceptive_users').document(user_phone).set({
                "stage": "AWAITING_LANGUAGE",
                "phone": user_phone,
                "assigned_provider_id": provider_id, # Link user to provider if known
                "created_at": firestore.SERVER_TIMESTAMP
            })
            lang_text = (
                "Welcome to ChaguoAI! Please select your language:\n"
                "1. English\n"
                "2. Kiswahili\n"
                "3. Français\n"
                "4. Português"
            )
            send_language_menu(to_number, user_phone)
            return
            
        stage = user.get("stage")
        lang = user.get("language", "english")
        global_commands = ["menu", "nyumbani", "mwanzo", "0", "hey", "hujambo", "habari", "hi", "hello"]
        if user.get("care_plan_status") == "awaiting_response" and incoming_msg.lower().strip() not in global_commands:
            if attach_client_followup_reply(db=get_db(), phone=user_phone, reply_text=incoming_msg):
                send_whatsapp_message(
                    to_number,
                    user_phone,
                    "Thank you. I have shared your follow-up reply with your CHW, who can review and support you.",
                )
                return

        if stage == "AWAITING_LANGUAGE":
            msg = incoming_msg.strip()
            lang_code = LANGUAGES.get(msg) or LANGUAGE_ALIASES.get(msg.lower())
            if lang_code:
                get_db().collection('contraceptive_users').document(user_phone).update({
                    "language": lang_code,
                    "stage": "MAIN_MENU"
                })
                # Show Main Menu in selected language
                send_main_menu(to_number, user_phone, lang_code)
            else:
                send_whatsapp_message(to_number, user_phone, "Invalid selection. Please reply with 1, 2, 3 or 4.")
            return

        if stage == "MAIN_MENU":
            msg = incoming_msg.lower().strip()
            s = STRINGS[lang]
            if option_selected(msg, 1, 'njia', 'match', 'method', 'uzazi', 'panga', 'birth', 'plan', 'tayari', 'kuanza', 'recommandations', 'recomendacoes', 'metodo'):
                get_db().collection('contraceptive_users').document(user_phone).update({"stage": "AWAITING_NAME"})
                send_whatsapp_message(to_number, user_phone, s["ask_name"])
                return
            if option_selected(msg, 2, 'swali', 'question', 'pergunta'):
                prompt = {
                    "english": "Ask me anything about contraception. I'm listening...",
                    "swahili": "Unaweza kuniuliza swali lolote kuhusu uzazi. Nausikiliza...",
                    "french": "Posez-moi n'importe quelle question sur la contraception. Je vous ecoute...",
                    "portuguese": "Pergunte-me qualquer coisa sobre contracepcao. Estou ouvindo..."
                }
                send_whatsapp_message(to_number, user_phone, prompt.get(lang, prompt["english"]))
                return
            if option_selected(msg, 3, 'myth', 'fact', 'imani', 'ukweli', 'mythe', 'mito'):
                get_db().collection('contraceptive_users').document(user_phone).update({"stage": "AWAITING_MYTH_QUESTION"})
                prompt = {
                    "english": "Tell me the contraception myth or concern you have heard, and I will answer using clinical guidance.",
                    "swahili": "Ni imani au wasiwasi gani kuhusu uzazi umesikia? Nitakujibu kwa kutumia mwongozo wa kitabibu.",
                    "french": "Dites-moi le mythe ou la preoccupation sur la contraception, et je repondrai avec des conseils cliniques.",
                    "portuguese": "Conte-me o mito ou preocupacao sobre contracepcao, e responderei com orientacao clinica."
                }
                send_whatsapp_message(to_number, user_phone, prompt.get(lang, prompt["english"]))
                return
            if option_selected(msg, 4, 'side', 'effect', 'madhara', 'effet', 'efeito', 'report', 'ripoti'):
                get_db().collection('contraceptive_users').document(user_phone).update({"stage": "AWAITING_SIDE_EFFECT_REPORT"})
                prompt = {
                    "english": "Please describe the side effect, when it started, and the method you are using. If symptoms are severe, seek urgent care now.",
                    "swahili": "Tafadhali eleza madhara, yalianza lini, na njia unayotumia. Kama dalili ni kali, tafuta huduma ya dharura sasa.",
                    "french": "Decrivez l'effet secondaire, sa date de debut et la methode utilisee. Si les symptomes sont graves, consultez en urgence.",
                    "portuguese": "Descreva o efeito colateral, quando comecou e o metodo usado. Se os sintomas forem graves, procure atendimento urgente."
                }
                send_whatsapp_message(to_number, user_phone, prompt.get(lang, prompt["english"]))
                return
            if option_selected(msg, 5, 'language', 'lugha', 'langue', 'idioma', 'change', 'badilisha', 'changer', 'mudar'):
                get_db().collection('contraceptive_users').document(user_phone).update({"stage": "AWAITING_LANGUAGE"})
                send_language_menu(to_number, user_phone)
                return
            if any(k in msg for k in ['1', 'njia', 'match', 'uzazi', 'panga', 'birth', 'plan', 'tayari', 'kuanza', 'recommandations', 'recomendações']):
                get_db().collection('contraceptive_users').document(user_phone).update({"stage": "AWAITING_NAME"})
                send_whatsapp_message(to_number, user_phone, s["ask_name"])
            elif '2' in msg or 'swali' in msg or 'question' in msg or 'pergunta' in msg:
                prompt = {
                    "english": "Ask me anything about contraception. I'm listening...",
                    "swahili": "Unaweza kuniuliza swali lolote kuhusu uzazi. Nausikiliza...",
                    "french": "Posez-moi n'importe quelle question sur la contraception. Je vous écoute...",
                    "portuguese": "Pergunte-me qualquer coisa sobre contracepção. Estou ouvindo..."
                }
                send_whatsapp_message(to_number, user_phone, prompt.get(lang, prompt["english"]))
            elif '3' in msg or 'about' in msg or 'propos' in msg or 'sobre' in msg:
                 info = {
                    "english": "ChaguoAI is a WHO-based decision support system for safe contraception.",
                    "swahili": "ChaguoAI ni mfumo wa kusaidia maamuzi ya uzazi kulingana na WHO.",
                    "french": "ChaguoAI est un système de support à la décision basé sur l'OMS.",
                    "portuguese": "ChaguoAI é um sistema de apoio à decisão baseado na OMS."
                }
                 send_whatsapp_message(to_number, user_phone, info.get(lang, info["english"]))
            else:
                # Intent Detection happens later in the general chat block
                pass
        
        # --- (IMPLEMENT 13 QUESTIONS STATE MACHINE WITH LOCALIZATION) ---
        q = SURVEY_STRINGS[lang]

        if stage == "AWAITING_SIDE_EFFECT_REPORT":
            report_text = incoming_msg.strip()
            get_db().collection('contraceptive_users').document(user_phone).collection('side_effects').add({
                'report': report_text,
                'language': lang,
                'timestamp': firestore.SERVER_TIMESTAMP,
                'source': 'whatsapp'
            })
            get_db().collection('contraceptive_users').document(user_phone).update({"stage": "MAIN_MENU"})
            response = {
                "english": "Thank you. I have recorded this for review. If you have heavy bleeding, severe lower abdominal pain, chest pain, shortness of breath, fainting, severe headache, or signs of pregnancy, please seek urgent care now.",
                "swahili": "Ahsante. Nimehifadhi taarifa hii kwa kufuatiliwa. Kama una damu nyingi, maumivu makali ya tumbo la chini, maumivu ya kifua, shida ya kupumua, kuzimia, kichwa kikali, au dalili za ujauzito, tafuta huduma ya dharura sasa.",
                "french": "Merci. J'ai enregistre ces informations pour suivi. En cas de saignement abondant, douleur abdominale severe, douleur thoracique, essoufflement, malaise, cefalee severe ou signes de grossesse, consultez en urgence.",
                "portuguese": "Obrigado. Registrei isso para acompanhamento. Se houver sangramento intenso, dor abdominal forte, dor no peito, falta de ar, desmaio, dor de cabeca intensa ou sinais de gravidez, procure atendimento urgente."
            }
            send_whatsapp_message(to_number, user_phone, response.get(lang, response["english"]))
            return

        if stage == "AWAITING_MYTH_QUESTION":
            get_db().collection('contraceptive_users').document(user_phone).update({"stage": "MAIN_MENU"})
            incoming_msg = f"Please answer this contraception myth or concern clearly and clinically: {incoming_msg.strip()}"
            user["stage"] = "MAIN_MENU"
        
        if stage == "AWAITING_NAME":
            get_db().collection('contraceptive_users').document(user_phone).update({
                "name": incoming_msg.strip(),
                "stage": "AWAITING_COUNTRY",
            })
            send_whatsapp_message(to_number, user_phone, country_prompt(lang))
            return

        if stage == "AWAITING_COUNTRY":
            if not is_valid_country_input(incoming_msg):
                send_whatsapp_message(to_number, user_phone, invalid_location_prompt(lang, "country"))
                return
            normalized = normalize_country(incoming_msg)
            if normalized.needs_confirmation:
                get_db().collection('contraceptive_users').document(user_phone).update({
                    "stage": "AWAITING_COUNTRY_CONFIRM",
                    "pending_country": normalized.canonical,
                    "pending_country_raw": normalized.raw,
                    "pending_country_match_confidence": normalized.confidence,
                })
                send_whatsapp_message(
                    to_number, user_phone, country_confirm_prompt(lang, normalized.canonical)
                )
                return
            get_db().collection('contraceptive_users').document(user_phone).update({
                **build_country_firestore_fields(normalized, source="whatsapp"),
                "stage": "AWAITING_ADMIN_AREA",
            })
            send_whatsapp_message(
                to_number, user_phone, admin_area_prompt(lang, normalized.canonical)
            )
            return

        if stage == "AWAITING_COUNTRY_CONFIRM":
            msg = incoming_msg.lower().strip()
            if msg in ("2", "no", "hapana", "non", "nao", "não"):
                get_db().collection('contraceptive_users').document(user_phone).update({
                    "stage": "AWAITING_COUNTRY",
                    "pending_country": firestore.DELETE_FIELD,
                    "pending_country_raw": firestore.DELETE_FIELD,
                    "pending_country_match_confidence": firestore.DELETE_FIELD,
                })
                send_whatsapp_message(to_number, user_phone, country_prompt(lang))
                return
            if msg not in ("1", "yes", "ndio", "oui", "sim"):
                send_whatsapp_message(
                    to_number, user_phone, country_confirm_prompt(lang, user.get("pending_country", ""))
                )
                return
            confirmed = NormalizedCountry(
                user.get("pending_country_raw", ""),
                user.get("pending_country", ""),
                user.get("pending_country_match_confidence", "fuzzy"),
                False,
            )
            get_db().collection('contraceptive_users').document(user_phone).update({
                **build_country_firestore_fields(confirmed, source="whatsapp"),
                "stage": "AWAITING_ADMIN_AREA",
                "pending_country": firestore.DELETE_FIELD,
                "pending_country_raw": firestore.DELETE_FIELD,
                "pending_country_match_confidence": firestore.DELETE_FIELD,
            })
            send_whatsapp_message(
                to_number, user_phone, admin_area_prompt(lang, confirmed.canonical)
            )
            return

        if stage == "AWAITING_ADMIN_AREA":
            if not is_valid_location_input(incoming_msg):
                send_whatsapp_message(to_number, user_phone, invalid_location_prompt(lang, "admin_area"))
                return
            country = user.get("country", "")
            get_db().collection('contraceptive_users').document(user_phone).update({
                **build_admin_area_firestore_fields(incoming_msg, country, source="whatsapp"),
                "location_captured_at": firestore.SERVER_TIMESTAMP,
                "stage": "AWAITING_Q1_AGE",
            })
            send_whatsapp_message(to_number, user_phone, q["q1"])
            return
            
        if stage == "AWAITING_Q1_AGE":
            match = re.search(r'\d+', incoming_msg)
            if match:
                get_db().collection('contraceptive_users').document(user_phone).update({"age": int(match.group()), "stage": "AWAITING_Q2_PERIOD"})
                send_whatsapp_buttons(to_number, user_phone, q["q2"], q["q2_options"])
            else:
                error_msg = {"english": "Please reply with a valid number.", "swahili": "Tafadhali jibu kwa nambari halali.", "french": "Veuillez répondre avec un nombre valide.", "portuguese": "Por favor, responda com um número válido."}
                send_whatsapp_message(to_number, user_phone, error_msg.get(lang, error_msg["english"]))
            return

        if stage == "AWAITING_Q2_PERIOD":
            get_db().collection('contraceptive_users').document(user_phone).update({"last_period": incoming_msg.strip(), "stage": "AWAITING_Q3_BABY"})
            send_whatsapp_buttons(to_number, user_phone, q["q3"], YES_NO_OPTIONS.get(lang, YES_NO_OPTIONS["english"]))
            return

        if stage == "AWAITING_Q3_BABY":
            is_yes = any(word in incoming_msg.lower() for word in ['ndio', 'yes', 'oui', 'sim', '1'])
            get_db().collection('contraceptive_users').document(user_phone).update({"baby_under_6m": incoming_msg.strip(), "stage": "AWAITING_Q3A_BREASTFEEDING" if is_yes else "AWAITING_Q4_CHILDREN"})
            if is_yes:
                send_whatsapp_buttons(to_number, user_phone, q["q3a"], YES_NO_OPTIONS.get(lang, YES_NO_OPTIONS["english"]))
            else:
                send_whatsapp_buttons(to_number, user_phone, q["q4"], CHILDREN_COUNT_OPTIONS)
            return

        if stage == "AWAITING_Q3A_BREASTFEEDING":
            get_db().collection('contraceptive_users').document(user_phone).update({"breastfeeding_only": incoming_msg.strip(), "stage": "AWAITING_Q4_CHILDREN"})
            send_whatsapp_buttons(to_number, user_phone, q["q4"], CHILDREN_COUNT_OPTIONS)
            return
 
        if stage == "AWAITING_Q4_CHILDREN":
            get_db().collection('contraceptive_users').document(user_phone).update({"living_children": incoming_msg.strip(), "stage": "AWAITING_Q5_MORE_CHILDREN"})
            send_whatsapp_buttons(to_number, user_phone, q["q5"], q["q5_options"])
            return
 
        if stage == "AWAITING_Q5_MORE_CHILDREN":
            get_db().collection('contraceptive_users').document(user_phone).update({"more_children": incoming_msg.strip(), "stage": "AWAITING_Q6_HEALTH"})
            send_whatsapp_options(to_number, user_phone, question_body(q["q6"]), HEALTH_CONDITION_OPTIONS, multi_select=True, button_text="Conditions", language=lang)
            return
 
        if stage == "AWAITING_Q6_HEALTH":
            get_db().collection('contraceptive_users').document(user_phone).update({"health_conditions": incoming_msg.strip(), "stage": "AWAITING_Q7_HIV"})
            send_whatsapp_buttons(to_number, user_phone, q["q7"], q["q7_options"])
            return

        if stage == "AWAITING_Q7_HIV":
            get_db().collection('contraceptive_users').document(user_phone).update({"hiv_status": incoming_msg.strip(), "stage": "AWAITING_Q8_SMOKE"})
            send_whatsapp_buttons(to_number, user_phone, q["q8"], YES_NO_OPTIONS.get(lang, YES_NO_OPTIONS["english"]))
            return

        if stage == "AWAITING_Q8_SMOKE":
            get_db().collection('contraceptive_users').document(user_phone).update({"smoke": incoming_msg.strip(), "stage": "AWAITING_Q9_PREVIOUS_USE"})
            send_whatsapp_buttons(to_number, user_phone, q["q9"], YES_NO_OPTIONS.get(lang, YES_NO_OPTIONS["english"]))
            return

        if stage == "AWAITING_Q9_PREVIOUS_USE":
            is_yes = any(word in incoming_msg.lower() for word in ['ndio', 'yes', 'oui', 'sim', '1'])
            get_db().collection('contraceptive_users').document(user_phone).update({"previous_use": incoming_msg.strip(), "stage": "AWAITING_Q9A_STOP" if is_yes else "AWAITING_Q10_PARTNER"})
            if is_yes:
                send_whatsapp_buttons(to_number, user_phone, q["q9a"], q["q9a_options"])
            else:
                send_whatsapp_buttons(to_number, user_phone, q["q10"], PARTNER_SUPPORT_OPTIONS.get(lang, PARTNER_SUPPORT_OPTIONS["english"]))
            return

        if stage == "AWAITING_Q9A_STOP":
            get_db().collection('contraceptive_users').document(user_phone).update({"stop_reason": incoming_msg.strip(), "stage": "AWAITING_Q10_PARTNER"})
            send_whatsapp_buttons(to_number, user_phone, q["q10"], PARTNER_SUPPORT_OPTIONS.get(lang, PARTNER_SUPPORT_OPTIONS["english"]))
            return

        if stage == "AWAITING_Q10_PARTNER":
            get_db().collection('contraceptive_users').document(user_phone).update({"partner_support": incoming_msg.strip(), "stage": "AWAITING_Q11_FACILITY"})
            send_whatsapp_buttons(to_number, user_phone, q["q11"], q["q11_options"])
            return

        if stage == "AWAITING_Q11_FACILITY":
            get_db().collection('contraceptive_users').document(user_phone).update({"facility_access": incoming_msg.strip(), "stage": "AWAITING_Q12_STI"})
            send_whatsapp_buttons(to_number, user_phone, q["q12"], YES_NO_OPTIONS.get(lang, YES_NO_OPTIONS["english"]))
            return

        if stage == "AWAITING_Q12_STI":
            get_db().collection('contraceptive_users').document(user_phone).update({"sti_concern": incoming_msg.strip(), "stage": "AWAITING_Q13_PREFERENCES"})
            send_whatsapp_options(to_number, user_phone, question_body(q["q13"]), METHOD_AVOID_OPTIONS, multi_select=True, button_text="Methods", language=lang)
            return

        if stage == "AWAITING_Q13_PREFERENCES":
            prefer = incoming_msg.strip()
            user["prefer_not_to_use"] = prefer
            user["stage"] = "REGISTERED"
            user["method_match_pending"] = True

            get_db().collection('contraceptive_users').document(user_phone).update({
                "prefer_not_to_use": prefer,
                "registered_at": firestore.SERVER_TIMESTAMP,
                "stage": "REGISTERED",
                "method_match_pending": True,
                "method_match_status": "queued",
            })
            send_whatsapp_message(to_number, user_phone, q["finished"])
            dispatch_whatsapp_method_match(user_phone, to_number, lang, user)
            return

        
        # --- GLOBAL COMMANDS ---
        if incoming_msg.lower().strip() in global_commands:
            get_db().collection('contraceptive_users').document(user_phone).update({"stage": "MAIN_MENU"})
            user = get_user_state(user_phone) # Refresh user data
            name = user.get('name', '')
            s = STRINGS[lang]
            menu_text = s["menu"]
            if name:
                # Personalize greeting
                greeting = {
                    "english": f"Hello {name}! ",
                    "swahili": f"Habari {name}! ",
                    "french": f"Bonjour {name}! ",
                    "portuguese": f"Olá {name}! "
                }
                menu_text = greeting.get(lang, "Hello! ") + menu_text
            
            send_main_menu(to_number, user_phone, lang, greeting.get(lang, "Hello! ") if name else None)
            return

        # --- THE WHO MEC PIPELINE & GENERAL CHAT ---
        if user.get("stage") in ["REGISTERED", "MAIN_MENU"]:
            if user.get("method_match_pending") or user.get("method_match_status") == "queued":
                print(f"[{user_phone}] Method match still processing — skipping duplicate AI call")
                return

            print(f"\n==========================================")
            print(f"[{user_phone}] AI chat processing...")
            user["phone"] = user_phone
            try:
                reply_text = generate_whatsapp_chat_reply(user, incoming_msg)
                if not reply_text.strip():
                    raise RuntimeError("Empty chat reply from Gemini")
                send_long_whatsapp_message(send_whatsapp_message, to_number, user_phone, reply_text)
                print(f"[{user_phone}] Chat success!")
            except Exception as chat_exc:
                print(f"[{user_phone}] Chat error: {chat_exc}")
                fallback = METHOD_MATCH_FALLBACK.get(lang, METHOD_MATCH_FALLBACK["english"])
                send_whatsapp_message(to_number, user_phone, fallback)
            print(f"==========================================\n")
            return

    except Exception as e:
        print(f"[{user_phone}] PIPELINE ERROR: {e}")
        import traceback
        traceback.print_exc()
        send_whatsapp_message(to_number, user_phone, "Samahani, mfumo wetu una hitilafu kwa sasa. Tafadhali jaribu tena baadaye.")

