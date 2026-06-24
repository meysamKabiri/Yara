OBSERVABILITY_GROUPS: dict[str, list[str]] = {
    "JOB": ["JOB_STARTED", "JOB_COMPLETED", "JOB_FAILED"],
    "DOMAIN_ROUTER": ["DOMAIN_ROUTER_START", "DOMAIN_ROUTER_END"],
    "LLM": ["LLM_STARTED", "LLM_REQUEST_STARTED", "LLM_COMPLETED"],
    "EXECUTION_ENGINE": ["EXECUTION_ENGINE_START", "EXECUTION_ENGINE_END"],
    "DB": ["DB_WRITE_SUCCESS", "DB_WRITE_FAILED"],
}


def get_event_group(event_name: str) -> str:
    for group, events in OBSERVABILITY_GROUPS.items():
        if event_name in events:
            return group
    return "OTHER"
