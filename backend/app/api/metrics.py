from typing import Any

from fastapi import APIRouter

from app.core.event_tracker import get_trace_events
from app.core.observability_validator import observability_health_summary

router = APIRouter(tags=["metrics"])


@router.get("/metrics/trace/{trace_id}")
def read_trace_metrics(trace_id: str) -> dict[str, Any]:
    events = get_trace_events(trace_id)
    total_duration_ms = sum(e["duration_ms"] or 0 for e in events)
    return {
        "trace_id": trace_id,
        "total_duration_ms": total_duration_ms,
        "events": events,
    }


@router.get("/metrics/health/observability")
def observability_health() -> dict[str, Any]:
    return observability_health_summary()
