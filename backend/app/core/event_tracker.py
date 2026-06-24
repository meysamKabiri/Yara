from __future__ import annotations

import time
from typing import Any, Callable, TypeVar

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.observability_schema import get_event_group
from app.core.trace_context import get_trace_id
from app.models.core import TraceEvent

F = TypeVar("F", bound=Callable[..., Any])

_NEXT_EVENT_INDEX = text("SELECT next_trace_event_index(:trace_id)")


def _next_event_index(db: Session, trace_id: str) -> int:
    return db.execute(_NEXT_EVENT_INDEX, {"trace_id": trace_id}).scalar_one()


def _serialize_event(event: TraceEvent) -> dict[str, Any]:
    return {
        "trace_id": event.trace_id,
        "event_name": event.event_name,
        "event_group": event.event_group,
        "event_index": event.event_index,
        "timestamp": event.created_at.isoformat(),
        "duration_ms": event.duration_ms,
        "payload": event.payload or {},
    }


def track_event(
    db: Session,
    trace_id: str | None = None,
    event_name: str | None = None,
    payload: dict[str, Any] | None = None,
    duration_ms: float | None = None,
) -> dict[str, Any]:
    _trace_id = trace_id or get_trace_id() or "unbound"
    event_index = _next_event_index(db, _trace_id)
    event_group = get_event_group(event_name)
    event = TraceEvent(
        trace_id=_trace_id,
        event_name=event_name,
        event_group=event_group,
        event_index=event_index,
        duration_ms=duration_ms,
        payload=payload or {},
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return _serialize_event(event)


def track_timed_event(
    db: Session,
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
        event_index = _next_event_index(db, _trace_id)
        event_group = get_event_group(event_name)
        db.add(TraceEvent(
            trace_id=_trace_id,
            event_name=event_name,
            event_group=event_group,
            event_index=event_index,
            duration_ms=duration_ms,
            payload={},
        ))
        db.commit()
        raise

    duration_ms = round((time.perf_counter() - start) * 1000, 3)
    event_index = _next_event_index(db, _trace_id)
    event_group = get_event_group(event_name)
    db.add(TraceEvent(
        trace_id=_trace_id,
        event_name=event_name,
        event_group=event_group,
        event_index=event_index,
        duration_ms=duration_ms,
        payload={},
    ))
    db.commit()
    return result


def get_trace_events(trace_id: str, db: Session | None = None) -> list[dict[str, Any]]:
    own_session = db is None
    if own_session:
        from app.db.session import SessionLocal

        db = SessionLocal()
    try:
        events = (
            db.query(TraceEvent)
            .filter(TraceEvent.trace_id == trace_id)
            .order_by(TraceEvent.event_index)
            .all()
        )
        return [_serialize_event(e) for e in events]
    finally:
        if own_session:
            db.close()
