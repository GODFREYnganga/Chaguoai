import os

from dotenv import load_dotenv
from redis import Redis
from rq import Queue


load_dotenv()

TRIAGE_QUEUE_NAME = os.environ.get("TRIAGE_QUEUE_NAME", "triage")
REDIS_URL = os.environ.get("REDIS_URL")
TRIAGE_JOB_TIMEOUT_SECONDS = int(os.environ.get("TRIAGE_JOB_TIMEOUT_SECONDS", "180"))
TRIAGE_JOB_RESULT_TTL_SECONDS = int(os.environ.get("TRIAGE_JOB_RESULT_TTL_SECONDS", "3600"))
TRIAGE_JOB_FAILURE_TTL_SECONDS = int(os.environ.get("TRIAGE_JOB_FAILURE_TTL_SECONDS", "86400"))


def get_redis_connection():
    if not REDIS_URL:
        raise RuntimeError("REDIS_URL is not configured")
    return Redis.from_url(
        REDIS_URL,
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
