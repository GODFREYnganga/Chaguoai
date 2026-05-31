import os
import re
import datetime
import json
import threading
from dotenv import load_dotenv
from flask import Flask, request, Response, render_template, session, redirect, url_for, jsonify
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client as TwilioClient
from firebase_admin import firestore, initialize_app, credentials
from google import genai
from google.genai import types

from ussd_logic import handle_ussd_request
from who_mec_engine import run_mec_assessment, format_mec_result_for_llm
from rag_ingestor import get_retriever
from rag_prompt import build_system_prompt, format_user_profile_for_prompt
from task_queue import (
    TRIAGE_JOB_FAILURE_TTL_SECONDS,
    TRIAGE_JOB_RESULT_TTL_SECONDS,
    TRIAGE_JOB_TIMEOUT_SECONDS,
    get_triage_queue,
)
from user_profile_mapper import (
    build_method_match_user_message,
    format_survey_context_for_llm,
    map_firestore_user_to_profile,
)
from twilio_templates import TwilioTemplateRegistry
from whatsapp_helpers import (
    send_long_whatsapp_message,
    send_options_message,
    send_twilio_content,
    split_message_at_sentences,
)

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

try:
    bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET")
    creds_val = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    
    print(f"[DEBUG] Starting initialization. Port: {os.environ.get('PORT', '8080')}")
    
    # Render/Cloud Friendly: Check if creds_val is a JSON string or a file path
    if creds_val and creds_val.strip().startswith('{'):
        creds_dict = json.loads(creds_val)
        firebase_creds = credentials.Certificate(creds_dict)
        initialize_app(firebase_creds, {'storageBucket': bucket_name} if bucket_name else {})
    elif creds_val and os.path.exists(creds_val):
        firebase_creds = credentials.Certificate(creds_val)
        initialize_app(firebase_creds, {'storageBucket': bucket_name} if bucket_name else {})
    else:
        initialize_app(options={'storageBucket': bucket_name} if bucket_name else {})
    
    db = firestore.client()
    print("[DEBUG] Firebase Initialized Successfully.")
except ValueError:
    db = firestore.client()
    pass # App already initialized
except Exception as e:
    print(f"CRITICAL Warning: Could not initialize firebase. {e}")
    db = None # Allow app to start even if DB fails, so health check can pass

try:
    client = genai.Client()
    print("[DEBUG] GenAI Client Initialized.")
except Exception as e:
    print(f"Warning: Could not initialize GenAI. {e}")
    client = None

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_TIMEOUT_MS = int(os.environ.get("GEMINI_TIMEOUT_MS", "20000"))
GEMINI_MAX_OUTPUT_TOKENS = int(os.environ.get("GEMINI_MAX_OUTPUT_TOKENS", "900"))
GEMINI_RETRY_ATTEMPTS = int(os.environ.get("GEMINI_RETRY_ATTEMPTS", "1"))

def generate_gemini_text(prompt, *, max_output_tokens=None, temperature=0.2):
    if client is None:
        raise RuntimeError("GenAI client is not initialized")

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_output_tokens or GEMINI_MAX_OUTPUT_TOKENS,
            http_options=types.HttpOptions(
                timeout=GEMINI_TIMEOUT_MS,
                retry_options=types.HttpRetryOptions(attempts=GEMINI_RETRY_ATTEMPTS),
            ),
        )
    )
    return response.text or ""

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
TWILIO_TEMPLATES = TwilioTemplateRegistry.from_env()

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

def _get_twilio_client():
    account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
    auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
    if not account_sid or not auth_token:
        return None
    return TwilioClient(account_sid, auth_token)

def _ensure_whatsapp_prefix(from_number, to_number):
    if from_number.startswith('whatsapp:') and not to_number.startswith('whatsapp:'):
        to_number = f"whatsapp:{to_number}"
    elif not from_number.startswith('whatsapp:') and to_number.startswith('whatsapp:'):
        from_number = f"whatsapp:{from_number}"
    return from_number, to_number

def send_whatsapp_message(from_number, to_number, body_text, media_url=None):
    twilio_client = _get_twilio_client()
    if not twilio_client:
        print("Missing Twilio Auth credentials in environment!")
        return

    from_number, to_number = _ensure_whatsapp_prefix(from_number, to_number)

    def _send_single(from_num, to_num, text):
        try:
            twilio_client.messages.create(
                from_=from_num,
                body=split_message_at_sentences(text, 1500)[0],
                to=to_num,
                media_url=[media_url] if media_url else None
            )
        except Exception as e:
            print(f"Twilio Error: {e}")

    if media_url or len(body_text) <= 1500:
        _send_single(from_number, to_number, body_text)
    else:
        send_long_whatsapp_message(_send_single, from_number, to_number, body_text)

def _send_twilio_content(from_number, to_number, content_sid, variables, *, option_count=0, mode=""):
    return send_twilio_content(
        _get_twilio_client,
        from_number,
        to_number,
        content_sid,
        variables,
        option_count=option_count,
        mode=mode,
    )

def send_whatsapp_buttons(from_number, to_number, body_text, buttons):
    send_whatsapp_options(from_number, to_number, body_text, buttons)

def send_whatsapp_options(from_number, to_number, body_text, options, multi_select=False, button_text="Choose"):
    send_options_message(
        ensure_prefix=_ensure_whatsapp_prefix,
        send_plain=send_whatsapp_message,
        send_content=_send_twilio_content,
        template_registry=TWILIO_TEMPLATES,
        from_number=from_number,
        to_number=to_number,
        body_text=body_text,
        options=options,
        multi_select=multi_select,
        button_text=button_text,
    )

def send_whatsapp_list_picker(from_number, to_number, body_text, options, button_text="Choose"):
    send_whatsapp_options(from_number, to_number, body_text, options, button_text=button_text)

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
            db.collection('contraceptive_users').document(user_phone).update({"name": incoming_msg.strip(), "stage": "AWAITING_Q1_AGE"})
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
            send_whatsapp_options(to_number, user_phone, question_body(q["q6"]), HEALTH_CONDITION_OPTIONS, multi_select=True, button_text="Conditions")
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
            send_whatsapp_options(to_number, user_phone, question_body(q["q13"]), METHOD_AVOID_OPTIONS, multi_select=True, button_text="Methods")
            return

        if stage == "AWAITING_Q13_PREFERENCES":
            db.collection('contraceptive_users').document(user_phone).update({
                "prefer_not_to_use": incoming_msg.strip(),
                "registered_at": firestore.SERVER_TIMESTAMP,
                "stage": "REGISTERED",
                "method_match_pending": True,
            })
            send_whatsapp_message(to_number, user_phone, q["finished"])
            user = get_user_state(user_phone)
            incoming_msg = build_method_match_user_message(user, lang)
            stage = "REGISTERED"

        
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
            print(f"\n==========================================")
            print(f"[{user_phone}] AI Processing...")
            
            is_registered = (user.get("stage") == "REGISTERED")
            is_method_match = bool(user.get("method_match_pending")) or incoming_msg.startswith("The client") or incoming_msg.startswith("Mteja") or incoming_msg.startswith("La cliente") or incoming_msg.startswith("A cliente")
            user_lang = user.get('language', 'english')
            
            mec_text = "[User not yet registered for Method Match]"
            prof_summary = "[No clinical profile available]"
            
            if is_registered:
                prof = map_firestore_user_to_profile(user)
                mec_result = run_mec_assessment(prof)
                mec_text = format_mec_result_for_llm(mec_result, language=user_lang)
                prof_dict = {k: v for k, v in prof.__dict__.items() if v is not None}
                prof_summary = format_user_profile_for_prompt(prof_dict)
                prof_summary = f"{prof_summary}\n\n{format_survey_context_for_llm(user)}"
            
            retriever = get_retriever()
            
            search_query = incoming_msg
            if user_lang != 'english' and not is_method_match:
                try:
                    search_query = generate_gemini_text(
                        f"You are a medical search optimizer. Translate this user sexual health query into ONLY 3-6 English medical keywords for a textbook search. Output ONLY the words, no explanation. Query: {incoming_msg}",
                        max_output_tokens=80
                    ).strip()
                    search_query = re.sub(r'^(Keywords|Search|Keywords:)\s*', '', search_query, flags=re.IGNORECASE)
                    print(f"[{user_phone}] Translated search query: {search_query}")
                except Exception as e:
                    print(f"[{user_phone}] Translation failed, falling back to original: {e}")
            
            if is_method_match:
                search_query = "WHO MEC contraceptive method recommendation implant IUD injectable pill eligibility"

            chunks = retriever.retrieve(search_query, top_k=4, country_scope='kenya')
            print(f"[{user_phone}] Retrieved {len(chunks)} chunks for context.")
            for i, c in enumerate(chunks):
                print(f"  Chunk {i+1}: {c['source_citation']} (Score: {c.get('final_score', 0):.3f})")
            
            context_str = retriever.format_context_for_llm(chunks)
            
            sys_prompt = build_system_prompt(
                mec_result_text=mec_text,
                retrieved_context=context_str,
                user_profile_summary=prof_summary,
                channel="whatsapp",
                language=user_lang,
                user_name=user.get('name', '')
            )
            
            max_tokens = 650 if is_method_match else GEMINI_MAX_OUTPUT_TOKENS
            reply_text = generate_gemini_text(f"{sys_prompt}\n\nUser Message: {incoming_msg}", max_output_tokens=max_tokens)
            
            send_long_whatsapp_message(send_whatsapp_message, to_number, user_phone, reply_text)
            
            update_fields = {}
            if is_method_match:
                update_fields = {
                    'matched_method': reply_text.strip(),
                    'latest_mec_text': mec_text,
                    'method_match_pending': False,
                    'stage': 'MAIN_MENU',
                }
            db.collection('contraceptive_users').document(user_phone).update(update_fields) if update_fields else None
            
            print(f"[{user_phone}] Success!")
            print(f"==========================================\n")

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
    return handle_ussd_request(session_id, service_code, phone_number, text, db=db, client=client)


# ======================== ADMIN DASHBOARD ========================
@app.route("/admin")
def admin_login_page():
    return render_template('admin_login.html')

@app.route("/admin/portal")
def admin_portal():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login_page'))
    return render_template('admin_portal.html')
# Access Codes for Admin
ADMIN_CODE = "ADMIN2026"

def to_fhir_patient(user_data):
    """Maps Firestore user data to a basic FHIR R4 Patient resource."""
    return {
        "resourceType": "Patient",
        "id": user_data.get('phone', 'unknown').replace('+', ''),
        "identifier": [{"system": "tel", "value": user_data.get('phone')}],
        "name": [{"text": user_data.get('name', 'Anonymous Client')}],
        "extension": [
            {"url": "http://chaguoai.ke/fhir/assigned_provider", "valueString": user_data.get('assigned_provider_id')}
        ]
    }

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

@app.route("/api/admin/stats", methods=['GET'])
def admin_stats():
    try:
        users = list(db.collection('contraceptive_users').stream())
        providers = list(db.collection('providers').stream())
        
        # Robust Method Extraction for Analytics
        method_counts = {}
        # Define common category keywords to look for in AI responses
        categories = ["Implant", "IUD", "Injection", "Pill", "Condom", "Sterilization", "Patch", "Ring", "Emergency"]
        
        for u in users:
            data = u.to_dict()
            raw_rec = data.get('matched_method', '')
            
            if not raw_rec or "Unmatched" in raw_rec:
                method_counts["Unmatched"] = method_counts.get("Unmatched", 0) + 1
                continue
            
            # Simple keyword matching to categorize the long AI text
            found = False
            for cat in categories:
                if cat.lower() in raw_rec.lower():
                    method_counts[cat] = method_counts.get(cat, 0) + 1
                    found = True
                    break # Assign to the first prominent category found
            
            if not found:
                method_counts["Other/Complex"] = method_counts.get("Other/Complex", 0) + 1
            
        stats = {
            "total_clients": len(users),
            "active_chws": len([p for p in providers if p.to_dict().get('role') == 'chw' and p.to_dict().get('status') == 'approved']),
            "active_clinicians": len([p for p in providers if p.to_dict().get('role') == 'clinician' and p.to_dict().get('status') == 'approved']),
            "method_stats": method_counts,
            # Add recent activity highlights
            "recent_activity": [
                {
                    "user": u.to_dict().get("name", "Unknown"),
                    "phone": u.id,
                    "date": u.to_dict().get("registered_at", ""),
                    "snippet": u.to_dict().get("matched_method", "")[:80] + "..."
                } for u in sorted(users, key=lambda x: str(x.to_dict().get("registered_at", "")), reverse=True)[:5]
            ]
        }
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/admin/pending_providers", methods=['GET'])
def admin_pending_providers():
    providers = []
    for doc in db.collection('providers').where('status', '==', 'pending').stream():
        p = doc.to_dict()
        p['id'] = doc.id
        providers.append(p)
    return jsonify({"providers": providers})

@app.route("/api/admin/approve_provider/<provider_id>", methods=['POST'])
def admin_approve_provider(provider_id):
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
    return value

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

@app.route("/api/provider/roster", methods=['GET'])
def api_provider_roster():
    pid = session.get('provider_id')
    if not pid: return jsonify({"error": "Unauthorized"}), 401
    
    users = []
    for doc in db.collection('contraceptive_users').where(filter=firestore.FieldFilter('assigned_provider_id', '==', pid)).stream():
        u = serialize_firestore_value(doc.to_dict())
        u['id'] = doc.id
        u['method_snippet'] = extract_method_snippet(u.get('matched_method') or u.get('latest_recommendation'))
        u['registered_at'] = serialize_firestore_value(u.get('registered_at'))
        users.append(u)
    return jsonify({"clients": users})

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
            f"{sys_prompt}\n\nClinician Query: {query}\n\n"
            "IMPORTANT: You MUST output 1-3 recommended methods using [METHOD_CARD] blocks "
            "with NAME, SUMMARY, and DETAILS fields. Include MEC category and citations."
        )
        
        response_text = generate_gemini_text(full_prompt, max_output_tokens=900)
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
            job_timeout=TRIAGE_JOB_TIMEOUT_SECONDS,
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

    result = doc.to_dict()
    if result.get('assigned_provider_id') != pid:
        return jsonify({"error": "Forbidden"}), 403

    return jsonify({"success": True, **result})

if __name__ == "__main__":
    # For local dev: default to 8080. For Render: uses the dynamic $PORT.
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
