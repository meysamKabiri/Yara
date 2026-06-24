from typing import Any

from fastapi import APIRouter

from app.core.event_tracker import get_trace_events as get_observability_events
from app.core.trace_events import get_trace_events


router = APIRouter(tags=["traces"])


@router.get("/traces/{trace_id}")
def read_trace(trace_id: str) -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "events": get_trace_events(trace_id),
        "observability_events": get_observability_events(trace_id),
    }
