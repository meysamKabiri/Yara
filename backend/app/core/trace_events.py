from __future__ import annotations

import logging
import traceback
from collections import defaultdict, deque
from enum import StrEnum
from time import perf_counter, time
from typing import Any

from app.core.trace_context import get_trace_id


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


def trace_event(
    event: TraceEvent | str,
    payload: dict[str, Any] | None = None,
    *,
    start_time: float | None = None,
    end_time: float | None = None,
) -> dict[str, Any]:
    trace_id = get_trace_id() or "unbound"
    end = end_time if end_time is not None else perf_counter()
    duration_ms = round((end - start_time) * 1000, 3) if start_time is not None else None
    entry = {
        "trace_id": trace_id,
        "event": event.value if isinstance(event, TraceEvent) else event,
        "payload": payload or {},
        "start_time": start_time,
        "end_time": end if start_time is not None else None,
        "duration_ms": duration_ms,
        "created_at": time(),
    }
    _TRACE_EVENTS[trace_id].append(entry)
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
