from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.observability_schema import get_event_group
from app.core.trace_context import get_trace_id
from app.models.core import TraceEvent

_EVENT_NAME_MAP: dict[str, str] = {
    "db.job_created": "JOB_CREATED",
    "db.job_enqueued": "JOB_ENQUEUED",
    "db.job_enqueue_failed": "JOB_ENQUEUE_FAILED",
    "db.project_created": "PROJECT_CREATED",
    "db.entity_resolved": "ENTITY_RESOLVED",
    "db.interpretation_confirmed": "INTERPRETATION_CONFIRMED",
    "db.confirmation_failed": "CONFIRMATION_FAILED",
    "job.started": "JOB_STARTED",
    "job.llm_failed": "LLM_FAILED",
    "job.completed": "JOB_COMPLETED",
    "job.failed": "JOB_FAILED",
    "llm_v2_interpreter.interpret": "LLM_INTERPRETER_STARTED",
    "execution_engine.execute": "EXECUTION_STARTED",
    "domain_router.route": "DOMAIN_ROUTER_START",
    "PENDING_INTERPRETATION_SAVED": "PENDING_INTERPRETATION_SAVED",
    "MULTI_EVENT_SPLIT_APPLIED": "MULTI_EVENT_SPLIT_APPLIED",
    "INTERPRETATION_NORMALIZED": "INTERPRETATION_NORMALIZED",
    "LLM_REQUEST_STARTED": "LLM_REQUEST_STARTED",
    "LLM_RETRY": "LLM_RETRY",
    "OLLAMA_RESPONSE_RECEIVED": "OLLAMA_RESPONSE_RECEIVED",
    "LLM_JSON_PARSED": "LLM_JSON_PARSED",
    "DOMAIN_ROUTED": "DOMAIN_ROUTED",
}


def normalize_event_name(event_name: str | None) -> str:
    if not event_name:
        return "UNKNOWN"
    canonical = _EVENT_NAME_MAP.get(event_name)
    if canonical:
        return canonical
    return event_name.upper().replace(".", "_")


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
    normalized_name = normalize_event_name(event_name)
    event_index = _next_event_index(db, _trace_id)
    event_group = get_event_group(normalized_name)
    event = TraceEvent(
        trace_id=_trace_id,
        event_name=normalized_name,
        event_group=event_group,
        event_index=event_index,
        duration_ms=duration_ms,
        payload=payload or {},
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return _serialize_event(event)


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
