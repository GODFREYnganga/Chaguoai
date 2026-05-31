"""
WhatsApp delivery helpers: interactive menus, label truncation, and long-message splitting.
"""

from __future__ import annotations

import json
import time

WHATSAPP_BODY_LIMIT = 1500
QUICK_REPLY_LABEL_LIMIT = 20
LIST_ROW_LABEL_LIMIT = 24


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
) -> dict:
    truncate = truncate_quick_reply_label if quick_reply else truncate_list_row_label
    variables = {"body": body_text[:WHATSAPP_BODY_LIMIT]}
    if not quick_reply:
        variables["button"] = truncate_list_row_label(button_text, 20)
    for i, option in enumerate(options, start=1):
        variables[f"option_{i}"] = truncate(option)
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


def send_twilio_content(twilio_client_factory, from_number: str, to_number: str, content_sid: str, variables: dict) -> bool:
    if not content_sid:
        return False
    try:
        twilio_client_factory().messages.create(
            from_=from_number,
            to=to_number,
            content_sid=content_sid,
            content_variables=json.dumps(variables),
        )
        return True
    except Exception as exc:
        print(f"Twilio Content Error: {exc}")
        return False


def send_options_message(
    *,
    ensure_prefix,
    send_plain,
    send_content,
    quick_reply_sid: str | None,
    list_picker_sid: str | None,
    from_number: str,
    to_number: str,
    body_text: str,
    options: list[str],
    multi_select: bool = False,
    button_text: str = "Choose",
    inter_message_delay: float = 0.4,
) -> None:
    """
    Send interactive WhatsApp options. Tries Twilio Content templates first,
    then falls back to numbered text menus.
    """
    from_number, to_number = ensure_prefix(from_number, to_number)
    options = [str(o) for o in options if str(o).strip()]

    if multi_select:
        body = fallback_option_message(body_text, options, multi_select=True)
        if len(options) <= 10 and list_picker_sid:
            variables = build_twilio_content_variables(body_text, options, button_text=button_text)
            if send_content(from_number, to_number, list_picker_sid, variables):
                send_plain(from_number, to_number, "_Tip: You can also reply with numbers like 1,3 for multiple selections._")
                return
        send_plain(from_number, to_number, body)
        return

    if len(options) <= 3 and quick_reply_sid:
        variables = build_twilio_content_variables(body_text, options[:3], quick_reply=True)
        if send_content(from_number, to_number, quick_reply_sid, variables):
            return

    if list_picker_sid:
        variables = build_twilio_content_variables(body_text, options, button_text=button_text)
        if send_content(from_number, to_number, list_picker_sid, variables):
            return

    send_plain(from_number, to_number, fallback_option_message(body_text, options))


def send_long_whatsapp_message(send_plain, from_number: str, to_number: str, body_text: str) -> None:
    """Send a message split across multiple WhatsApp bubbles if needed."""
    parts = split_message_at_sentences(body_text)
    for index, part in enumerate(parts):
        send_plain(from_number, to_number, part)
        if index < len(parts) - 1:
            time.sleep(0.35)
