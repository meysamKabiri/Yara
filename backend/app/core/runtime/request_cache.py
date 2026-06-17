from dataclasses import dataclass, field
from typing import Any


@dataclass
class RequestCache:
    legacy_result: Any = None
    shadow_result: dict[str, Any] | None = None
    governance_result: dict[str, Any] | None = None
    timings_ms: dict[str, float] = field(default_factory=dict)
    decision_logs: list[dict[str, Any]] = field(default_factory=list)

    def get_legacy_result(self) -> Any:
        return self.legacy_result

    def set_legacy_result(self, value: Any) -> Any:
        self.legacy_result = value
        return value

    def get_shadow_result(self) -> dict[str, Any] | None:
        return self.shadow_result

    def set_shadow_result(self, value: dict[str, Any]) -> dict[str, Any]:
        self.shadow_result = value
        return value

    def get_governance_result(self) -> dict[str, Any] | None:
        return self.governance_result

    def set_governance_result(self, value: dict[str, Any]) -> dict[str, Any]:
        self.governance_result = value
        return value

    def set_timing(self, key: str, value_ms: float) -> None:
        self.timings_ms[key] = value_ms

    def add_decision_log(self, payload: dict[str, Any]) -> None:
        self.decision_logs.append(payload)


def new_request_cache() -> RequestCache:
    return RequestCache()
