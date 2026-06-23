from __future__ import annotations

import json
import logging
from typing import Any

from app.core.queue import get_redis_connection


logger = logging.getLogger(__name__)


def job_event_channel(job_id: str) -> str:
    return f"job_events:{job_id}"


def publish_job_event(job_id: str, event: dict[str, Any]) -> None:
    try:
        payload = json.dumps(event, ensure_ascii=False, default=str)
        get_redis_connection().publish(job_event_channel(job_id), payload)
    except Exception:
        logger.debug("job_event_publish_failed", extra={"job_id": job_id}, exc_info=True)


def subscribe_job_events(job_id: str):
    pubsub = get_redis_connection().pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(job_event_channel(job_id))
    return pubsub


def read_job_event(pubsub, *, timeout: float = 1.0) -> dict[str, Any] | None:
    message = pubsub.get_message(timeout=timeout)
    if not message or message.get("type") != "message":
        return None
    data = message.get("data")
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    if not data:
        return None
    return json.loads(data)


def close_job_event_subscription(pubsub, job_id: str) -> None:
    try:
        pubsub.unsubscribe(job_event_channel(job_id))
    except Exception:
        logger.debug("job_event_unsubscribe_failed", extra={"job_id": job_id}, exc_info=True)
    try:
        pubsub.close()
    except Exception:
        logger.debug("job_event_pubsub_close_failed", extra={"job_id": job_id}, exc_info=True)
