import logging
import time
from collections.abc import Callable
from typing import Any

from app.core.event_tracker import track_event as _db_track_event
from app.core.trace_context import get_trace_id

logger = logging.getLogger(__name__)


def track_event(
    db,
    trace_id: str | None = None,
    event_name: str | None = None,
    payload: dict[str, Any] | None = None,
    duration_ms: float | None = None,
) -> dict[str, Any]:
    try:
        event = _db_track_event(
            db=db,
            trace_id=trace_id,
            event_name=event_name,
            payload=payload,
            duration_ms=duration_ms,
        )
        _publish(event)
        return event
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        logger.debug("observability_track_event_failed", exc_info=True)
        return {}


def track_timed_event(
    db,
    trace_id: str | None = None,
    event_name: str | None = None,
    fn: Callable[[], Any] | None = None,
) -> Any:
    _trace_id = trace_id or get_trace_id() or "unbound"
    start = time.perf_counter()
    try:
        result = fn()
    except BaseException:
        duration_ms = round((time.perf_counter() - start) * 1000, 3)
        event = _db_track_event(
            db=db,
            trace_id=_trace_id,
            event_name=event_name,
            payload={},
            duration_ms=duration_ms,
        )
        _publish(event)
        raise
    duration_ms = round((time.perf_counter() - start) * 1000, 3)
    event = _db_track_event(
        db=db,
        trace_id=_trace_id,
        event_name=event_name,
        payload={},
        duration_ms=duration_ms,
    )
    _publish(event)
    return result


def queue_trace_event(
    db,
    *,
    trace_id: str | None = None,
    event_name: str | None = None,
    payload: dict[str, Any] | None = None,
    duration_ms: float | None = None,
) -> None:
    queued = db.info.setdefault("queued_trace_events", [])
    queued.append(
        {
            "trace_id": trace_id,
            "event_name": event_name,
            "payload": payload or {},
            "duration_ms": duration_ms,
        }
    )


def flush_queued_trace_events(db) -> list[dict[str, Any]]:
    queued = list(db.info.pop("queued_trace_events", []))
    emitted: list[dict[str, Any]] = []
    for item in queued:
        emitted.append(
            track_event(
                db=db,
                trace_id=item.get("trace_id"),
                event_name=item.get("event_name"),
                payload=item.get("payload"),
                duration_ms=item.get("duration_ms"),
            )
        )
    return emitted


def _publish(event: dict[str, Any]) -> None:
    job_id = (event.get("payload") or {}).get("job_id")
    if not job_id:
        return
    try:
        from app.core.job_event_bus import publish_job_event

        publish_job_event(job_id, {
            "sequence_number": event.get("event_index"),
            "event": event.get("event_name"),
            "job_id": job_id,
            "trace_id": event.get("trace_id"),
            "timestamp": event.get("timestamp"),
            "duration_ms": event.get("duration_ms"),
            "payload": event.get("payload", {}),
            "created_at": event.get("timestamp"),
        })
    except Exception:
        logger.debug("event_publish_failed", exc_info=True)
