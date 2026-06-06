import os

from redis import Redis
from rq import Queue

from env_loader import load_backend_dotenv

load_backend_dotenv()

TRIAGE_QUEUE_NAME = os.environ.get("TRIAGE_QUEUE_NAME", "triage")
TRIAGE_JOB_TIMEOUT_SECONDS = int(os.environ.get("TRIAGE_JOB_TIMEOUT_SECONDS", "180"))
TRIAGE_JOB_RESULT_TTL_SECONDS = int(os.environ.get("TRIAGE_JOB_RESULT_TTL_SECONDS", "3600"))
TRIAGE_JOB_FAILURE_TTL_SECONDS = int(os.environ.get("TRIAGE_JOB_FAILURE_TTL_SECONDS", "86400"))

_PLACEHOLDER_MARKERS = ("your-render-redis-url", "your-redis-url", "changeme", "replace-me")


def resolve_redis_url() -> str:
    candidates = [
        os.environ.get("REDIS_URL"),
        os.environ.get("REDIS_INTERNAL_URL"),
        os.environ.get("REDIS_TLS_URL"),
    ]
    raw = next((c.strip() for c in candidates if c and c.strip()), "")
    if not raw:
        raise RuntimeError(
            "REDIS_URL is not configured. Set the Internal Redis URL on Render "
            "(must start with redis:// or rediss://)."
        )
    lowered = raw.lower()
    if any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        raise RuntimeError(f"REDIS_URL still contains a placeholder ({raw!r}).")
    if raw.startswith(("redis://", "rediss://", "unix://")):
        return raw
    if "@" in raw or ":" in raw:
        return f"redis://{raw}"
    raise RuntimeError(f"REDIS_URL is invalid ({raw!r}).")


def get_redis_connection():
    return Redis.from_url(
        resolve_redis_url(),
        socket_connect_timeout=5,
        socket_timeout=5,
        health_check_interval=30,
    )


def get_triage_queue():
    return Queue(
        TRIAGE_QUEUE_NAME,
        connection=get_redis_connection(),
        default_timeout=TRIAGE_JOB_TIMEOUT_SECONDS,
    )
