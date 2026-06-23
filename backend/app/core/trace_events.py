from __future__ import annotations

import logging
import traceback
from collections import defaultdict, deque
from enum import StrEnum
from time import perf_counter, time
from typing import Any
from uuid import uuid4

from app.core.trace_context import get_job_id, get_trace_id


logger = logging.getLogger(__name__)


class TraceEvent(StrEnum):
    DOMAIN_ROUTED = "DOMAIN_ROUTED"
    ENTITY_RESOLVED = "ENTITY_RESOLVED"
    EXECUTION_STARTED = "EXECUTION_STARTED"
    EXECUTION_COMPLETED = "EXECUTION_COMPLETED"
    DB_WRITE_SUCCESS = "DB_WRITE_SUCCESS"
    SHADOW_COMPARISON_DONE = "SHADOW_COMPARISON_DONE"
    ERROR_OCCURRED = "ERROR_OCCURRED"


_TRACE_EVENTS: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=200))
_TRACE_SEQUENCES: dict[str, int] = defaultdict(int)
_TRACE_DEDUPE_KEYS: dict[str, set[str]] = defaultdict(set)


def trace_event(
    event: TraceEvent | str,
    payload: dict[str, Any] | None = None,
    *,
    start_time: float | None = None,
    end_time: float | None = None,
) -> dict[str, Any]:
    trace_id = get_trace_id() or "unbound"
    job_id = get_job_id()
    event_name = event.value if isinstance(event, TraceEvent) else event
    event_payload = dict(payload or {})
    entry_job_id = str(event_payload.pop("job_id", job_id or ""))
    entry_trace_id = str(event_payload.pop("trace_id", trace_id))
    if entry_job_id:
        event_payload["job_id"] = entry_job_id
    event_payload["trace_id"] = entry_trace_id
    dedupe_key = event_payload.pop("dedupe_key", None)
    if dedupe_key is not None:
        normalized_key = f"{event_name}:{dedupe_key}"
        if normalized_key in _TRACE_DEDUPE_KEYS[entry_trace_id]:
            return _TRACE_EVENTS[entry_trace_id][-1]
        _TRACE_DEDUPE_KEYS[entry_trace_id].add(normalized_key)
    end = end_time if end_time is not None else perf_counter()
    duration_ms = round((end - start_time) * 1000, 3) if start_time is not None else None
    _TRACE_SEQUENCES[entry_trace_id] += 1
    entry = {
        "event_id": str(uuid4()),
        "sequence_number": _TRACE_SEQUENCES[entry_trace_id],
        "event": event_name,
        "job_id": entry_job_id,
        "trace_id": entry_trace_id,
        "timestamp": time(),
        "duration_ms": duration_ms,
        "payload": event_payload,
        "start_time": start_time,
        "end_time": end if start_time is not None else None,
        "created_at": time(),
    }
    _TRACE_EVENTS[entry_trace_id].append(entry)
    if entry_job_id:
        try:
            from app.core.job_event_bus import publish_job_event

            publish_job_event(entry_job_id, entry)
        except Exception:
            logger.debug("trace_event_publish_failed", exc_info=True)
    logger.info(
        "trace_event: %s",
        entry["event"],
        extra={
            "trace_event": entry["event"],
            "trace_payload": entry["payload"],
            "duration_ms": duration_ms,
        },
    )
    return entry


def trace_error(error: BaseException, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = {
        **(payload or {}),
        "error_message": str(error),
        "stack_trace": "".join(traceback.format_exception(type(error), error, error.__traceback__, limit=6)),
    }
    return trace_event(TraceEvent.ERROR_OCCURRED, merged)


def get_trace_events(trace_id: str) -> list[dict[str, Any]]:
    return list(_TRACE_EVENTS.get(trace_id) or [])
