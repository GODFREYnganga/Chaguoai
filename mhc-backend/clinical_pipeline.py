import re
from typing import Any

from app_config import (
    WHATSAPP_MAX_OUTPUT_TOKENS,
    WHATSAPP_RECOMMENDATION_MAX_WORDS,
    WEB_PROVIDER_MAX_OUTPUT_TOKENS,
)
from gemini_client import generate_gemini_text
from rag_ingestor import get_retriever
from rag_prompt import build_system_prompt, format_user_profile_for_prompt, build_web_clinical_instruction
from geography import strip_analytics_fields
from user_profile_mapper import (
    build_method_match_user_message,
    format_survey_context_for_llm,
    map_firestore_user_to_profile,
)
from whatsapp_helpers import trim_to_word_count
from who_mec_engine import format_mec_result_for_llm, run_mec_assessment
from response_cards import (
    build_fallback_method_cards,
    method_cards_to_text,
    parse_method_cards,
    resolve_method_cards,
)


def _avoid_tokens_from_profile(user: dict) -> set[str]:
    """Best-effort filter so deterministic WhatsApp fallback respects stated dislikes."""
    raw = str(user.get("prefer_not_to_use") or "").lower()
    tokens: set[str] = set()
    if "1" in raw or "pill" in raw:
        tokens.add("pill")
    if "2" in raw or "inject" in raw:
        tokens.add("inject")
    if "3" in raw or "iud" in raw or "iucd" in raw:
        tokens.add("iud")
    if "4" in raw or "implant" in raw:
        tokens.add("implant")
    return tokens


def _build_whatsapp_fallback_recommendation(user: dict, mec_text: str, language: str) -> str:
    """
    Deterministic Method Match response when Gemini returns an unusably short answer.
    Uses only methods already classified as safe by the WHO MEC engine.
    """
    name = user.get("name") or "there"
    cards = build_fallback_method_cards(mec_text=mec_text, limit=5)
    avoid = _avoid_tokens_from_profile(user)
    filtered = []
    for card in cards:
        haystack = f"{card.get('name', '')} {card.get('category', '')}".lower()
        if avoid and any(token in haystack for token in avoid):
            continue
        filtered.append(card)
    cards = (filtered or cards)[:3]

    if not cards:
        if language == "swahili":
            return (
                f"Habari {name}, nimekagua majibu yako lakini siwezi kupata njia salama ya kupendekeza moja kwa moja sasa. "
                "Tafadhali zungumza na mhudumu wa afya ili akague historia yako na kukusaidia kuchagua njia inayofaa. "
                "Ukitaka, unaweza pia kujibu MENU kuanza tena."
            )
        return (
            f"Hello {name}, I reviewed your answers but could not identify a safe method to recommend directly right now. "
            "Please discuss your profile with a trained health worker so they can help you choose safely. "
            "You can also reply MENU to start again."
        )

    if language == "swahili":
        lines = [
            f"Habari {name}, kulingana na majibu yako, hizi ni njia salama zaidi kuzingatia:",
        ]
        for idx, card in enumerate(cards, start=1):
            referral = " Inahitaji mhudumu aliyefunzwa kwa kuanza/kuweka." if card.get("referral_required") else ""
            lines.append(
                f"#{idx} *{card.get('name')}*: {card.get('why_it_fits') or card.get('summary')} "
                f"{card.get('common_side_effects') or ''}{referral}"
            )
        lines.append(
            "Chanzo: WHO MEC 6th Edition na Kenya FP Guidelines. Je, ungependa kuzungumza na CHW kuhusu mojawapo ya hizi?"
        )
        return "\n\n".join(lines)

    lines = [
        f"Hello {name}, based on your health profile, these are medically safe options to discuss:",
    ]
    for idx, card in enumerate(cards, start=1):
        referral = " It needs a trained provider for starting or insertion." if card.get("referral_required") else ""
        side_effects = card.get("common_side_effects") or "Side effects vary, so ask your CHW what to expect."
        lines.append(
            f"#{idx} *{card.get('name')}*: {card.get('why_it_fits') or card.get('summary')} "
            f"Common side effects can include {side_effects.lower()}{referral}"
        )
    lines.append(
        "Source: WHO MEC 6th Edition and Kenya FP Guidelines. Which option would you like to ask your CHW about?"
    )
    return "\n\n".join(lines)


def build_retrieval_citations(chunks: list[dict]) -> list[dict]:
    citations = []
    for index, chunk in enumerate(chunks or [], start=1):
        meta = chunk.get("metadata", {}) or {}
        citations.append({
            "id": f"S{index}",
            "document": meta.get("document_title") or "Unknown source",
            "page": meta.get("page_num") or "",
            "chapter": meta.get("chapter") or "",
            "section": meta.get("section") or "",
            "source_citation": chunk.get("source_citation") or "",
        })
    return citations


def format_context_with_citation_ids(retriever, chunks: list[dict]) -> str:
    if not chunks:
        return "[No retrieved guideline chunks available]"
    base = retriever.format_context_for_llm(chunks)
    citation_lines = ["\nSOURCE IDS FOR CITATION:"]
    for citation in build_retrieval_citations(chunks):
        parts = [
            citation["id"],
            citation["document"],
            f"Chapter: {citation['chapter']}" if citation.get("chapter") else "",
            f"Section: {citation['section']}" if citation.get("section") else "",
            f"Page: {citation['page']}" if citation.get("page") else "Page: unknown",
        ]
        citation_lines.append(" | ".join(part for part in parts if part))
    return f"{base}\n" + "\n".join(citation_lines)


def _build_profile_context(user: dict, language: str) -> tuple[str, str]:
    user = strip_analytics_fields(user)
    prof = map_firestore_user_to_profile(user)
    mec_result = run_mec_assessment(prof)
    mec_text = format_mec_result_for_llm(mec_result, language=language)
    prof_dict = {k: v for k, v in prof.__dict__.items() if v is not None}
    prof_summary = format_user_profile_for_prompt(prof_dict)
    prof_summary = f"{prof_summary}\n\n{format_survey_context_for_llm(user)}"
    return mec_text, prof_summary


def _translate_search_query(incoming_msg: str, user_phone: str) -> str:
    try:
        search_query = generate_gemini_text(
            "You are a medical search optimizer. Translate this user sexual health query "
            "into ONLY 3-6 English medical keywords for a textbook search. "
            f"Output ONLY the words, no explanation. Query: {incoming_msg}",
            max_output_tokens=80,
        ).strip()
        search_query = re.sub(r"^(Keywords|Search|Keywords:)\s*", "", search_query, flags=re.IGNORECASE)
        print(f"[{user_phone}] Translated search query: {search_query}")
        return search_query
    except Exception as exc:
        print(f"[{user_phone}] Translation failed, falling back to original: {exc}")
        return incoming_msg


def generate_whatsapp_recommendation(user: dict, *, user_message: str | None = None) -> tuple[str, str]:
    """
    Run MEC + RAG + Gemini for WhatsApp. Returns (reply_text, mec_text).
    """
    language = user.get("language", "english")
    user_phone = user.get("phone", "unknown")
    prompt_message = user_message or build_method_match_user_message(user, language)

    print(f"[{user_phone}] method_match: mec_assessment")
    mec_text, prof_summary = _build_profile_context(user, language)

    print(f"[{user_phone}] method_match: rag_retrieval")
    retriever = get_retriever()
    chunks = retriever.retrieve(
        "WHO MEC contraceptive method recommendation implant IUD injectable pill eligibility",
        top_k=4,
        country_scope="kenya",
    )
    context_str = retriever.format_context_for_llm(chunks)

    print(f"[{user_phone}] method_match: gemini_generation")
    sys_prompt = build_system_prompt(
        mec_result_text=mec_text,
        retrieved_context=context_str,
        user_profile_summary=prof_summary,
        channel="whatsapp",
        language=language,
        user_name=user.get("name", ""),
    )
    full_prompt = f"{sys_prompt}\n\nUser Message: {prompt_message}"
    reply_text = generate_gemini_text(
        full_prompt,
        max_output_tokens=WHATSAPP_MAX_OUTPUT_TOKENS,
        disable_thinking=True,
    )
    word_count = len(reply_text.split())
    print(f"[{user_phone}] method_match: gemini raw reply ({word_count} words)")
    if word_count < 40:
        print(f"[{user_phone}] method_match: retrying — first reply was too short")
        retry_prompt = (
            f"{full_prompt}\n\n"
            "Your previous answer was too short. Write a COMPLETE WhatsApp message "
            "of at least 80 words: greet by name, recommend 2-3 named contraceptive "
            "methods with brief reasons, cite guidelines, end with one short question."
        )
        reply_text = generate_gemini_text(
            retry_prompt,
            max_output_tokens=WHATSAPP_MAX_OUTPUT_TOKENS,
            disable_thinking=True,
        )
        print(f"[{user_phone}] method_match: gemini retry ({len(reply_text.split())} words)")

    if len(reply_text.split()) < 40:
        print(f"[{user_phone}] method_match: using deterministic MEC fallback")
        reply_text = _build_whatsapp_fallback_recommendation(user, mec_text, language)

    reply_text = trim_to_word_count(reply_text, max_words=WHATSAPP_RECOMMENDATION_MAX_WORDS)
    if not reply_text.strip():
        raise RuntimeError("Gemini returned an empty recommendation")
    return reply_text.strip(), mec_text


def generate_whatsapp_chat_reply(user: dict, incoming_msg: str) -> str:
    """General WhatsApp Q&A (non method-match completion)."""
    language = user.get("language", "english")
    user_phone = user.get("phone", "unknown")
    is_registered = user.get("stage") == "REGISTERED"

    mec_text = "[User not yet registered for Method Match]"
    prof_summary = "[No clinical profile available]"
    if is_registered:
        mec_text, prof_summary = _build_profile_context(user, language)

    search_query = incoming_msg
    if language != "english":
        search_query = _translate_search_query(incoming_msg, user_phone)

    retriever = get_retriever()
    chunks = retriever.retrieve(search_query, top_k=4, country_scope="kenya")
    context_str = retriever.format_context_for_llm(chunks)

    sys_prompt = build_system_prompt(
        mec_result_text=mec_text,
        retrieved_context=context_str,
        user_profile_summary=prof_summary,
        channel="whatsapp",
        language=language,
        user_name=user.get("name", ""),
    )
    reply_text = generate_gemini_text(
        f"{sys_prompt}\n\nUser Message: {incoming_msg}",
        max_output_tokens=WHATSAPP_MAX_OUTPUT_TOKENS,
        disable_thinking=True,
    )
    return trim_to_word_count(reply_text, max_words=WHATSAPP_RECOMMENDATION_MAX_WORDS)


def generate_provider_triage_recommendation(user: dict, client_data_json: str) -> tuple[str, str, list[dict], list[dict[str, Any]]]:
    """Provider portal triage with rich METHOD_CARD output."""
    language = "english"
    mec_text, prof_summary = _build_profile_context(user, language)

    search_query = (
        f"Contraception for age {user.get('age')}, parity {user.get('living_children')}, "
        f"preference {user.get('prefer_not_to_use')}"
    )
    retriever = get_retriever()
    chunks = retriever.retrieve(search_query, top_k=4)
    citations = build_retrieval_citations(chunks)
    context_str = format_context_with_citation_ids(retriever, chunks)

    sys_prompt = build_system_prompt(
        mec_result_text=mec_text,
        retrieved_context=context_str,
        user_profile_summary=f"{prof_summary}\n\nProvider triage data: {client_data_json}",
        channel="web",
        language=language,
        user_name=user.get("name", ""),
    )
    full_query = (
        f"{sys_prompt}\n\n{build_web_clinical_instruction()}\n"
        "If recommending implant, IUD, or sterilization, add one Referral Note sentence "
        "after the cards about visiting a trained provider for insertion."
    )
    recommendation = generate_gemini_text(
        full_query,
        max_output_tokens=max(WEB_PROVIDER_MAX_OUTPUT_TOKENS, 1800),
        disable_thinking=True,
    )
    if not recommendation.strip():
        raise RuntimeError("Gemini returned an empty web recommendation")

    cards, recommendation = resolve_method_cards(recommendation, mec_text, citations)
    return recommendation, mec_text, citations, cards


def generate_ussd_recommendation(user: dict) -> tuple[str, str]:
    """Short USSD-safe recommendation (max ~140 chars for END screen)."""
    reply, mec_text = generate_whatsapp_recommendation(user)
    ussd_text = trim_to_word_count(reply, max_words=35)
    if len(ussd_text) > 140:
        ussd_text = ussd_text[:137].rsplit(" ", 1)[0] + "..."
    return ussd_text, mec_text
