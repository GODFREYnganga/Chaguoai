"""Profile-grounded WhatsApp general Q&A helpers (no LLM dependency)."""

from __future__ import annotations

import re


def extract_method_hint(text: str, limit: int = 120) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"\s+", " ", str(text)).strip()
    match = re.search(r"\*([^*]+)\*", cleaned)
    if match:
        return match.group(1).strip()[:limit]
    for keyword in ("Implant", "IUD", "Injection", "Pill", "Condom", "Injectable", "DIU"):
        if keyword.lower() in cleaned.lower():
            return keyword
    return cleaned[:limit]


def user_has_clinical_profile(user: dict) -> bool:
    if user.get("stage") in ("REGISTERED", "MAIN_MENU"):
        if user.get("age") is not None or user.get("registered_at"):
            return True
    if user.get("method_match_status") == "completed" or user.get("triage_status") == "completed":
        return True
    if user.get("matched_method") or user.get("latest_recommendation"):
        return True
    if user.get("latest_mec_text") or user.get("latest_mec_result"):
        return True
    return False


def method_hint_from_profile(user: dict) -> str:
    selected = str(user.get("selected_method") or "").strip()
    if selected:
        return selected
    snippet = extract_method_hint(user.get("matched_method") or user.get("latest_recommendation") or "")
    if snippet:
        return snippet
    cards = user.get("method_cards") or []
    if cards:
        return str(cards[0].get("name") or cards[0].get("display_name") or "your recommended options")
    return "your recommended options"


_VAGUE_CHAT_PATTERNS = (
    r"^(hi|hello|hey|habari|bonjour|ola|help|\?|menu)\.?$",
    r"^(what|how|tell me|more|explain|info|information)\.?$",
    r"^i have (a )?question",
    r"^can you help",
    r"^general question",
    r"^ask (a )?question",
)


def is_vague_chat_question(message: str) -> bool:
    cleaned = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not cleaned:
        return True
    words = cleaned.split()
    if len(words) <= 3 and "?" not in cleaned:
        return True
    return any(re.search(pattern, cleaned) for pattern in _VAGUE_CHAT_PATTERNS)


def build_chat_clarification_reply(user: dict, language: str) -> str:
    name = user.get("name") or ""
    method_hint = method_hint_from_profile(user)
    greet = f"{name}, " if name else ""
    if language == "swahili":
        return (
            f"Habari {greet}nimeona una swali. Kulingana na Method Match yako, "
            f"je unauliza kuhusu *{method_hint}*, madhara, jinsi ya kuanza, au kitu kingine? "
            "Taja moja ili nikujibu kwa usahihi."
        )
    if language == "french":
        return (
            f"Bonjour {greet}j'ai votre profil Method Match. "
            f"Posez-vous une question sur *{method_hint}*, les effets secondaires, "
            "comment commencer, ou autre chose? Indiquez un sujet."
        )
    if language == "portuguese":
        return (
            f"Olá {greet}tenho o seu perfil do Method Match. "
            f"A pergunta é sobre *{method_hint}*, efeitos secundários, "
            "como começar, ou outro assunto? Diga qual tema."
        )
    return (
        f"Hi {greet}I have your Method Match profile. "
        f"Are you asking about *{method_hint}*, side effects, how to get started, or something else? "
        "Reply with one topic so I can answer precisely."
    )
