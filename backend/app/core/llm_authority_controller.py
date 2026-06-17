import random
from typing import Any

from app.core.feature_flags import FinancialMigrationMode
from app.core.validation.financial_validator import (
    decimal_or_none,
    legacy_has_resolved_entity,
)
from app.services.compare_legacy_vs_shadow import compare_legacy_vs_shadow


class LLMAuthorityController:
    def decide(
        self,
        *,
        unified_pipeline_context: dict[str, Any],
        shadow_result: dict[str, Any],
        legacy_result: dict[str, Any] | list[dict[str, Any]],
        migration_mode: FinancialMigrationMode | str,
        analytics_signals: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        mode = _mode(migration_mode)
        event_type = str(unified_pipeline_context.get("event_type") or "")
        diff = compare_legacy_vs_shadow(legacy_result, shadow_result)
        analytics = analytics_signals if isinstance(analytics_signals, dict) else {}

        override_reason = _safety_override_reason(shadow_result, diff, analytics)
        if override_reason is not None:
            return _decision("LEGACY", True, override_reason, _confidence(shadow_result))

        if mode == FinancialMigrationMode.OFF:
            return _decision("LEGACY", False, "Financial migration is OFF", 1.0)
        if mode == FinancialMigrationMode.SHADOW_ONLY:
            return _decision("LEGACY", False, "Shadow-only mode keeps legacy primary", 1.0)
        if mode == FinancialMigrationMode.A_B_TEST:
            if random.random() < 0.5:
                return _decision("LEGACY", False, "A/B authority selected legacy", 0.5)
            return _decision("LLM", False, "A/B authority selected LLM", 0.5)

        if event_type == "FINANCIAL_EVENT":
            return _financial_decision(shadow_result, legacy_result)
        if event_type == "WORK_EVENT":
            return _work_decision(shadow_result, analytics)
        if event_type == "SETUP_EVENT":
            return _setup_decision(shadow_result, analytics)
        return _decision("LEGACY", False, "Unsupported event type for LLM authority", 1.0)


def _financial_decision(
    shadow_result: dict[str, Any],
    legacy_result: dict[str, Any] | list[dict[str, Any]],
) -> dict[str, Any]:
    confidence = _confidence(shadow_result)
    financial = (
        shadow_result.get("financial")
        if isinstance(shadow_result.get("financial"), dict)
        else {}
    )
    if (
        confidence >= 0.90
        and _shadow_has_entity(shadow_result)
        and legacy_has_resolved_entity(legacy_result)
        and decimal_or_none(financial.get("amount")) is not None
    ):
        return _decision(
            "LLM",
            False,
            "LLM financial confidence/entity/amount checks passed",
            confidence,
        )
    return _decision("LEGACY", True, "LLM financial authority checks failed", confidence)


def _work_decision(shadow_result: dict[str, Any], analytics: dict[str, Any]) -> dict[str, Any]:
    confidence = _confidence(shadow_result)
    work = shadow_result.get("work") if isinstance(shadow_result.get("work"), dict) else {}
    entity_accuracy = _analytics_accuracy(analytics, "entity")
    if entity_accuracy > 0.90 and work.get("quantity") is not None:
        return _decision(
            "LLM",
            False,
            "LLM work entity accuracy and quantity checks passed",
            confidence,
        )
    return _decision("LEGACY", True, "LLM work authority checks failed", confidence)


def _setup_decision(shadow_result: dict[str, Any], analytics: dict[str, Any]) -> dict[str, Any]:
    confidence = _confidence(shadow_result)
    entity_accuracy = _analytics_accuracy(analytics, "entity")
    if entity_accuracy > 0.92 and _shadow_has_entity(shadow_result):
        return _decision("LLM", False, "LLM setup entity extraction is stable", confidence)
    return _decision("LEGACY", True, "LLM setup authority checks failed", confidence)


def _safety_override_reason(
    shadow_result: dict[str, Any],
    diff: dict[str, bool],
    analytics: dict[str, Any],
) -> str | None:
    if shadow_result.get("ambiguity") is True:
        return "Safety override: shadow ambiguity flag is set"
    if diff.get("amount_match") is False:
        return "Safety override: amount conflict detected"
    for risk in analytics.get("risk_areas", []):
        if (
            isinstance(risk, dict)
            and risk.get("severity") == "HIGH"
            and "Entity mismatch" in str(risk.get("issue", ""))
        ):
            return "Safety override: entity mismatch risk is HIGH"
    return None


def _decision(
    primary_source: str,
    fallback_required: bool,
    reason: str,
    confidence: float,
) -> dict[str, Any]:
    return {
        "primary_source": primary_source,
        "fallback_required": fallback_required,
        "reason": reason,
        "confidence": confidence,
    }


def _mode(value: FinancialMigrationMode | str) -> FinancialMigrationMode:
    if isinstance(value, FinancialMigrationMode):
        return value
    try:
        return FinancialMigrationMode(value)
    except ValueError:
        return FinancialMigrationMode.OFF


def _confidence(shadow_result: dict[str, Any]) -> float:
    confidence = shadow_result.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, int | float):
        return 0.0
    return max(0.0, min(float(confidence), 1.0))


def _shadow_has_entity(shadow_result: dict[str, Any]) -> bool:
    entities = shadow_result.get("entities")
    return isinstance(entities, list) and any(
        isinstance(entity, dict) and entity.get("name") for entity in entities
    )


def _analytics_accuracy(analytics: dict[str, Any], key: str) -> float:
    accuracy = analytics.get("accuracy")
    if not isinstance(accuracy, dict):
        return 0.0
    value = accuracy.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return float(value)
