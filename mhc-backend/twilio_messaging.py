import os

from dotenv import load_dotenv
from twilio.rest import Client as TwilioClient

from twilio_templates import TwilioTemplateRegistry
from whatsapp_helpers import (
    send_long_whatsapp_message,
    send_options_message,
    send_twilio_content,
    split_message_at_sentences,
)

load_dotenv()

TWILIO_NUMBER = os.environ.get("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")
TWILIO_SMS_NUMBER = os.environ.get("TWILIO_SMS_NUMBER", "").strip()
TWILIO_TEMPLATES = TwilioTemplateRegistry.from_env()


def _get_twilio_client():
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    if not account_sid or not auth_token:
        return None
    return TwilioClient(account_sid, auth_token)


def ensure_whatsapp_prefix(from_number, to_number):
    if from_number.startswith("whatsapp:") and not to_number.startswith("whatsapp:"):
        to_number = f"whatsapp:{to_number}"
    elif not from_number.startswith("whatsapp:") and to_number.startswith("whatsapp:"):
        from_number = f"whatsapp:{from_number}"
    return from_number, to_number


def send_whatsapp_message(from_number, to_number, body_text, media_url=None):
    twilio_client = _get_twilio_client()
    if not twilio_client:
        print("Missing Twilio Auth credentials in environment!")
        return False

    from_number, to_number = ensure_whatsapp_prefix(from_number, to_number)

    def _send_single(from_num, to_num, text):
        try:
            twilio_client.messages.create(
                from_=from_num,
                body=split_message_at_sentences(text, 1500)[0],
                to=to_num,
                media_url=[media_url] if media_url else None,
            )
            return True
        except Exception as exc:
            print(f"Twilio Error: {exc}")
            return False

    if media_url or len(body_text) <= 1500:
        return _send_single(from_number, to_number, body_text)
    send_long_whatsapp_message(_send_single, from_number, to_number, body_text)
    return True


def send_sms_message(to_number, body_text, from_number=None):
    """Send plain SMS when a Twilio SMS number is configured."""
    twilio_client = _get_twilio_client()
    sms_from = from_number or TWILIO_SMS_NUMBER
    if not twilio_client or not sms_from:
        print("Missing Twilio SMS credentials or TWILIO_SMS_NUMBER.")
        return False
    try:
        twilio_client.messages.create(
            from_=sms_from,
            body=str(body_text or "")[:1600],
            to=to_number.replace("whatsapp:", ""),
        )
        return True
    except Exception as exc:
        print(f"Twilio SMS Error: {exc}")
        return False


def send_whatsapp_with_sms_fallback(from_number, to_number, body_text):
    """
    Try WhatsApp first, then SMS if configured.
    Returns a delivery metadata dict for Firestore audit fields.
    """
    try:
        whatsapp_ok = send_whatsapp_message(from_number, to_number, body_text)
        if whatsapp_ok:
            return {"channel": "whatsapp", "status": "sent"}
        raise RuntimeError("WhatsApp delivery returned false")
    except Exception as exc:
        sms_ok = send_sms_message(to_number, body_text)
        if sms_ok:
            return {"channel": "sms", "status": "sent", "whatsapp_error": str(exc)}
        return {"channel": "none", "status": "failed", "error": str(exc)}


def send_twilio_content_message(
    from_number,
    to_number,
    content_sid,
    variables,
    *,
    option_count=0,
    mode="",
    **kwargs,
):
    """Send via Twilio Content API. Extra kwargs (language, redis_client, etc.) are ignored for compatibility."""
    return send_twilio_content(
        _get_twilio_client,
        from_number,
        to_number,
        content_sid,
        variables,
        option_count=option_count,
        mode=mode,
    )


def send_whatsapp_options(
    from_number,
    to_number,
    body_text,
    options,
    multi_select=False,
    button_text="Choose",
    language=None,
):
    send_options_message(
        ensure_prefix=ensure_whatsapp_prefix,
        send_plain=send_whatsapp_message,
        send_content=send_twilio_content_message,
        template_registry=TWILIO_TEMPLATES,
        from_number=from_number,
        to_number=to_number,
        body_text=body_text,
        options=options,
        multi_select=multi_select,
        button_text=button_text,
        language=language,
    )
