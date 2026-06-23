import os

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")


def get_redis_connection():
    from redis import Redis

    return Redis.from_url(redis_url)


def get_queue():
    from rq import Queue

    return Queue("llm_tasks", connection=get_redis_connection(), default_timeout=600)


def get_job(job_id: str):
    from rq.job import Job

    return Job.fetch(job_id, connection=get_redis_connection())
