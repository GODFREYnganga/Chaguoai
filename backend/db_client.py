import base64
import json
import os
import re

from firebase_admin import credentials, firestore, initialize_app

_db = None
_initialized = False


def _parse_service_account_json(raw: str) -> dict:
    """Parse Firebase service-account JSON from an env var (Render-safe)."""
    text = (raw or "").strip()
    if not text.startswith("{"):
        raise ValueError(
            "GOOGLE_APPLICATION_CREDENTIALS must be inline JSON starting with '{' "
            "or a path to a service-account file."
        )
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        # Common Render mistake: real newlines inside "private_key" break JSON escapes.
        match = re.search(
            r'"private_key"\s*:\s*"(.*?)"\s*,',
            text,
            flags=re.DOTALL,
        )
        if match:
            key_body = match.group(1)
            if "\n" in key_body and "\\n" not in key_body:
                escaped_key = key_body.replace("\n", "\\n").replace('"', '\\"')
                repaired = text[: match.start(1)] + escaped_key + text[match.end(1) :]
                try:
                    return json.loads(repaired)
                except json.JSONDecodeError:
                    pass
        raise ValueError(
            "Invalid Firebase service-account JSON in GOOGLE_APPLICATION_CREDENTIALS. "
            "On Render, paste the JSON on one line or set GOOGLE_APPLICATION_CREDENTIALS_BASE64 "
            f"instead. Parser error: {exc}"
        ) from exc


def _load_service_account_dict() -> dict | None:
    b64 = (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_BASE64") or "").strip()
    if b64:
        try:
            decoded = base64.b64decode(b64).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError(
                "GOOGLE_APPLICATION_CREDENTIALS_BASE64 is not valid base64 UTF-8 JSON."
            ) from exc
        return _parse_service_account_json(decoded)

    creds_val = (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
    if not creds_val:
        return None
    if creds_val.startswith("{"):
        return _parse_service_account_json(creds_val)
    return None


def _initialize_firebase_app(*, bucket_name: str | None) -> None:
    options = {"storageBucket": bucket_name} if bucket_name else {}
    creds_dict = _load_service_account_dict()
    creds_val = (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()

    if creds_dict is not None:
        firebase_creds = credentials.Certificate(creds_dict)
        initialize_app(firebase_creds, options)
        return

    if creds_val and os.path.exists(creds_val):
        firebase_creds = credentials.Certificate(creds_val)
        initialize_app(firebase_creds, options)
        return

    initialize_app(options=options)


def init_firebase():
    global _db, _initialized
    if _initialized:
        return _db

    bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET")

    try:
        try:
            _initialize_firebase_app(bucket_name=bucket_name)
        except ValueError as exc:
            if "already exists" not in str(exc).lower():
                raise
        _db = firestore.client()
        print("[DEBUG] Firebase Initialized Successfully.")
    except Exception as exc:
        print(f"CRITICAL Warning: Could not initialize firebase. {exc}")
        _db = None

    _initialized = True
    return _db


def get_db():
    if _db is None and not _initialized:
        init_firebase()
    return _db
