from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RuleTrace:
    rule_id: str
    event_type: str
    priority: int
    matched_signals: list[str] = field(default_factory=list)
    confidence: float = 0.0


class SemanticExplainabilityService:
    def explain(
        self,
        *,
        event_type: str,
        confidence: float,
        rule_traces: list[RuleTrace],
        rejected_rules: list[dict[str, str]],
    ) -> dict[str, Any]:
        selected = next((trace for trace in rule_traces if trace.event_type == event_type), None)
        triggered_rule = selected.rule_id if selected is not None else f"{event_type}_FALLBACK"
        matched_signals = selected.matched_signals if selected is not None else []

        decision_path = ["LLM output parsed"]
        if selected is None:
            decision_path.append("no semantic rule matched")
            decision_path.append(f"event classified as {event_type}")
        else:
            decision_path.append(f"rule {triggered_rule} matched")
            decision_path.append("priority resolved")
            decision_path.append(f"event classified as {event_type}")

        return {
            "event_type": event_type,
            "confidence": confidence,
            "triggered_rule": triggered_rule,
            "matched_signals": matched_signals,
            "rejected_rules": rejected_rules,
            "decision_path": decision_path,
        }

    def attach_to_event_metadata(
        self,
        metadata: dict[str, Any],
        explanation: dict[str, Any],
        conflict_warnings: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        updated = dict(metadata)
        updated["semantic_explanation"] = explanation
        updated["rule_id"] = explanation.get("triggered_rule")
        updated["conflict_warnings"] = conflict_warnings or []
        return updated
