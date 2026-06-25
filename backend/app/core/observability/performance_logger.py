import logging
from typing import Any


logger = logging.getLogger(__name__)


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
    logger.info(
        "pipeline_performance",
        extra={
            "project_id": project_id,
            "input_text": input_text[:100] if input_text else "",
            "total_request_time_ms": total_duration_ms,
            "llm_latency_ms": shadow_duration_ms,
            "legacy_duration_ms": legacy_duration_ms,
            "governance_evaluation_time_ms": governance_duration_ms,
            "fallback_required": fallback_required,
        },
    )


def latest_performance_events() -> list[dict[str, Any]]:
    return []


def performance_summary() -> dict[str, Any]:
    return {
        "total_samples": 0,
        "average_total_request_time_ms": 0.0,
        "average_llm_latency_ms": 0.0,
        "average_governance_evaluation_time_ms": 0.0,
        "fallback_rate": 0.0,
    }
