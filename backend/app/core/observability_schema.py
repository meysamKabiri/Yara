OBSERVABILITY_GROUPS: dict[str, list[str]] = {
    "JOB": [
        "JOB_CREATED",
        "JOB_STARTED",
        "JOB_COMPLETED",
        "JOB_FAILED",
        "JOB_ENQUEUED",
        "JOB_ENQUEUE_FAILED",
        "JOB_EXPIRED",
    ],
    "LLM": [
        "LLM_STARTED",
        "LLM_REQUEST_STARTED",
        "LLM_COMPLETED",
        "LLM_INTERPRETER_STARTED",
        "LLM_FAILED",
        "LLM_RETRY",
        "OLLAMA_RESPONSE_RECEIVED",
        "LLM_JSON_PARSED",
        "LLM_JSON_PARSE_FAILED",
        "LLM_LOW_CONFIDENCE",
    ],
    "PIPELINE": [
        "DOMAIN_ROUTER_START",
        "DOMAIN_ROUTED",
        "EXECUTION_STARTED",
        "EXECUTION_COMPLETED",
        "INTERPRETATION_NORMALIZED",
        "INTERPRETATION_CONFIRMED",
        "CONFIRMATION_FAILED",
        "ENTITY_RESOLVED",
        "PENDING_INTERPRETATION_SAVED",
        "MULTI_EVENT_SPLIT_APPLIED",
        "MULTI_EVENT_CHUNK_PROCESSED",
        "FINANCIAL_MUTATION_RECORDED",
        "FINANCIAL_MISMATCH",
        "IDEMPOTENCY_COLLISION",
        "RECONCILIATION_COMPLETED",
    ],
    "DB": [
        "DB_WRITE_SUCCESS",
        "DB_WRITE_FAILED",
        "PROJECT_CREATED",
    ],
}


def get_event_group(event_name: str) -> str:
    for group, events in OBSERVABILITY_GROUPS.items():
        if event_name in events:
            return group
    return "OTHER"
