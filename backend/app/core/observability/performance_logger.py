from collections import deque
from typing import Any

MAX_PERFORMANCE_EVENTS = 500
_PERFORMANCE_EVENTS: deque[dict[str, Any]] = deque(maxlen=MAX_PERFORMANCE_EVENTS)


def record_pipeline_performance(
    *,
    project_id: int,
    input_text: str,
    total_duration_ms: float,
    legacy_duration_ms: float,
    shadow_duration_ms: float,
    governance_duration_ms: float,
    fallback_required: bool,
) -> None:
    _PERFORMANCE_EVENTS.append(
        {
            "project_id": project_id,
            "input_text": input_text,
            "total_request_time_ms": total_duration_ms,
            "llm_latency_ms": shadow_duration_ms,
            "legacy_duration_ms": legacy_duration_ms,
            "governance_evaluation_time_ms": governance_duration_ms,
            "fallback_required": fallback_required,
        }
    )


def latest_performance_events() -> list[dict[str, Any]]:
    return list(_PERFORMANCE_EVENTS)


def performance_summary() -> dict[str, Any]:
    total = len(_PERFORMANCE_EVENTS)
    if total == 0:
        return {
            "total_samples": 0,
            "average_total_request_time_ms": 0.0,
            "average_llm_latency_ms": 0.0,
            "average_governance_evaluation_time_ms": 0.0,
            "fallback_rate": 0.0,
        }
    return {
        "total_samples": total,
        "average_total_request_time_ms": _average("total_request_time_ms"),
        "average_llm_latency_ms": _average("llm_latency_ms"),
        "average_governance_evaluation_time_ms": _average("governance_evaluation_time_ms"),
        "fallback_rate": sum(1 for item in _PERFORMANCE_EVENTS if item["fallback_required"])
        / total,
    }


def _average(key: str) -> float:
    return sum(float(item[key]) for item in _PERFORMANCE_EVENTS) / len(_PERFORMANCE_EVENTS)
