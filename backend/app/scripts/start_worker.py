import os

from rq import Worker

from app.core.logger import configure_logging, log_event
from app.core.trace_context import get_trace_id, new_trace_id, reset_trace_id, set_trace_id


class _TraceWorker(Worker):
    def perform_job(self, job, *args, **kwargs):
        trace_id = job.meta.get("trace_id") if job.meta else None
        trace_id = trace_id or new_trace_id()
        token = set_trace_id(trace_id)
        log_event(event="worker.job_start", payload={"job_id": job.id, "trace_id": trace_id})
        try:
            return super().perform_job(job, *args, **kwargs)
        finally:
            reset_trace_id(token)


def wait_for_redis() -> None:
    from redis import Redis

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    attempt = 0
    while True:
        try:
            conn = Redis.from_url(redis_url, socket_connect_timeout=5, socket_timeout=5)
            conn.ping()
            log_event(event="worker.redis_connected", message="Connected to Redis", payload={"url": redis_url})
            conn.close()
            return
        except Exception as e:
            attempt += 1
            delay = min(0.5 * (2**attempt), 30.0)
            log_event(
                event="worker.redis_unavailable",
                message="Redis unavailable, retrying...",
                payload={"attempt": attempt, "delay": delay, "error": str(e)},
            )
            import time

            time.sleep(delay)


def main() -> None:
    configure_logging()
    log_event(event="worker.starting", message="Starting RQ worker")

    from redis import Redis

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    queues = os.getenv("RQ_QUEUES", "llm_tasks").split(",")

    wait_for_redis()

    conn = Redis.from_url(redis_url, socket_connect_timeout=5, socket_timeout=5)
    log_event(event="worker.ready", message="Worker starting", payload={"queues": queues})
    worker = _TraceWorker(queues, connection=conn)
    worker.work()


if __name__ == "__main__":
    main()
