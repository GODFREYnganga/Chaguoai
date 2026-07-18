from google import genai
from google.genai import types

from app_config import (
    GEMINI_MAX_OUTPUT_TOKENS,
    GEMINI_MODEL,
    GEMINI_RETRY_ATTEMPTS,
    GEMINI_TIMEOUT_MS,
)

_client = None


def get_genai_client():
    global _client
    if _client is None:
        try:
            _client = genai.Client()
            print("[DEBUG] GenAI Client Initialized.")
        except Exception as exc:
            print(f"Warning: Could not initialize GenAI. {exc}")
            _client = None
    return _client


def _extract_response_text(response) -> str:
    """Collect visible text parts; skip internal thought parts when present."""
    direct = getattr(response, "text", None)
    if direct and str(direct).strip():
        return str(direct).strip()

    chunks: list[str] = []
    for cand in getattr(response, "candidates", None) or []:
        content = getattr(cand, "content", None)
        if not content:
            continue
        for part in getattr(content, "parts", None) or []:
            if getattr(part, "thought", False):
                continue
            text = getattr(part, "text", None)
            if text and str(text).strip():
                chunks.append(str(text).strip())
    return "\n".join(chunks).strip()


def _log_gemini_usage(response, visible_text: str, max_output_tokens: int | None) -> None:
    usage = getattr(response, "usage_metadata", None)
    if not usage:
        return
    thoughts = getattr(usage, "thoughts_token_count", None) or 0
    output_tokens = getattr(usage, "candidates_token_count", None) or 0
    word_count = len(visible_text.split())
    finish = None
    candidates = getattr(response, "candidates", None) or []
    if candidates:
        finish = getattr(candidates[0], "finish_reason", None)

    if word_count < 40 or (thoughts and thoughts >= (max_output_tokens or 0) * 0.5):
        print(
            f"[Gemini] short_or_thinking_limited output: words={word_count} "
            f"thought_tokens={thoughts} output_tokens={output_tokens} "
            f"max_output_tokens={max_output_tokens} finish={finish}"
        )


def _thinking_config(disable_thinking: bool):
    """
    Gemini 2.5 Flash uses 'thinking' tokens inside max_output_tokens.
    With a low cap (e.g. 220), almost no visible text is returned.
    """
    if not disable_thinking or "2.5" not in GEMINI_MODEL:
        return None
    try:
        return types.ThinkingConfig(thinking_budget=0)
    except Exception:
        return None


def generate_gemini_text(
    prompt,
    *,
    max_output_tokens=None,
    temperature=0.2,
    disable_thinking=True,
):
    client = get_genai_client()
    if client is None:
        raise RuntimeError("GenAI client is not initialized")

    token_limit = max_output_tokens or GEMINI_MAX_OUTPUT_TOKENS
    config_kwargs = {
        "temperature": temperature,
        "max_output_tokens": token_limit,
        "http_options": types.HttpOptions(
            timeout=GEMINI_TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(attempts=GEMINI_RETRY_ATTEMPTS),
        ),
    }
    thinking = _thinking_config(disable_thinking)
    if thinking is not None:
        config_kwargs["thinking_config"] = thinking

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(**config_kwargs),
    )
    text = _extract_response_text(response)
    _log_gemini_usage(response, text, token_limit)
    return text
