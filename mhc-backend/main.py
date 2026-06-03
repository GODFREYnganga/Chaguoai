import os
import re
import datetime
import json
import time
import threading
from dotenv import load_dotenv
from flask import Flask, request, Response, render_template, session, redirect, url_for, jsonify
from twilio.twiml.messaging_response import MessagingResponse
from firebase_admin import firestore

from app_config import (
    ADMIN_CODE,
    METHOD_MATCH_FALLBACK,
    WEB_PROVIDER_MAX_OUTPUT_TOKENS,
)
from clinical_pipeline import generate_whatsapp_chat_reply
from db_client import get_db, init_firebase
from fhir_utils import to_fhir_patient
from gemini_client import generate_gemini_text
from health_check import run_health_checks
from method_match_tasks import process_whatsapp_method_match_job
from ussd_logic import handle_ussd_request
from rag_ingestor import get_retriever
from rag_prompt import build_system_prompt, build_web_clinical_instruction
from task_queue import (
    TRIAGE_JOB_FAILURE_TTL_SECONDS,
    TRIAGE_JOB_RESULT_TTL_SECONDS,
    TRIAGE_JOB_TIMEOUT_SECONDS,
    get_triage_queue,
)
from user_profile_mapper import serializable_user_snapshot
from admin_analytics import build_admin_stats, export_clients_csv, collect_safety_items
from geography import (
    NormalizedCountry,
    admin_area_label,
    admin_area_prompt,
    build_admin_area_firestore_fields,
    build_country_firestore_fields,
    country_confirm_prompt,
    country_prompt,
    invalid_location_prompt,
    is_valid_country_input,
    is_valid_location_input,
    normalize_country,
    normalize_admin_area,
    countries_for_api,
)
from method_categories import classify_method_category_primary
from method_library import get_method_info, all_methods
from method_selection import (
    build_selection_client_message,
    create_referral,
    record_followup_outcome,
    select_method,
)
from client_messages import compose_followup_reminder
from response_cards import parse_method_cards
from response_cards import build_fallback_method_cards
from response_cards import resolve_method_cards
from twilio_messaging import (
    TWILIO_TEMPLATES,
    TWILIO_NUMBER,
    send_whatsapp_with_sms_fallback,
    send_whatsapp_message,
    send_whatsapp_options,
)
from whatsapp_helpers import send_long_whatsapp_message

load_dotenv()

# Configure folders relative to this script's location
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.abspath(os.path.join(BASE_DIR, '..', 'mhc-dashboard'))
static_dir = os.path.abspath(os.path.join(BASE_DIR, '..', 'static'))

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'mhc_super_secret_123')

@app.route("/")
def index():
    return "Contraception DSS Backend is running. Access /admin or /provider for dashboards."

@app.route("/health", methods=["GET"])
def health():
    checks = run_health_checks()
    status_code = 200 if checks.get("overall", {}).get("ok") else 503
    return jsonify(checks), status_code

try:
    print(f"[DEBUG] Starting initialization. Port: {os.environ.get('PORT', '8080')}")
    init_firebase()
    db = get_db()
except Exception as e:
    print(f"CRITICAL Warning: Could not initialize firebase. {e}")
    db = None

def format_to_e164(phone, country_code="+254"):
    """Converts local phone formats (e.g. 07...) to E.164 (+254...)."""
    if not phone: return phone
    # Remove all non-numeric characters except +
    cleaned = re.sub(r'[^\d+]', '', phone)
    # Handle Kenyan format starting with 0
    if cleaned.startswith('0') and len(cleaned) == 10:
        return f"{country_code}{cleaned[1:]}"
    # If it starts with country code without +
    if cleaned.startswith(country_code[1:]) and not cleaned.startswith('+'):
        return f"+{cleaned}"
    # If no + and seems like a local number, prepend country code
    if len(cleaned) <= 10 and not cleaned.startswith('+'):
        return f"{country_code}{cleaned}"
    return cleaned

# Globals
TWILIO_NUMBER = os.environ.get('TWILIO_WHATSAPP_NUMBER', 'whatsapp:+14155238886')

def _log_whatsapp_template_status():
    status = TWILIO_TEMPLATES.status_report()
    print(f"[WhatsApp Templates] {' '.join(f'{k}={v}' for k, v in status.items())}")
    missing = TWILIO_TEMPLATES.missing_for_survey()
    if missing:
        print("[WhatsApp Templates] Missing SIDs — some questions will use text menus:")
        for item in missing:
            print(f"  - {item}")
        print("  See mhc-docs/twilio_content_templates.md for setup steps.")

_log_whatsapp_template_status()

MAIN_MENU_OPTIONS = {
    "english": ["Method Match", "Ask Question", "Myths & Facts", "Report Side Effects", "Change Language"],
    "swahili": ["Njia Inayonifaa", "Uliza Swali", "Ukweli na Imani", "Ripoti Madhara", "Badilisha Lugha"],
    "french": ["Methode adaptee", "Poser Question", "Mythes et faits", "Signaler effets", "Changer de langue"],
    "portuguese": ["Metodo ideal", "Fazer Pergunta", "Mitos e fatos", "Relatar efeitos", "Mudar idioma"],
}

LANGUAGE_OPTIONS = ["English", "Kiswahili", "Francais", "Portugues"]
HEALTH_CONDITION_OPTIONS = ["High blood pressure", "Diabetes", "Heart disease", "Liver problem", "Cancer", "Migraines", "None"]
METHOD_AVOID_OPTIONS = ["Pills", "Injectables", "IUD", "Implants", "None"]
CHILDREN_COUNT_OPTIONS = ["0", "1", "2", "3 or more"]
YES_NO_OPTIONS = {
    "english": ["Yes", "No"],
    "swahili": ["Ndio", "Hapana"],
    "french": ["Oui", "Non"],
    "portuguese": ["Sim", "Não"],
}
PARTNER_SUPPORT_OPTIONS = {
    "english": ["Yes", "No", "No partner"],
    "swahili": ["Ndio", "Hapana", "Sina mpenzi"],
    "french": ["Oui", "Non", "Pas de partenaire"],
    "portuguese": ["Sim", "Não", "Sem parceiro"],
}

def get_user_state(phone):
    doc = db.collection('contraceptive_users').document(phone).get()
    if doc.exists:
        return doc.to_dict()
    return None

def send_whatsapp_buttons(from_number, to_number, body_text, buttons):
    send_whatsapp_options(from_number, to_number, body_text, buttons)

def send_whatsapp_list_picker(from_number, to_number, body_text, options, button_text="Choose"):
    send_whatsapp_options(from_number, to_number, body_text, options, button_text=button_text)

def dispatch_whatsapp_method_match(user_phone, to_number, lang, user_snapshot):
    """Queue Method Match generation (Redis worker) with inline thread fallback."""
    payload = serializable_user_snapshot(user_snapshot)
    payload["phone"] = user_phone
    payload["language"] = lang
    payload["stage"] = "REGISTERED"
    payload["method_match_pending"] = True

    db.collection("contraceptive_users").document(user_phone).update({
        "method_match_status": "queued",
    })

    try:
        job = get_triage_queue().enqueue_call(
            func=process_whatsapp_method_match_job,
            args=(user_phone, to_number, lang, payload),
            timeout=TRIAGE_JOB_TIMEOUT_SECONDS,
            result_ttl=TRIAGE_JOB_RESULT_TTL_SECONDS,
            failure_ttl=TRIAGE_JOB_FAILURE_TTL_SECONDS,
        )
        print(f"[{user_phone}] Queued method match job {job.id}")
    except Exception as exc:
        print(f"[{user_phone}] Redis queue unavailable ({exc}); running inline worker thread")
        threading.Thread(
            target=process_whatsapp_method_match_job,
            args=(user_phone, to_number, lang, payload),
            daemon=True,
        ).start()

def extract_whatsapp_reply(form):
    return (
        form.get('ButtonPayload')
        or form.get('ListId')
        or form.get('ButtonText')
        or form.get('ListTitle')
        or form.get('Body')
        or ''
    ).strip()

def option_selected(message, option_number, *keywords):
    msg = str(message or '').lower().strip()
    if msg == str(option_number):
        return True
    return any(keyword in msg for keyword in keywords)

def question_body(text):
    return str(text).split("\n", 1)[0]

def send_main_menu(from_number, to_number, lang, greeting=None):
    s = STRINGS.get(lang, STRINGS["english"])
    menu_text = s["menu"]
    if greeting:
        menu_text = f"{greeting}{menu_text}"
    menu_options = MAIN_MENU_OPTIONS.get(lang, MAIN_MENU_OPTIONS["english"])
    send_whatsapp_list_picker(from_number, to_number, menu_text, menu_options, "Menu")

def send_language_menu(from_number, to_number):
    send_whatsapp_list_picker(
        from_number,
        to_number,
        "Welcome to ChaguoAI. Please select your preferred language.",
        LANGUAGE_OPTIONS,
        "Language"
    )

# ======================== WEBHOOKS ======================== 
@app.route("/webhook", methods=['POST'])
@app.route("/whatsapp", methods=['POST'])
def webhook():
    incoming_msg = extract_whatsapp_reply(request.values)
    user_phone = request.values.get('From', '')
    to_number = request.values.get('To', '')
    
    thread = threading.Thread(
        target=process_webhook_background,
        args=(incoming_msg, user_phone, to_number)
    )
    thread.start()
    return str(MessagingResponse())

# ======================== TRANSLATIONS ========================
LANGUAGES = {
    "1": "english", "2": "swahili", "3": "french", "4": "portuguese"
}
LANGUAGE_ALIASES = {
    "english": "english",
    "kiswahili": "swahili",
    "swahili": "swahili",
    "francais": "french",
    "français": "french",
    "french": "french",
    "portugues": "portuguese",
    "português": "portuguese",
    "portuguese": "portuguese",
}

STRINGS = {
    "english": {
        "menu": "Welcome to ChaguoAI — your contraception decision support assistant.\n\nHow can I help today?",
        "ask_name": "Great! Let's start with your name.",
        "menu_btns": MAIN_MENU_OPTIONS["english"]
    },
    "swahili": {
        "menu": "Habari! Karibu ChaguoAI — msaidizi wako wa upangaji uzazi.\n\nNinawezaje kukusaidia leo?",
        "ask_name": "Safi sana! Hebu nianze kwa kufahamu jina lako kwanza.",
        "menu_btns": MAIN_MENU_OPTIONS["swahili"]
    },
    "french": {
        "menu": "Bienvenue sur ChaguoAI — votre assistant d'aide a la decision contraceptive.\n\nComment puis-je vous aider aujourd'hui ?",
        "ask_name": "Génial ! Commençons par votre nom.",
        "menu_btns": MAIN_MENU_OPTIONS["french"]
    },
    "portuguese": {
        "menu": "Bem-vindo ao ChaguoAI — seu assistente de apoio a decisao contraceptiva.\n\nComo posso ajudar hoje?",
        "ask_name": "Ótimo! Vamos começar com o seu nome.",
        "menu_btns": MAIN_MENU_OPTIONS["portuguese"]
    }
}
SURVEY_STRINGS = {
    "english": {
        "q1": "Q1/13: How old are you? (Reply with a number, e.g., 25).",
        "q2": "Q2/13: Your menstrual period or pregnancy status?",
        "q2_options": ["Within 4 weeks", "Not sure", "Currently pregnant"],
        "q3": "Q3/13: Do you have a baby under 6 months?",
        "q3_options": ["Yes", "No"],
        "q3a": "Q3a: Are you exclusively breastfeeding?",
        "q4": "Q4/13: How many living children do you have?",
        "q5": "Q5/13: Do you want more children?",
        "q5_options": ["Yes, in 2 years", "Yes, later", "No"],
        "q6": "Q6/13: Do you have any health conditions? (Select number(s) e.g. 1,2 or 7):\n1. High blood pressure\n2. Diabetes\n3. Heart disease\n4. Liver problem\n5. Cancer\n6. Migraines\n7. None",
        "q7": "Q7/13: Are you living with HIV?",
        "q7_options": ["Yes", "No", "Prefer not to say"],
        "q8": "Q8/13: Do you smoke?",
        "q9": "Q9/13: Have you used contraception before?",
        "q9a": "Q9a: Did you stop?",
        "q9a_options": ["Still using", "Stopped - side effects", "Stopped - other", "Switched"],
        "q10": "Q10/13: Does your partner support contraception?",
        "q11": "Q11/13: How difficult is it to visit a health facility?",
        "q11_options": ["Easy", "Sometimes hard", "Very hard"],
        "q12": "Q12/13: Do you also care about STI protection?",
        "q13": "Q13/13: Are there methods you prefer NOT to use?\n1. Pills\n2. Injectables\n3. IUD\n4. Implants\n5. None",
        "finished": "Thank you! I have collected your profile. Preparing your Method Match... Please wait."
    },
    "swahili": {
        "q1": "Q1/13: Una umri wa miaka mingapi? Jibu kwa nambari tu (Mfn. 25).",
        "q2": "Q2/13: Kipindi chako cha hedhi au hali ya ujauzito?",
        "q2_options": ["Ndani ya wiki 4", "Sina uhakika", "Nina mimba kwa sasa"],
        "q3": "Q3/13: Je, una mtoto chini ya miezi 6?",
        "q3_options": ["Ndio", "Hapana"],
        "q3a": "Q3a: Je, unanyonyesha maziwa ya mama pekee?",
        "q4": "Q4/13: Una watoto wangapi walio hai? Jibu kwa nambari (Mfn. 0 au 2).",
        "q5": "Q5/13: Je, unataka watoto zaidi?",
        "q5_options": ["Ndio, miaka 2", "Ndio, baadaye", "Hapana"],
        "q6": "Q6/13: Je, una hali yoyote ya kiafya? (Chagua nambari Mfn. 1,2 au 7):\n1. High blood pressure\n2. Diabetes\n3. Heart disease\n4. Liver problem\n5. Cancer\n6. Migraines\n7. None of the above",
        "q7": "Q7/13: Je, unaishi na virusi vya ukimwi (HIV)?",
        "q7_options": ["Ndio", "Hapana", "Sipendelei kusema"],
        "q8": "Q8/13: Je, unavuta sigara?",
        "q9": "Q9/13: Je, umewahi kutumia njia za kupanga uzazi hapo awali?",
        "q9a": "Q9a: Je, uliacha?",
        "q9a_options": ["Bado natumia", "Niliacha - madhara", "Niliacha - sababu zingine", "Nilibadilisha"],
        "q10": "Q10/13: Je, mpenzi wako anaunga mkono kupanga uzazi?",
        "q11": "Q11/13: Ni vigumu kiasi gani kutembelea kituo cha afya?",
        "q11_options": ["Rahisi", "Wakati mwingine ngumu", "Ngumu sana"],
        "q12": "Q12/13: Je, wajali pia kuhusu kujikinga na magonjwa ya zinaa (STI)?",
        "q13": "Q13/13: Kuna njia ambazo hupendi kutumia?\n1. Pills\n2. Injectables\n3. IUD\n4. Implants\n5. Hakuna / None",
        "finished": "Ahsante sana! Nimekusanya majibu yako yote. Naandaa mapendekezo yako ya Method Match... Tafadhali subiri kidogo."
    },
    "french": {
        "q1": "Q1/13: Quel âge avez-vous ? (Répondez avec un nombre, ex. 25).",
        "q2": "Q2/13: Votre période menstruelle ou état de grossesse ?",
        "q2_options": ["Moins de 4 semaines", "Pas sûr", "Actuellement enceinte"],
        "q3": "Q3/13: Avez-vous un bébé de moins de 6 mois ?",
        "q3_options": ["Oui", "Non"],
        "q3a": "Q3a: Allaiterez-vous exclusivement ?",
        "q4": "Q4/13: Combien d'enfants vivants avez-vous ?",
        "q5": "Q5/13: Voulez-vous plus d'enfants ?",
        "q5_options": ["Oui, dans 2 ans", "Oui, plus tard", "Non"],
        "q6": "Q6/13: Avez-vous des problèmes de santé ? (Sélectionnez le(s) numéro(s) ex. 1,2 ou 7):\n1. Hypertension\n2. Diabète\n3. Maladie cardiaque\n4. Problème de foie\n5. Cancer\n6. Migraines\n7. Aucun",
        "q7": "Q7/13: Vivez-vous avec le VIH ?",
        "q7_options": ["Oui", "Non", "Préfère ne pas dire"],
        "q8": "Q8/13: Fumez-vous ?",
        "q9": "Q9/13: Avez-vous déjà utilisé une contraception ?",
        "q9a": "Q9a: Avez-vous arrêté ?",
        "q9a_options": ["Toujours en cours", "Arrêté - effets secondaires", "Arrêté - autre", "Changé"],
        "q10": "Q10/13: Votre partenaire soutient-il la contraception ?",
        "q11": "Q11/13: Est-il difficile de visiter un centre de santé ?",
        "q11_options": ["Facile", "Parfois difficile", "Très difficile"],
        "q12": "Q12/13: Vous souciez-vous aussi de la protection contre les IST ?",
        "q13": "Q13/13: Y a-t-il des méthodes que vous préférez NE PAS utiliser ?\n1. Pilules\n2. Injectables\n3. DIU\n4. Implants\n5. Aucun",
        "finished": "Merci ! J'ai recueilli votre profil. Je prépare vos recommandations... Veuillez patienter."
    },
    "portuguese": {
        "q1": "Q1/13: Qual é a sua idade? (Responda com um número, ex. 25).",
        "q2": "Q2/13: Seu período menstrual ou estado de gravidez?",
        "q2_options": ["Menos de 4 semanas", "Não tenho certeza", "Atualmente grávida"],
        "q3": "Q3/13: Você tem um bebê com menos de 6 meses?",
        "q3_options": ["Sim", "Não"],
        "q3a": "Q3a: Você está amamentando exclusivamente?",
        "q4": "Q4/13: Quantos filhos vivos você tem?",
        "q5": "Q5/13: Você quer mais filhos?",
        "q5_options": ["Sim, em 2 anos", "Sim, mais tarde", "Não"],
        "q6": "Q6/13: Você tem alguma condição de saúde? (Selecione o(s) número(s) ex. 1,2 ou 7):\n1. Pressão alta\n2. Diabetes\n3. Doença cardíaca\n4. Problema de fígado\n5. Câncer\n6. Enxaquecas\n7. Nenhum",
        "q7": "Q7/13: Você vive com HIV?",
        "q7_options": ["Sim", "Não", "Prefiro não dizer"],
        "q8": "Q8/13: Você fuma?",
        "q9": "Q9/13: Você já usou contracepção antes?",
        "q9a": "Q9a: Você parou?",
        "q9a_options": ["Ainda usando", "Parou - efeitos colaterais", "Parou - outro", "Trocou"],
        "q10": "Q10/13: Seu parceiro apoia a contracepção?",
        "q11": "Q11/13: Quão difícil é visitar uma unidade de saúde?",
        "q11_options": ["Fácil", "Às vezes difícil", "Muito difícil"],
        "q12": "Q12/13: Você também se preocupa com a proteção contra IST?",
        "q13": "Q13/13: Existem métodos que você prefere NÃO usar?\n1. Pílulas\n2. Injetáveis\n3. DIU\n4. Implantes\n5. Nenhum",
        "finished": "Obrigado! Coletei seu perfil. Preparando suas recomendações... Aguarde."
    }
}

def process_webhook_background(incoming_msg, user_phone, to_number):
    try:
        incoming_msg = str(incoming_msg or '').strip()
        user = get_user_state(user_phone)
        if not user:
            # First interaction - Ask for Language
            # Check if this person is being registered by a provider (session or web entry)
            provider_id = session.get('provider_id') # Fallback if being registered via webhook
            db.collection('contraceptive_users').document(user_phone).set({
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

        if stage == "AWAITING_LANGUAGE":
            msg = incoming_msg.strip()
            lang_code = LANGUAGES.get(msg) or LANGUAGE_ALIASES.get(msg.lower())
            if lang_code:
                db.collection('contraceptive_users').document(user_phone).update({
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
                db.collection('contraceptive_users').document(user_phone).update({"stage": "AWAITING_NAME"})
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
                db.collection('contraceptive_users').document(user_phone).update({"stage": "AWAITING_MYTH_QUESTION"})
                prompt = {
                    "english": "Tell me the contraception myth or concern you have heard, and I will answer using clinical guidance.",
                    "swahili": "Ni imani au wasiwasi gani kuhusu uzazi umesikia? Nitakujibu kwa kutumia mwongozo wa kitabibu.",
                    "french": "Dites-moi le mythe ou la preoccupation sur la contraception, et je repondrai avec des conseils cliniques.",
                    "portuguese": "Conte-me o mito ou preocupacao sobre contracepcao, e responderei com orientacao clinica."
                }
                send_whatsapp_message(to_number, user_phone, prompt.get(lang, prompt["english"]))
                return
            if option_selected(msg, 4, 'side', 'effect', 'madhara', 'effet', 'efeito', 'report', 'ripoti'):
                db.collection('contraceptive_users').document(user_phone).update({"stage": "AWAITING_SIDE_EFFECT_REPORT"})
                prompt = {
                    "english": "Please describe the side effect, when it started, and the method you are using. If symptoms are severe, seek urgent care now.",
                    "swahili": "Tafadhali eleza madhara, yalianza lini, na njia unayotumia. Kama dalili ni kali, tafuta huduma ya dharura sasa.",
                    "french": "Decrivez l'effet secondaire, sa date de debut et la methode utilisee. Si les symptomes sont graves, consultez en urgence.",
                    "portuguese": "Descreva o efeito colateral, quando comecou e o metodo usado. Se os sintomas forem graves, procure atendimento urgente."
                }
                send_whatsapp_message(to_number, user_phone, prompt.get(lang, prompt["english"]))
                return
            if option_selected(msg, 5, 'language', 'lugha', 'langue', 'idioma', 'change', 'badilisha', 'changer', 'mudar'):
                db.collection('contraceptive_users').document(user_phone).update({"stage": "AWAITING_LANGUAGE"})
                send_language_menu(to_number, user_phone)
                return
            if any(k in msg for k in ['1', 'njia', 'match', 'uzazi', 'panga', 'birth', 'plan', 'tayari', 'kuanza', 'recommandations', 'recomendações']):
                db.collection('contraceptive_users').document(user_phone).update({"stage": "AWAITING_NAME"})
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
            db.collection('contraceptive_users').document(user_phone).collection('side_effects').add({
                'report': report_text,
                'language': lang,
                'timestamp': firestore.SERVER_TIMESTAMP,
                'source': 'whatsapp'
            })
            db.collection('contraceptive_users').document(user_phone).update({"stage": "MAIN_MENU"})
            response = {
                "english": "Thank you. I have recorded this for review. If you have heavy bleeding, severe lower abdominal pain, chest pain, shortness of breath, fainting, severe headache, or signs of pregnancy, please seek urgent care now.",
                "swahili": "Ahsante. Nimehifadhi taarifa hii kwa kufuatiliwa. Kama una damu nyingi, maumivu makali ya tumbo la chini, maumivu ya kifua, shida ya kupumua, kuzimia, kichwa kikali, au dalili za ujauzito, tafuta huduma ya dharura sasa.",
                "french": "Merci. J'ai enregistre ces informations pour suivi. En cas de saignement abondant, douleur abdominale severe, douleur thoracique, essoufflement, malaise, cefalee severe ou signes de grossesse, consultez en urgence.",
                "portuguese": "Obrigado. Registrei isso para acompanhamento. Se houver sangramento intenso, dor abdominal forte, dor no peito, falta de ar, desmaio, dor de cabeca intensa ou sinais de gravidez, procure atendimento urgente."
            }
            send_whatsapp_message(to_number, user_phone, response.get(lang, response["english"]))
            return

        if stage == "AWAITING_MYTH_QUESTION":
            db.collection('contraceptive_users').document(user_phone).update({"stage": "MAIN_MENU"})
            incoming_msg = f"Please answer this contraception myth or concern clearly and clinically: {incoming_msg.strip()}"
            user["stage"] = "MAIN_MENU"
        
        if stage == "AWAITING_NAME":
            db.collection('contraceptive_users').document(user_phone).update({
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
                db.collection('contraceptive_users').document(user_phone).update({
                    "stage": "AWAITING_COUNTRY_CONFIRM",
                    "pending_country": normalized.canonical,
                    "pending_country_raw": normalized.raw,
                    "pending_country_match_confidence": normalized.confidence,
                })
                send_whatsapp_message(
                    to_number, user_phone, country_confirm_prompt(lang, normalized.canonical)
                )
                return
            db.collection('contraceptive_users').document(user_phone).update({
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
                db.collection('contraceptive_users').document(user_phone).update({
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
            db.collection('contraceptive_users').document(user_phone).update({
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
            db.collection('contraceptive_users').document(user_phone).update({
                **build_admin_area_firestore_fields(incoming_msg, country, source="whatsapp"),
                "location_captured_at": firestore.SERVER_TIMESTAMP,
                "stage": "AWAITING_Q1_AGE",
            })
            send_whatsapp_message(to_number, user_phone, q["q1"])
            return
            
        if stage == "AWAITING_Q1_AGE":
            match = re.search(r'\d+', incoming_msg)
            if match:
                db.collection('contraceptive_users').document(user_phone).update({"age": int(match.group()), "stage": "AWAITING_Q2_PERIOD"})
                send_whatsapp_buttons(to_number, user_phone, q["q2"], q["q2_options"])
            else:
                error_msg = {"english": "Please reply with a valid number.", "swahili": "Tafadhali jibu kwa nambari halali.", "french": "Veuillez répondre avec un nombre valide.", "portuguese": "Por favor, responda com um número válido."}
                send_whatsapp_message(to_number, user_phone, error_msg.get(lang, error_msg["english"]))
            return

        if stage == "AWAITING_Q2_PERIOD":
            db.collection('contraceptive_users').document(user_phone).update({"last_period": incoming_msg.strip(), "stage": "AWAITING_Q3_BABY"})
            send_whatsapp_buttons(to_number, user_phone, q["q3"], YES_NO_OPTIONS.get(lang, YES_NO_OPTIONS["english"]))
            return

        if stage == "AWAITING_Q3_BABY":
            is_yes = any(word in incoming_msg.lower() for word in ['ndio', 'yes', 'oui', 'sim', '1'])
            db.collection('contraceptive_users').document(user_phone).update({"baby_under_6m": incoming_msg.strip(), "stage": "AWAITING_Q3A_BREASTFEEDING" if is_yes else "AWAITING_Q4_CHILDREN"})
            if is_yes:
                send_whatsapp_buttons(to_number, user_phone, q["q3a"], YES_NO_OPTIONS.get(lang, YES_NO_OPTIONS["english"]))
            else:
                send_whatsapp_buttons(to_number, user_phone, q["q4"], CHILDREN_COUNT_OPTIONS)
            return

        if stage == "AWAITING_Q3A_BREASTFEEDING":
            db.collection('contraceptive_users').document(user_phone).update({"breastfeeding_only": incoming_msg.strip(), "stage": "AWAITING_Q4_CHILDREN"})
            send_whatsapp_buttons(to_number, user_phone, q["q4"], CHILDREN_COUNT_OPTIONS)
            return
 
        if stage == "AWAITING_Q4_CHILDREN":
            db.collection('contraceptive_users').document(user_phone).update({"living_children": incoming_msg.strip(), "stage": "AWAITING_Q5_MORE_CHILDREN"})
            send_whatsapp_buttons(to_number, user_phone, q["q5"], q["q5_options"])
            return
 
        if stage == "AWAITING_Q5_MORE_CHILDREN":
            db.collection('contraceptive_users').document(user_phone).update({"more_children": incoming_msg.strip(), "stage": "AWAITING_Q6_HEALTH"})
            send_whatsapp_options(to_number, user_phone, question_body(q["q6"]), HEALTH_CONDITION_OPTIONS, multi_select=True, button_text="Conditions", language=lang)
            return
 
        if stage == "AWAITING_Q6_HEALTH":
            db.collection('contraceptive_users').document(user_phone).update({"health_conditions": incoming_msg.strip(), "stage": "AWAITING_Q7_HIV"})
            send_whatsapp_buttons(to_number, user_phone, q["q7"], q["q7_options"])
            return

        if stage == "AWAITING_Q7_HIV":
            db.collection('contraceptive_users').document(user_phone).update({"hiv_status": incoming_msg.strip(), "stage": "AWAITING_Q8_SMOKE"})
            send_whatsapp_buttons(to_number, user_phone, q["q8"], YES_NO_OPTIONS.get(lang, YES_NO_OPTIONS["english"]))
            return

        if stage == "AWAITING_Q8_SMOKE":
            db.collection('contraceptive_users').document(user_phone).update({"smoke": incoming_msg.strip(), "stage": "AWAITING_Q9_PREVIOUS_USE"})
            send_whatsapp_buttons(to_number, user_phone, q["q9"], YES_NO_OPTIONS.get(lang, YES_NO_OPTIONS["english"]))
            return

        if stage == "AWAITING_Q9_PREVIOUS_USE":
            is_yes = any(word in incoming_msg.lower() for word in ['ndio', 'yes', 'oui', 'sim', '1'])
            db.collection('contraceptive_users').document(user_phone).update({"previous_use": incoming_msg.strip(), "stage": "AWAITING_Q9A_STOP" if is_yes else "AWAITING_Q10_PARTNER"})
            if is_yes:
                send_whatsapp_buttons(to_number, user_phone, q["q9a"], q["q9a_options"])
            else:
                send_whatsapp_buttons(to_number, user_phone, q["q10"], PARTNER_SUPPORT_OPTIONS.get(lang, PARTNER_SUPPORT_OPTIONS["english"]))
            return

        if stage == "AWAITING_Q9A_STOP":
            db.collection('contraceptive_users').document(user_phone).update({"stop_reason": incoming_msg.strip(), "stage": "AWAITING_Q10_PARTNER"})
            send_whatsapp_buttons(to_number, user_phone, q["q10"], PARTNER_SUPPORT_OPTIONS.get(lang, PARTNER_SUPPORT_OPTIONS["english"]))
            return

        if stage == "AWAITING_Q10_PARTNER":
            db.collection('contraceptive_users').document(user_phone).update({"partner_support": incoming_msg.strip(), "stage": "AWAITING_Q11_FACILITY"})
            send_whatsapp_buttons(to_number, user_phone, q["q11"], q["q11_options"])
            return

        if stage == "AWAITING_Q11_FACILITY":
            db.collection('contraceptive_users').document(user_phone).update({"facility_access": incoming_msg.strip(), "stage": "AWAITING_Q12_STI"})
            send_whatsapp_buttons(to_number, user_phone, q["q12"], YES_NO_OPTIONS.get(lang, YES_NO_OPTIONS["english"]))
            return

        if stage == "AWAITING_Q12_STI":
            db.collection('contraceptive_users').document(user_phone).update({"sti_concern": incoming_msg.strip(), "stage": "AWAITING_Q13_PREFERENCES"})
            send_whatsapp_options(to_number, user_phone, question_body(q["q13"]), METHOD_AVOID_OPTIONS, multi_select=True, button_text="Methods", language=lang)
            return

        if stage == "AWAITING_Q13_PREFERENCES":
            prefer = incoming_msg.strip()
            user["prefer_not_to_use"] = prefer
            user["stage"] = "REGISTERED"
            user["method_match_pending"] = True

            db.collection('contraceptive_users').document(user_phone).update({
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
        if incoming_msg.lower().strip() in ["menu", "nyumbani", "mwanzo", "0", "hey", "hujambo", "habari", "hi", "hello"]:
            db.collection('contraceptive_users').document(user_phone).update({"stage": "MAIN_MENU"})
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


@app.route("/ussd", methods=['POST'])
def ussd():
    session_id = request.values.get('sessionId')
    service_code = request.values.get('serviceCode')
    phone_number = request.values.get('phoneNumber')
    text = request.values.get('text')
    return handle_ussd_request(session_id, service_code, phone_number, text, db=db)


# ======================== ADMIN DASHBOARD ========================
@app.route("/admin")
def admin_login_page():
    return render_template('admin_login.html')

@app.route("/admin/portal")
def admin_portal():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login_page'))
    return render_template('admin_portal.html')
# Access Codes for Admin — see app_config.ADMIN_CODE

@app.route("/api/admin/login", methods=['POST'])
def api_admin_login():
    data = request.json
    code = data.get('access_code')
    if code == ADMIN_CODE:
        session['admin_logged_in'] = True
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Invalid Access Code"}), 401

@app.route("/admin/logout")
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login_page'))

@app.route("/api/geography/countries", methods=["GET"])
def api_geography_countries():
    """Canonical country list for provider portal dropdown (analytics only)."""
    return jsonify({"countries": countries_for_api()})


def _require_admin():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    return None


@app.route("/api/admin/stats", methods=["GET"])
def admin_stats():
    denied = _require_admin()
    if denied:
        return denied
    try:
        cohort = request.args.get("cohort", "all")
        return jsonify(build_admin_stats(db, cohort=cohort))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/export/clients.csv", methods=["GET"])
def admin_export_clients():
    denied = _require_admin()
    if denied:
        return denied
    try:
        users = []
        for doc in db.collection("contraceptive_users").stream():
            data = doc.to_dict() or {}
            data["phone"] = doc.id
            users.append(data)
        csv_body = export_clients_csv(users)
        return Response(
            csv_body,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=chaguoai_clients.csv"},
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/events", methods=["GET"])
def admin_events():
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    cohort = request.args.get("cohort", "all")

    def event_stream():
        # Keep the stream lightweight: emit compact stats every 15 seconds.
        while True:
            try:
                payload = build_admin_stats(db, cohort=cohort)
                yield f"event: stats\ndata: {json.dumps(payload, default=str)}\n\n"
            except GeneratorExit:
                break
            except Exception as exc:
                yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"
            time.sleep(15)

    return Response(event_stream(), mimetype="text/event-stream")

@app.route("/api/admin/pending_providers", methods=['GET'])
def admin_pending_providers():
    denied = _require_admin()
    if denied:
        return denied
    providers = []
    for doc in db.collection('providers').where('status', '==', 'pending').stream():
        p = doc.to_dict()
        p['id'] = doc.id
        providers.append(p)
    return jsonify({"providers": providers})

@app.route("/api/admin/approve_provider/<provider_id>", methods=['POST'])
def admin_approve_provider(provider_id):
    denied = _require_admin()
    if denied:
        return denied
    db.collection('providers').document(provider_id).update({"status": "approved"})
    return jsonify({"success": True})


# ======================== PROVIDER DASHBOARD ========================
@app.route("/provider")
def provider_dashboard():
    return render_template('provider_portal.html')

@app.route("/provider/login")
def provider_login():
    return render_template('provider_login.html')

@app.route("/provider/register")
def provider_register():
    return render_template('provider_register.html')

@app.route("/api/provider/register", methods=['POST'])
def api_provider_register():
    data = request.json
    data['status'] = 'pending'
    db.collection('providers').add(data)
    return jsonify({"success": True})

@app.route("/api/provider/login", methods=['POST'])
def api_provider_login():
    data = request.json
    email = data.get('email')
    docs = list(db.collection('providers').where(filter=firestore.FieldFilter('email', '==', email)).where(filter=firestore.FieldFilter('status', '==', 'approved')).stream())
    if docs:
        session['provider_id'] = docs[0].id
        return jsonify({"success": True, "role": docs[0].to_dict().get('role')})
    return jsonify({"success": False, "error": "Invalid credentials or pending approval"}), 401

@app.route("/api/provider/logout", methods=['POST'])
def api_provider_logout():
    session.clear()
    return jsonify({"success": True})

@app.route("/api/provider/me", methods=['GET'])
def api_provider_me():
    pid = session.get('provider_id')
    if not pid: return jsonify({"error": "Unauthorized"}), 401
    doc = db.collection('providers').document(pid).get()
    if not doc.exists: return jsonify({"error": "Not Found"}), 404
    return jsonify(doc.to_dict())

def serialize_firestore_value(value):
    """Convert Firestore types to JSON-safe values for dashboard APIs."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if hasattr(value, "timestamp"):
        try:
            return datetime.datetime.utcfromtimestamp(value.timestamp()).isoformat() + "Z"
        except Exception:
            pass
    if isinstance(value, dict):
        return {k: serialize_firestore_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [serialize_firestore_value(v) for v in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)

def extract_method_snippet(text, limit=120):
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

def _provider_client_summary(doc) -> dict:
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


@app.route("/api/provider/roster", methods=['GET'])
def api_provider_roster():
    pid = session.get('provider_id')
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401

    users = []
    for doc in db.collection('contraceptive_users').where(
        filter=firestore.FieldFilter('assigned_provider_id', '==', pid)
    ).stream():
        users.append(_provider_client_summary(doc))
    return jsonify({"clients": users})


@app.route("/api/provider/clients/<path:phone>", methods=["GET"])
def api_provider_client_detail(phone):
    pid = session.get("provider_id")
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401

    phone = format_to_e164(phone)
    doc = db.collection("contraceptive_users").document(phone).get()
    if not doc.exists:
        return jsonify({"error": "Client not found"}), 404

    data = doc.to_dict() or {}
    if data.get("assigned_provider_id") != pid:
        return jsonify({"error": "Forbidden"}), 403

    client = _provider_client_summary(doc)
    side_effects = []
    try:
        se_query = doc.reference.collection("side_effects").order_by(
            "timestamp", direction=firestore.Query.DESCENDING
        ).limit(10)
    except Exception:
        se_query = doc.reference.collection("side_effects").limit(10)
    for se in se_query.stream():
        item = serialize_firestore_value(se.to_dict())
        item["id"] = se.id
        item["at"] = serialize_firestore_value(item.get("timestamp"))
        side_effects.append(item)
    side_effects.sort(key=lambda x: x.get("at") or "", reverse=True)
    recommendation_text = client.get("matched_method") or client.get("latest_recommendation") or ""
    mec_summary = client.get("latest_mec_text") or client.get("latest_mec_result") or ""
    citations = client.get("recommendation_citations") or []
    stored_cards = client.get("method_cards") or []
    if stored_cards:
        method_cards = stored_cards
    else:
        method_cards, recommendation_text = resolve_method_cards(
            recommendation_text, mec_summary, citations
        )

    return jsonify({
        "client": client,
        "recommendation": recommendation_text,
        "method_cards": method_cards,
        "recommendation_citations": client.get("recommendation_citations") or [],
        "mec_summary": client.get("latest_mec_text") or client.get("latest_mec_result") or "",
        "side_effects": side_effects,
    })


@app.route("/api/provider/side_effects", methods=["GET"])
def api_provider_side_effects():
    pid = session.get("provider_id")
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401
    items = collect_safety_items(db, provider_id=pid, limit=50)
    reports = [i for i in items if i.get("type") == "side_effect"]
    return jsonify({"reports": reports})


@app.route("/api/provider/methods", methods=["GET"])
def api_provider_methods():
    pid = session.get("provider_id")
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"methods": all_methods()})


@app.route("/api/provider/clients/<path:phone>/select_method", methods=["POST"])
def api_provider_select_method(phone):
    pid = session.get("provider_id")
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json or {}
    method_name = data.get("method") or data.get("method_name")
    if not method_name:
        return jsonify({"error": "Method is required"}), 400
    try:
        phone = format_to_e164(phone)
        result = select_method(
            db=db,
            phone=phone,
            provider_id=pid,
            method_name=method_name,
            counseling=data.get("counseling") or {},
            referral=data.get("referral") or None,
        )
        return jsonify(serialize_firestore_value(result))
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/provider/clients/<path:phone>/referral", methods=["POST"])
def api_provider_create_referral(phone):
    pid = session.get("provider_id")
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json or {}
    method_name = data.get("method") or data.get("method_name") or "Selected method"
    try:
        phone = format_to_e164(phone)
        referral = create_referral(
            db=db,
            phone=phone,
            provider_id=pid,
            method_name=method_name,
            referral=data,
        )
        return jsonify({"success": True, "referral": serialize_firestore_value(referral)})
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/provider/clients/<path:phone>/send_selection_message", methods=["POST"])
def api_provider_send_selection_message(phone):
    pid = session.get("provider_id")
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json or {}
    phone = format_to_e164(phone)
    doc_ref = db.collection("contraceptive_users").document(phone)
    doc = doc_ref.get()
    if not doc.exists:
        return jsonify({"error": "Client not found"}), 404
    client = doc.to_dict() or {}
    if client.get("assigned_provider_id") != pid:
        return jsonify({"error": "Forbidden"}), 403

    method_name = data.get("method") or client.get("selected_method")
    if not method_name:
        return jsonify({"error": "Select a method before sending a message"}), 400

    referral = data.get("referral")
    if not referral and client.get("latest_referral_facility"):
        referral = {"facility_name": client.get("latest_referral_facility")}

    message = build_selection_client_message(
        client=client,
        method_name=method_name,
        referral=referral,
        next_followup=serialize_firestore_value(client.get("next_followup_at")),
    )
    delivery = send_whatsapp_with_sms_fallback(TWILIO_NUMBER, phone, message)
    doc_ref.set({
        "selection_message_status": delivery.get("status"),
        "selection_message_channel": delivery.get("channel"),
        "selection_message_error": delivery.get("error") or delivery.get("whatsapp_error") or "",
        "selection_message_sent_at": firestore.SERVER_TIMESTAMP,
        "latest_selection_message": message,
    }, merge=True)
    return jsonify({"success": delivery.get("status") == "sent", "delivery": delivery, "message": message})


@app.route("/api/provider/clients/<path:phone>/compose_followup", methods=["POST"])
def api_provider_compose_followup(phone):
    """Send one composed follow-up message to a client (WhatsApp/SMS)."""
    pid = session.get("provider_id")
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json or {}
    phone = format_to_e164(phone)
    doc_ref = db.collection("contraceptive_users").document(phone)
    doc = doc_ref.get()
    if not doc.exists:
        return jsonify({"error": "Client not found"}), 404
    client = doc.to_dict() or {}
    if client.get("assigned_provider_id") != pid:
        return jsonify({"error": "Forbidden"}), 403

    custom = (data.get("message") or "").strip()
    method_name = data.get("method") or client.get("selected_method") or "your method"
    reason = (data.get("reason") or "routine check-in").strip()
    if custom:
        message = custom
    else:
        message = compose_followup_reminder(
            client_name=client.get("name") or "",
            method_name=method_name,
            reason=reason,
        )

    delivery = send_whatsapp_with_sms_fallback(TWILIO_NUMBER, phone, message)
    doc_ref.set({
        "latest_followup_message": message,
        "latest_followup_sent_at": firestore.SERVER_TIMESTAMP,
        "latest_followup_sent_by": pid,
    }, merge=True)
    return jsonify({
        "success": delivery.get("status") == "sent",
        "delivery": delivery,
        "message": message,
    })


@app.route("/api/provider/clients/<path:phone>/followups", methods=["GET"])
def api_provider_client_followups(phone):
    pid = session.get("provider_id")
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401
    phone = format_to_e164(phone)
    doc = db.collection("contraceptive_users").document(phone).get()
    if not doc.exists:
        return jsonify({"error": "Client not found"}), 404
    if (doc.to_dict() or {}).get("assigned_provider_id") != pid:
        return jsonify({"error": "Forbidden"}), 403
    tasks = []
    for task in db.collection("followup_tasks").where(
        filter=firestore.FieldFilter("phone", "==", phone)
    ).stream():
        item = serialize_firestore_value(task.to_dict())
        item["id"] = task.id
        tasks.append(item)
    tasks.sort(key=lambda x: str(x.get("due_at") or ""))
    return jsonify({"followups": tasks})


@app.route("/api/provider/followups", methods=["GET"])
def api_provider_followups():
    pid = session.get("provider_id")
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401
    status = request.args.get("status")
    tasks = []
    query = db.collection("followup_tasks").where(
        filter=firestore.FieldFilter("provider_id", "==", pid)
    )
    for task in query.stream():
        item = serialize_firestore_value(task.to_dict())
        item["id"] = task.id
        if status and item.get("status") != status:
            continue
        tasks.append(item)
    tasks.sort(key=lambda x: str(x.get("due_at") or ""))
    return jsonify({"followups": tasks})


@app.route("/api/provider/followups/<task_id>/outcome", methods=["POST"])
def api_provider_followup_outcome(task_id):
    pid = session.get("provider_id")
    if not pid:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json or {}
    outcome = data.get("outcome")
    if not outcome:
        return jsonify({"error": "Outcome is required"}), 400
    try:
        result = record_followup_outcome(
            db=db,
            task_id=task_id,
            provider_id=pid,
            outcome=outcome,
            note=data.get("note", ""),
        )
        return jsonify(serialize_firestore_value(result))
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@app.route("/api/provider/mec_query", methods=['POST'])
def api_provider_mec_query():
    pid = session.get('provider_id')
    if not pid: return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    query = data.get('query')
    if not query: return jsonify({"error": "Query required"}), 400
    
    try:
        retriever = get_retriever()
        chunks = retriever.retrieve(query, top_k=5)
        context = retriever.format_context_for_llm(chunks)
        
        sys_prompt = build_system_prompt(
            mec_result_text="[Clinician query — apply WHO MEC categories to the methods discussed in the question.]",
            retrieved_context=context,
            user_profile_summary=f"Clinician portal query from provider {pid}.",
            channel="web",
            language="english",
        )
        full_prompt = (
            f"{sys_prompt}\n\n{build_web_clinical_instruction()}\n\n"
            f"Clinician Query: {query}"
        )
        
        response_text = generate_gemini_text(full_prompt, max_output_tokens=WEB_PROVIDER_MAX_OUTPUT_TOKENS)
        return jsonify({"success": True, "response": response_text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/provider/submit_triage", methods=['POST'])
def api_provider_submit_triage():
    pid = session.get('provider_id')
    if not pid: return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json or {}
    phone = data.get('phone')
    if not phone: return jsonify({"error": "Phone required"}), 400
    
    # Map raw data to Firestore document
    phone = format_to_e164(phone) # Standardize to E.164
    data['phone'] = phone
    data['assigned_provider_id'] = pid
    data['stage'] = 'REGISTERED'
    data['registered_at'] = firestore.SERVER_TIMESTAMP
    if data.get('country') or data.get('admin_area'):
        data['location_capture_purpose'] = 'analytics_only'
        data['location_source'] = 'provider'
        data['admin_area_type'] = data.get('admin_area_type') or admin_area_label(data.get('country'))
        if data.get('country') and not data.get('country_raw'):
            normalized = normalize_country(str(data['country']), allow_legacy_index=False)
            data['country'] = normalized.canonical
            data['country_raw'] = normalized.raw
            data['country_match_confidence'] = normalized.confidence
        if data.get('admin_area') and not data.get('admin_area_raw'):
            data['admin_area_raw'] = str(data['admin_area']).strip()
            data['admin_area'] = normalize_admin_area(data['admin_area'], data.get('country'))
    
    db.collection('contraceptive_users').document(phone).set(data)
    job_ref = db.collection('triage_jobs').document()
    job_ref.set({
        "status": "queued",
        "phone": phone,
        "assigned_provider_id": pid,
        "created_at": firestore.SERVER_TIMESTAMP,
    })
    db.collection('contraceptive_users').document(phone).set({
        "triage_status": "queued",
        "latest_triage_job_id": job_ref.id,
        "triage_queued_at": firestore.SERVER_TIMESTAMP,
    }, merge=True)

    triage_payload = {k: v for k, v in data.items() if k != 'registered_at'}
    try:
        rq_job = get_triage_queue().enqueue_call(
            func="triage_tasks.process_triage_job",
            args=(job_ref.id, triage_payload),
            job_id=f"triage_{job_ref.id}",
            timeout=TRIAGE_JOB_TIMEOUT_SECONDS,
            result_ttl=TRIAGE_JOB_RESULT_TTL_SECONDS,
            failure_ttl=TRIAGE_JOB_FAILURE_TTL_SECONDS,
        )
        job_ref.update({
            "rq_job_id": rq_job.id,
            "queued_at": firestore.SERVER_TIMESTAMP,
        })
    except Exception as e:
        error_message = str(e)
        print(f"Triage enqueue failed: {error_message}")
        job_ref.update({
            "status": "failed",
            "error": f"Could not queue triage job: {error_message}",
            "completed_at": firestore.SERVER_TIMESTAMP,
        })
        db.collection('contraceptive_users').document(phone).set({
            "triage_status": "failed",
            "latest_triage_job_id": job_ref.id,
            "triage_error": error_message,
            "triage_completed_at": firestore.SERVER_TIMESTAMP,
        }, merge=True)
        return jsonify({
            "success": False,
            "error": "Could not queue triage job. Please try again.",
            "job_id": job_ref.id,
        }), 503
    
    return jsonify({
        "success": True,
        "status": "queued",
        "job_id": job_ref.id,
        "poll_url": url_for('api_provider_triage_result', job_id=job_ref.id)
    }), 202

@app.route("/api/provider/triage_result/<job_id>", methods=['GET'])
def api_provider_triage_result(job_id):
    pid = session.get('provider_id')
    if not pid: return jsonify({"error": "Unauthorized"}), 401

    doc = db.collection('triage_jobs').document(job_id).get()
    if not doc.exists:
        return jsonify({"error": "Job not found"}), 404

    result = serialize_firestore_value(doc.to_dict())
    if result.get('assigned_provider_id') != pid:
        return jsonify({"error": "Forbidden"}), 403

    recommendation = result.get("recommendation") or ""
    method_cards = result.get("method_cards") or []
    if not method_cards and recommendation:
        method_cards, recommendation = resolve_method_cards(
            recommendation,
            result.get("mec_result") or "",
            result.get("recommendation_citations") or [],
        )
        result["recommendation"] = recommendation
        result["method_cards"] = method_cards

    payload = {"success": True, **result}
    payload["method_cards_count"] = len(method_cards or [])
    return jsonify(payload)

if __name__ == "__main__":
    # For local dev: default to 8080. For Render: uses the dynamic $PORT.
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
