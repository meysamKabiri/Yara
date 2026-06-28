from collections import Counter
from typing import Any

from app.core.event_tracker import get_trace_events
from app.core.observability_schema import OBSERVABILITY_GROUPS

REQUIRED_PIPELINE_STAGES: dict[str, list[str]] = {
    "JOB": ["JOB_CREATED", "JOB_STARTED"],
    "LLM": ["LLM_STARTED"],
    "COMPLETION": ["LLM_COMPLETED", "EXECUTION_COMPLETED", "JOB_COMPLETED"],
    "FAILURE": ["LLM_FAILED", "ERROR_OCCURRED", "JOB_FAILED"],
}


def validate_trace(trace_id: str, db: Any = None) -> dict[str, Any]:
    events = get_trace_events(trace_id, db=db)
    event_names_present = {e["event_name"] for e in events}
    indices = sorted(e["event_index"] for e in events)
    name_count = Counter(e["event_name"] for e in events)

    gaps: list[int] = []
    duplicates: list[int] = []
    prev = None
    for idx in indices:
        if idx == prev:
            duplicates.append(idx)
        elif prev is not None and idx != prev + 1:
            for missing in range(prev + 1, idx):
                gaps.append(missing)
        prev = idx

    groups: dict[str, int] = Counter()
    for e in events:
        groups[e["event_group"]] += 1

    errors: list[str] = []
    if gaps:
        errors.append(f"event_index gaps at: {gaps}")
    if duplicates:
        errors.append(f"duplicate event_index: {duplicates}")

    return {
        "trace_id": trace_id,
        "valid": len(errors) == 0,
        "event_count": len(events),
        "unique_event_names": len(name_count),
        "first_index": indices[0] if indices else None,
        "last_index": indices[-1] if indices else None,
        "gaps": gaps,
        "duplicates": duplicates,
        "groups": dict(groups),
        "event_name_counts": dict(name_count),
        "errors": errors,
    }


def validate_all_traces(db: Any = None) -> list[dict[str, Any]]:
    from app.db.session import SessionLocal
    from app.models.core import TraceEvent

    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        trace_ids = [
            row[0]
            for row in db.query(TraceEvent.trace_id).distinct().all()
        ]
        results = []
        for trace_id in trace_ids:
            results.append(validate_trace(trace_id, db=db))
        return results
    finally:
        if own_session:
            db.close()


def observability_health_summary(db: Any = None) -> dict[str, Any]:
    from app.db.session import SessionLocal
    from app.models.core import TraceEvent

    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        total_traces = (
            db.query(TraceEvent.trace_id)
            .distinct()
            .count()
        )
        total_events = db.query(TraceEvent).count()
    finally:
        if own_session:
            db.close()

    if total_traces == 0:
        return {
            "status": "ok",
            "total_traces": 0,
            "total_events": 0,
            "broken_traces": 0,
            "last_issues": [],
        }

    results = validate_all_traces(db=db)
    broken = [r for r in results if not r["valid"]]
    last_issues = []
    for r in broken[-5:]:
        last_issues.append({
            "trace_id": r["trace_id"],
            "errors": r["errors"],
        })

    return {
        "status": "ok" if not broken else "degraded",
        "total_traces": total_traces,
        "total_events": total_events,
        "broken_traces": len(broken),
        "last_issues": last_issues,
    }
