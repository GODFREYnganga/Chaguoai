import sys

from rq import SimpleWorker, Worker

import method_match_tasks  # noqa: F401
import triage_tasks  # noqa: F401
from task_queue import TRIAGE_QUEUE_NAME, get_redis_connection


def create_worker(connection):
    """
    RQ's default Worker uses os.fork() (Unix only).
    On Windows, SimpleWorker runs jobs in-process — required for local dev.
    Linux production (e.g. Render) keeps the fork-based Worker.
    """
    queues = [TRIAGE_QUEUE_NAME]
    if sys.platform == "win32":
        print("[Worker] Windows detected — using SimpleWorker (no fork).")
        return SimpleWorker(queues, connection=connection)
    return Worker(queues, connection=connection)


def main():
    try:
        connection = get_redis_connection()
    except RuntimeError as exc:
        print(f"[Worker] Cannot start: {exc}")
        raise SystemExit(1) from exc

    worker = create_worker(connection)
    print(f"[Worker] Connected to Redis. Listening on queue '{TRIAGE_QUEUE_NAME}'...")
    worker.work()


if __name__ == "__main__":
    main()
