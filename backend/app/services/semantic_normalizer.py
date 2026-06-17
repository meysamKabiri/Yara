from typing import Any

from app.core.semantic_rules import CanonicalEvent, CanonicalEventType, SemanticRuleEngine
from app.models.core import Worker


class SemanticNormalizerService:
    def __init__(self, rule_engine: SemanticRuleEngine | None = None) -> None:
        self.rule_engine = rule_engine or SemanticRuleEngine()

    def normalize(
        self,
        llm_output: dict[str, Any],
        raw_text: str,
        entity_context: list[Worker],
    ) -> CanonicalEvent:
        return self.rule_engine.classify(llm_output, raw_text, entity_context)


__all__ = ["CanonicalEvent", "CanonicalEventType", "SemanticNormalizerService"]
