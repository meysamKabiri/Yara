import logging
import os
import time

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
_redis_connection = None


def get_redis_connection():
    global _redis_connection
    if _redis_connection is not None:
        try:
            _redis_connection.ping()
            return _redis_connection
        except Exception:
            logger.warning("Redis connection lost, reconnecting...")
            _redis_connection = None

    attempt = 0
    while True:
        try:
            from redis import Redis

            conn = Redis.from_url(
                REDIS_URL, socket_connect_timeout=5, socket_timeout=5
            )
            conn.ping()
            _redis_connection = conn
            logger.info("Redis connection established")
            return conn
        except Exception as e:
            attempt += 1
            delay = min(0.5 * (2**attempt), 30.0)
            logger.warning(
                "Redis unavailable (attempt %d): %s. Retrying in %.1fs...",
                attempt,
                e,
                delay,
            )
            time.sleep(delay)


def get_queue():
    from rq import Queue

    return Queue(
        "llm_tasks", connection=get_redis_connection(), default_timeout=600
    )


def get_job(job_id: str):
    from rq.job import Job

    return Job.fetch(job_id, connection=get_redis_connection())
