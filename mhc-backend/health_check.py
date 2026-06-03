import os
from pathlib import Path

from app_config import TWILIO_NUMBER
from db_client import get_db, init_firebase
from gemini_client import get_genai_client
from task_queue import resolve_redis_url

BASE_DIR = Path(__file__).resolve().parent
CHROMA_DIR = BASE_DIR / "knowledge_base" / "chroma_db"


def run_health_checks() -> dict:
    checks = {}

    try:
        init_firebase()
        db = get_db()
        checks["firebase"] = {"ok": db is not None, "detail": "connected" if db else "not initialized"}
    except Exception as exc:
        checks["firebase"] = {"ok": False, "detail": str(exc)}

    genai = get_genai_client()
    checks["genai"] = {"ok": genai is not None, "detail": "client ready" if genai else "not initialized"}

    checks["twilio"] = {
        "ok": bool(os.environ.get("TWILIO_ACCOUNT_SID") and os.environ.get("TWILIO_AUTH_TOKEN")),
        "detail": TWILIO_NUMBER,
    }

    chroma_ok = CHROMA_DIR.exists() and any(CHROMA_DIR.iterdir()) if CHROMA_DIR.exists() else False
    checks["chroma_db"] = {
        "ok": chroma_ok,
        "detail": str(CHROMA_DIR) if chroma_ok else "missing — run rag_ingestor.py",
    }

    try:
        resolve_redis_url()
        checks["redis"] = {"ok": True, "detail": "url configured"}
    except Exception as exc:
        checks["redis"] = {"ok": False, "detail": str(exc)}

    checks["overall"] = {"ok": all(c.get("ok") for c in checks.values() if isinstance(c, dict))}
    return checks
