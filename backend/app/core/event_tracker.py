from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from app.core.auth import current_user_id
from app.core.observability_schema import get_event_group
from app.core.trace_context import get_job_id, get_trace_id
from app.models.core import ReconciliationEvent, TraceEvent

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
    "LLM_JSON_PARSE_FAILED": "LLM_JSON_PARSE_FAILED",
    "LLM_LOW_CONFIDENCE": "LLM_LOW_CONFIDENCE",
    "DOMAIN_ROUTED": "DOMAIN_ROUTED",
    "FINANCIAL_MUTATION_RECORDED": "FINANCIAL_MUTATION_RECORDED",
    "FINANCIAL_MISMATCH": "FINANCIAL_MISMATCH",
    "IDEMPOTENCY_COLLISION": "IDEMPOTENCY_COLLISION",
    "RECONCILIATION_COMPLETED": "RECONCILIATION_COMPLETED",
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
    standard = _standard_from_payload(event)
    return {
        "trace_id": event.trace_id,
        "event_type": standard["event_type"],
        "event_name": event.event_name,
        "event_group": event.event_group,
        "event_index": event.event_index,
        "timestamp": event.created_at.isoformat(),
        "created_at": event.created_at.isoformat(),
        "duration_ms": event.duration_ms,
        "domain": standard.get("domain"),
        "stage": standard.get("stage"),
        "user_id": standard.get("user_id"),
        "project_id": standard.get("project_id"),
        "job_id": standard.get("job_id"),
        "input_snapshot": standard.get("input_snapshot"),
        "output_snapshot": standard.get("output_snapshot"),
        "metadata": standard.get("metadata") or {},
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
    standard_payload = build_standard_event_payload(
        trace_id=_trace_id,
        event_type=normalized_name,
        payload=payload or {},
    )
    event_index = _next_event_index(db, _trace_id)
    event_group = get_event_group(normalized_name)
    event = TraceEvent(
        trace_id=_trace_id,
        event_name=normalized_name,
        event_group=event_group,
        event_index=event_index,
        duration_ms=duration_ms,
        payload=standard_payload,
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


def list_recent_traces(
    db: Session | None = None,
    *,
    project_id: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    own_session = db is None
    if own_session:
        from app.db.session import SessionLocal

        db = SessionLocal()
    try:
        statement = (
            select(
                TraceEvent.trace_id,
                func.min(TraceEvent.created_at).label("started_at"),
                func.max(TraceEvent.created_at).label("last_event_at"),
                func.count(TraceEvent.id).label("event_count"),
            )
            .group_by(TraceEvent.trace_id)
            .order_by(desc("last_event_at"))
            .limit(max(1, min(limit, 200)))
        )
        if project_id is not None:
            statement = statement.where(
                TraceEvent.payload["project_id"].as_integer() == project_id
            )
        rows = db.execute(statement).all()
        return [
            {
                "trace_id": row.trace_id,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "last_event_at": row.last_event_at.isoformat() if row.last_event_at else None,
                "event_count": int(row.event_count or 0),
            }
            for row in rows
        ]
    finally:
        if own_session:
            db.close()


def get_trace_anomalies(
    db: Session | None = None,
    *,
    limit: int = 50,
) -> dict[str, list[dict[str, Any]]]:
    own_session = db is None
    if own_session:
        from app.db.session import SessionLocal

        db = SessionLocal()
    try:
        safe_limit = max(1, min(limit, 200))
        events = list(
            db.scalars(
                select(TraceEvent)
                .where(
                    TraceEvent.event_name.in_(
                        [
                            "FINANCIAL_MISMATCH",
                            "IDEMPOTENCY_COLLISION",
                            "LLM_LOW_CONFIDENCE",
                            "LLM_FAILED",
                            "JOB_FAILED",
                            "ERROR_OCCURRED",
                        ]
                    )
                )
                .order_by(TraceEvent.created_at.desc())
                .limit(safe_limit)
            )
        )
        drift_events = list(
            db.scalars(
                select(ReconciliationEvent)
                .where(ReconciliationEvent.drift_detected)
                .order_by(ReconciliationEvent.created_at.desc())
                .limit(safe_limit)
            )
        )
        return {
            "financial_mismatches": [
                _serialize_anomaly(event)
                for event in events
                if event.event_name == "FINANCIAL_MISMATCH"
            ],
            "low_confidence_llm_decisions": [
                _serialize_anomaly(event)
                for event in events
                if event.event_name in {"LLM_LOW_CONFIDENCE", "LLM_FAILED"}
            ],
            "idempotency_collisions": [
                _serialize_anomaly(event)
                for event in events
                if event.event_name == "IDEMPOTENCY_COLLISION"
            ],
            "reconciliation_drift_flags": [
                {
                    "event_id": event.id,
                    "project_id": event.project_id,
                    "created_at": event.created_at.isoformat(),
                    "status": event.status.value,
                    "snapshot": event.snapshot,
                }
                for event in drift_events
            ],
            "pipeline_errors": [
                _serialize_anomaly(event)
                for event in events
                if event.event_name in {"JOB_FAILED", "ERROR_OCCURRED"}
            ],
        }
    finally:
        if own_session:
            db.close()


def build_standard_event_payload(
    *,
    trace_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    legacy_payload = dict(payload or {})
    user_id = current_user_id.get()
    standard = {
        "trace_id": trace_id,
        "event_type": event_type,
        "timestamp": datetime.now(UTC).isoformat(),
        "user_id": str(user_id) if user_id is not None else legacy_payload.get("user_id"),
        "project_id": legacy_payload.get("project_id"),
        "job_id": legacy_payload.get("job_id") or get_job_id(),
        "domain": legacy_payload.get("domain") or _infer_domain(event_type, legacy_payload),
        "stage": legacy_payload.get("stage") or _infer_stage(event_type),
        "input_snapshot": legacy_payload.get("input_snapshot")
        or _infer_input_snapshot(legacy_payload),
        "output_snapshot": legacy_payload.get("output_snapshot")
        or _infer_output_snapshot(legacy_payload),
        "metadata": legacy_payload.get("metadata") or _infer_metadata(legacy_payload),
    }
    return {
        **legacy_payload,
        **{key: value for key, value in standard.items() if value is not None},
        "standard": standard,
    }


def _standard_from_payload(event: TraceEvent) -> dict[str, Any]:
    payload = event.payload or {}
    standard = payload.get("standard")
    if isinstance(standard, dict):
        return {"event_type": event.event_name, **standard}
    return build_standard_event_payload(
        trace_id=event.trace_id,
        event_type=event.event_name,
        payload=payload,
    )["standard"]


def _infer_stage(event_type: str) -> str:
    if (
        event_type.startswith("LLM")
        or "OLLAMA" in event_type
        or event_type == "INTERPRETATION_NORMALIZED"
    ):
        return "LLM"
    if "DOMAIN" in event_type or "ROUTER" in event_type:
        return "ROUTER"
    if event_type.startswith("EXECUTION") or event_type.startswith("FINANCIAL"):
        return "ENGINE"
    if event_type.startswith("DB") or event_type.startswith("PENDING_INTERPRETATION"):
        return "DB"
    if event_type.startswith("JOB"):
        return "WORKER"
    return "DB"


def _infer_domain(event_type: str, payload: dict[str, Any]) -> str | None:
    domain = payload.get("final_domain") or payload.get("detected_domain")
    if isinstance(domain, str):
        return domain
    if (
        "financial" in event_type.lower()
        or payload.get("financial_direction")
        or payload.get("amount")
    ):
        return "FINANCIAL"
    action = str(payload.get("semantic_action") or payload.get("action") or "").upper()
    if action in {"PAYMENT", "PAYMENT_IN", "PAYMENT_OUT", "PURCHASE_PAID", "DEBT_CREATED"}:
        return "FINANCIAL"
    if action in {"WORK_LOG"}:
        return "WORK"
    if action in {"NOTE"}:
        return "NOTE"
    if action:
        return "SETUP"
    return None


def _infer_input_snapshot(payload: dict[str, Any]) -> Any:
    for key in ("input_text", "raw_text", "raw_user_text", "prompt", "chunk_text"):
        if key in payload:
            return payload[key]
    return None


def _infer_output_snapshot(payload: dict[str, Any]) -> Any:
    for key in ("output", "result", "parsed_json", "normalized_result", "raw_llm_output"):
        if key in payload:
            return payload[key]
    return None


def _infer_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    skip = {
        "standard",
        "input_snapshot",
        "output_snapshot",
        "metadata",
        "input_text",
        "raw_text",
        "raw_user_text",
        "prompt",
        "output",
        "result",
        "parsed_json",
        "normalized_result",
        "raw_llm_output",
    }
    return {key: value for key, value in payload.items() if key not in skip}


def _serialize_anomaly(event: TraceEvent) -> dict[str, Any]:
    serialized = _serialize_event(event)
    return {
        "trace_id": serialized["trace_id"],
        "event_type": serialized["event_type"],
        "created_at": serialized["created_at"],
        "project_id": serialized.get("project_id"),
        "job_id": serialized.get("job_id"),
        "metadata": serialized.get("metadata") or {},
    }
