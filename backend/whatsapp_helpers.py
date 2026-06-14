"""
WhatsApp delivery helpers: interactive menus, label truncation, and long-message splitting.
"""

from __future__ import annotations

import json
import re
import time

from twilio_templates import TwilioTemplateRegistry

WHATSAPP_BODY_LIMIT = 1500
QUICK_REPLY_LABEL_LIMIT = 20
LIST_ROW_LABEL_LIMIT = 24
WHATSAPP_MAX_WORDS = 250
WHATSAPP_MIN_WORDS = 50
WEB_MAX_WORDS = 200


def trim_to_word_count(text: str, max_words: int = WHATSAPP_MAX_WORDS) -> str:
    """Trim only when over max_words; prefer ending at a sentence boundary."""
    text = re.sub(r"\s+", " ", str(text or "").strip())
    if not text:
        return text
    words = text.split()
    if len(words) <= max_words:
        return text
    trimmed = " ".join(words[:max_words])
    for punct in (". ", "! ", "? "):
        idx = trimmed.rfind(punct)
        # Do not cut to a tiny fragment (e.g. greeting-only) before the real recommendation.
        if idx > len(trimmed) // 2 and (trimmed[: idx + 1].count(" ") + 1) >= WHATSAPP_MIN_WORDS:
            return trimmed[: idx + 1].strip()
    return trimmed.rstrip(",;:") + "…"


def format_recommendation_for_whatsapp(text: str, max_words: int = WHATSAPP_MAX_WORDS) -> str:
    """Convert METHOD_CARD blocks or long clinical text into a concise WhatsApp message."""
    raw = str(text or "").strip()
    cards = re.findall(r"\[METHOD_CARD\]([\s\S]*?)\[/METHOD_CARD\]", raw, re.IGNORECASE)
    if cards:
        lines = []
        for card in cards[:3]:
            name = re.search(r"NAME:\s*(.+)", card, re.IGNORECASE)
            summary = re.search(r"SUMMARY:\s*(.+)", card, re.IGNORECASE)
            if name and summary:
                lines.append(f"• *{name.group(1).strip()}* — {summary.group(1).strip()}")
        if lines:
            return trim_to_word_count("\n".join(lines), max_words=max_words)
    cleaned = re.sub(r"\[/?METHOD_CARD\]", "", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return trim_to_word_count(cleaned, max_words=max_words)


def truncate_quick_reply_label(text: str, limit: int = QUICK_REPLY_LABEL_LIMIT) -> str:
    text = str(text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def truncate_list_row_label(text: str, limit: int = LIST_ROW_LABEL_LIMIT) -> str:
    text = str(text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def split_message_at_sentences(text: str, max_len: int = WHATSAPP_BODY_LIMIT) -> list[str]:
    """Split long text into WhatsApp-sized chunks, never cutting mid-sentence when possible."""
    text = str(text or "").strip()
    if not text:
        return []
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining.strip())
            break

        window = remaining[:max_len]
        split_at = max(
            window.rfind(". "),
            window.rfind("! "),
            window.rfind("? "),
            window.rfind("\n\n"),
            window.rfind("\n"),
        )
        if split_at <= max_len // 3:
            split_at = window.rfind(" ")
        if split_at <= 0:
            split_at = max_len

        piece = remaining[:split_at].strip()
        if piece:
            chunks.append(piece)
        remaining = remaining[split_at:].lstrip()

    return [c for c in chunks if c]


def build_twilio_content_variables(
    body_text: str,
    options: list[str],
    *,
    button_text: str = "Choose",
    quick_reply: bool = False,
    template_slots: int | None = None,
) -> dict:
    """Build variables matching the exact slot count the Twilio template expects."""
    truncate = truncate_quick_reply_label if quick_reply else truncate_list_row_label
    slot_count = template_slots if template_slots is not None else len(options)
    variables = {"body": body_text[:WHATSAPP_BODY_LIMIT]}
    if not quick_reply:
        variables["button"] = truncate_list_row_label(button_text, 20)
    for i in range(1, slot_count + 1):
        if i <= len(options):
            variables[f"option_{i}"] = truncate(options[i - 1])
            variables[f"option_{i}_payload"] = str(i)
        else:
            # Pad unused slots when falling back to a larger legacy template
            variables[f"option_{i}"] = truncate(f"Option {i}")
            variables[f"option_{i}_payload"] = str(i)
    return variables


def fallback_option_message(body_text: str, options: list[str], *, multi_select: bool = False) -> str:
    menu_body = f"{body_text}\n\n"
    for i, option in enumerate(options, start=1):
        menu_body += f"{i}. *{option}*\n"
    if multi_select:
        menu_body += "\nReply with one or more numbers (e.g. 1,3). Choose *None* alone if none apply."
    else:
        menu_body += "\nReply with a number or tap an option."
    return menu_body


def send_twilio_content(
    twilio_client_factory,
    from_number: str,
    to_number: str,
    content_sid: str,
    variables: dict,
    *,
    option_count: int = 0,
    mode: str = "",
) -> bool:
    if not content_sid:
        return False
    client = twilio_client_factory()
    if not client:
        return False
    try:
        client.messages.create(
            from_=from_number,
            to=to_number,
            content_sid=content_sid,
            content_variables=json.dumps(variables),
        )
        return True
    except Exception as exc:
        print(
            f"Twilio Content Error ({option_count} options, {mode}, SID={content_sid}): {exc}"
        )
        return False


def _multi_select_tip(language: str | None) -> str:
    lang = str(language or "").lower()
    if lang in ("sw", "swahili", "2"):
        return "_Kidokezo: Kwa michaguo mingi, jawabu na namba kama 1,3._"
    return "_Tip: For multiple selections, reply with numbers like 1,3._"


def send_options_message(
    *,
    ensure_prefix,
    send_plain,
    send_content,
    template_registry: TwilioTemplateRegistry,
    from_number: str,
    to_number: str,
    body_text: str,
    options: list[str],
    multi_select: bool = False,
    button_text: str = "Choose",
    language: str | None = None,
    redis_client=None,
    firestore_client=None,
) -> None:
    """
    Send interactive WhatsApp options using size-matched Twilio Content templates.
    Falls back to numbered text if templates are missing or misconfigured.
    """
    from_number, to_number = ensure_prefix(from_number, to_number)
    options = [str(o) for o in options if str(o).strip()]
    if not options:
        send_plain(from_number, to_number, body_text)
        return

    content_sid, mode, template_slots = template_registry.resolve(len(options))

    if content_sid:
        variables = build_twilio_content_variables(
            body_text,
            options,
            button_text=button_text,
            quick_reply=(mode == "quick_reply"),
            template_slots=template_slots,
        )

        def _send(sid, vars_, count, send_mode):
            return send_content(
                from_number,
                to_number,
                sid,
                vars_,
                option_count=count,
                mode=send_mode,
            )

        if _send(content_sid, variables, len(options), mode):
            if multi_select:
                send_plain(from_number, to_number, _multi_select_tip(language))
            return

        # Exact template failed — try list picker as secondary path for 2–3 option questions
        if mode == "quick_reply" and len(options) <= 3:
            list_sid, list_mode, list_slots = template_registry.resolve(max(len(options), 4))
            if list_sid and list_sid != content_sid:
                list_vars = build_twilio_content_variables(
                    body_text,
                    options,
                    button_text=button_text,
                    quick_reply=False,
                    template_slots=list_slots,
                )
                if _send(list_sid, list_vars, len(options), list_mode):
                    if multi_select:
                        send_plain(from_number, to_number, _multi_select_tip(language))
                    return

    send_plain(from_number, to_number, fallback_option_message(body_text, options, multi_select=multi_select))


def send_long_whatsapp_message(send_plain, from_number: str, to_number: str, body_text: str) -> None:
    """Send a message split across multiple WhatsApp bubbles if needed."""
    parts = split_message_at_sentences(body_text)
    for index, part in enumerate(parts):
        send_plain(from_number, to_number, part)
        if index < len(parts) - 1:
            time.sleep(0.35)
