from dataclasses import dataclass
from typing import Any

from app.core.semantic_rules import EVENT_RULES, CanonicalEvent, CanonicalEventType, SemanticRuleEngine
from app.models.core import Worker


class SemanticFirewallError(RuntimeError):
    pass


@dataclass(frozen=True)
class FirewallDecision:
    event: CanonicalEvent
    status: str
    reason: str


class SemanticFirewallService:
    def __init__(self, rule_engine: SemanticRuleEngine | None = None) -> None:
        self.rule_engine = rule_engine or SemanticRuleEngine()

    def validate(
        self,
        event: CanonicalEvent,
        raw_text: str,
        entity_context: list[Worker],
        llm_output: dict[str, Any] | None = None,
    ) -> FirewallDecision:
        self.rule_engine.conflict_detector.validate_or_raise(EVENT_RULES)
        validation = self.rule_engine.validate(event, raw_text, entity_context, llm_output or {})
        if validation.valid:
            return FirewallDecision(event=event, status="PASS", reason=validation.reason)

        if validation.expected_type is None:
            raise SemanticFirewallError(validation.reason)

        fixed = self.rule_engine.reclassify(
            event,
            validation.expected_type,
            raw_text,
            entity_context,
            llm_output or {},
        )
        if fixed.type == CanonicalEventType.NOTE and not self.rule_engine.note_allowed(
            raw_text,
            entity_context,
        ):
            raise SemanticFirewallError("NOTE_EVENT blocked by semantic rule engine")

        return FirewallDecision(
            event=fixed,
            status="FIXED",
            reason=f"reclassified {event.type.value} -> {fixed.type.value}",
        )
