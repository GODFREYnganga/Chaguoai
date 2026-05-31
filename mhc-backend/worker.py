from rq import Worker

import triage_tasks  # noqa: F401 - ensure task module is importable by RQ workers
from task_queue import TRIAGE_QUEUE_NAME, get_redis_connection


def main():
    connection = get_redis_connection()
    worker = Worker([TRIAGE_QUEUE_NAME], connection=connection)
    worker.work()


if __name__ == "__main__":
    main()
