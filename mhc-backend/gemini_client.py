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


def generate_gemini_text(prompt, *, max_output_tokens=None, temperature=0.2):
    client = get_genai_client()
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
        ),
    )
    return response.text or ""
