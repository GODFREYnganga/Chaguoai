import os

from env_loader import load_backend_dotenv

load_backend_dotenv()

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_TIMEOUT_MS = int(os.environ.get("GEMINI_TIMEOUT_MS", "20000"))
GEMINI_MAX_OUTPUT_TOKENS = int(os.environ.get("GEMINI_MAX_OUTPUT_TOKENS", "900"))
# WhatsApp: allow full Method Match replies (split across bubbles if >1500 chars).
WHATSAPP_MAX_OUTPUT_TOKENS = int(os.environ.get("WHATSAPP_MAX_OUTPUT_TOKENS", "2048"))
WHATSAPP_RECOMMENDATION_MAX_WORDS = int(os.environ.get("WHATSAPP_RECOMMENDATION_MAX_WORDS", "250"))
WEB_PROVIDER_MAX_OUTPUT_TOKENS = int(os.environ.get("WEB_PROVIDER_MAX_OUTPUT_TOKENS", "1400"))
GEMINI_RETRY_ATTEMPTS = int(os.environ.get("GEMINI_RETRY_ATTEMPTS", "1"))

TWILIO_NUMBER = os.environ.get("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")
ADMIN_CODE = os.environ.get("ADMIN_ACCESS_CODE", "")

METHOD_MATCH_FALLBACK = {
    "english": (
        "We could not generate your Method Match right now. "
        "Please visit a health facility or reply MENU to try again."
    ),
    "swahili": (
        "Hatukuweza kutengeneza mapendekezo yako sasa. "
        "Tafadhali tembelea kituo cha afya au jibu MENU kujaribu tena."
    ),
    "french": (
        "Nous n'avons pas pu générer vos recommandations. "
        "Consultez un centre de santé ou répondez MENU."
    ),
    "portuguese": (
        "Nao foi possivel gerar suas recomendacoes agora. "
        "Visite uma unidade de saude ou responda MENU."
    ),
}
