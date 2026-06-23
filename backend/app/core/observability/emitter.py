from __future__ import annotations

import logging
from copy import deepcopy
from time import time
from typing import Any

from app.core.trace_context import reset_job_id, reset_trace_id, set_trace_context
from app.core.trace_events import trace_event


logger = logging.getLogger(__name__)


def emit_event(
    trace_id: str,
    job_id: str,
    event_name: str,
    payload: dict[str, Any] | None = None,
    duration_ms: float | None = None,
    dedupe_key: str | None = None,
) -> dict[str, Any] | None:
    event_payload = {
        "job_id": job_id,
        "trace_id": trace_id,
        **(payload or {}),
    }
    if dedupe_key is not None:
        event_payload["dedupe_key"] = dedupe_key
    start_time = None
    end_time = None
    if duration_ms is not None:
        end_time = time()
        start_time = end_time - (duration_ms / 1000)

    job_token = None
    trace_token = None
    try:
        job_token, trace_token = set_trace_context(job_id, trace_id)
        entry = trace_event(
            event_name,
            event_payload,
            start_time=start_time,
            end_time=end_time,
        )
        if entry is not None:
            persist_job_event(job_id, entry)
        return entry
    except Exception:
        logger.exception("observability_event_emit_failed")
        return None
    finally:
        if job_token is not None:
            reset_job_id(job_token)
        if trace_token is not None:
            reset_trace_id(trace_token)


def persist_job_event(job_id: str, event: dict[str, Any]) -> None:
    """Persist a replayable event copy on the job row.

    Redis/WebSocket delivery is live and best-effort; this DB copy is the
    source used by HTTP replay when the worker and API run in different
    processes.
    """
    if not job_id:
        return
    try:
        from app.db.session import SessionLocal
        from app.models.core import NaturalInputJob

        db = SessionLocal()
        try:
            job = db.query(NaturalInputJob).filter(NaturalInputJob.job_id == job_id).one_or_none()
            if job is None:
                return
            result = dict(job.result or {})
            events = list(result.get("_events") or [])
            event_copy = deepcopy(event)
            if not any(existing.get("event_id") == event_copy.get("event_id") for existing in events):
                events.append(event_copy)
            result["_events"] = sorted(events, key=lambda item: item.get("sequence_number", 0))
            job.result = result
            db.commit()
        finally:
            db.close()
    except Exception:
        logger.debug("job_event_persist_failed", exc_info=True)
