import random
from typing import Any

from sqlalchemy.orm import Session

from app.core.feature_flags import FinancialMigrationMode
from app.core.validation.financial_validator import (
    decimal_or_none,
    financial_decision_ready,
    financial_outputs_match,
    legacy_has_resolved_entity,
    shadow_financial_unsafe_reason,
)
from app.services.compare_legacy_vs_shadow import compare_legacy_vs_shadow
from app.services.shadow_analytics_service import ShadowAnalyticsService
from app.services.shadow_migration_decision_engine import MigrationDecisionEngine


class UnifiedGovernanceEngine:
    def __init__(self, db: Session | None = None) -> None:
        self.db = db

    def evaluate(self, context: dict[str, Any]) -> dict[str, Any]:
        legacy_result = context["legacy_result"]
        shadow_result = context["shadow_result"]
        event_type = str(context.get("event_type") or "")
        mode = _mode(context.get("migration_mode", FinancialMigrationMode.OFF))
        decision_engine_output = self._decision_engine_output(context)
        analytics_signals = self._analytics_signals(context, decision_engine_output)
        diff = compare_legacy_vs_shadow(legacy_result, shadow_result)
        confidence = _confidence(shadow_result)

        override_reason = _safety_override_reason(shadow_result, diff, analytics_signals)
        if override_reason is not None:
            return _governance_decision("LEGACY", True, "HIGH", override_reason, confidence)

        if mode == FinancialMigrationMode.OFF:
            return _governance_decision("LEGACY", False, "LOW", "Financial migration is OFF", 1.0)
        if mode == FinancialMigrationMode.SHADOW_ONLY:
            return _governance_decision(
                "LEGACY",
                False,
                "LOW",
                "Shadow-only mode keeps legacy primary",
                1.0,
            )
        if mode == FinancialMigrationMode.A_B_TEST:
            if random.random() < 0.5:
                return _governance_decision(
                    "LEGACY",
                    False,
                    "LOW",
                    "A/B authority selected legacy",
                    0.5,
                )
            return self._llm_with_safety(
                legacy_result,
                shadow_result,
                decision_engine_output,
                "A/B authority selected LLM",
                confidence,
            )

        if event_type == "FINANCIAL_EVENT":
            if _financial_llm_ready(shadow_result, legacy_result):
                return self._llm_with_safety(
                    legacy_result,
                    shadow_result,
                    decision_engine_output,
                    "LLM financial confidence/entity/amount checks passed",
                    confidence,
                )
            return _governance_decision(
                "LEGACY",
                True,
                "MEDIUM",
                "LLM financial authority checks failed",
                confidence,
            )

        if event_type == "WORK_EVENT":
            return _work_decision(shadow_result, analytics_signals)
        if event_type == "SETUP_EVENT":
            return _setup_decision(shadow_result, analytics_signals)
        return _governance_decision(
            "LEGACY",
            False,
            "LOW",
            "Unsupported event type for LLM governance",
            1.0,
        )

    def _llm_with_safety(
        self,
        legacy_result: dict[str, Any] | list[dict[str, Any]],
        shadow_result: dict[str, Any],
        decision_engine_output: dict[str, Any] | None,
        default_reason: str,
        confidence: float,
    ) -> dict[str, Any]:
        diff = compare_legacy_vs_shadow(legacy_result, shadow_result)
        if not financial_outputs_match(diff):
            return _governance_decision(
                "LEGACY",
                True,
                "HIGH",
                "Safety override: legacy/shadow mismatch",
                confidence,
            )
        if not financial_decision_ready(decision_engine_output):
            return _governance_decision(
                "LEGACY",
                True,
                "MEDIUM",
                "Decision engine has not marked financial ready",
                confidence,
            )
        if not legacy_has_resolved_entity(legacy_result):
            return _governance_decision(
                "LEGACY",
                True,
                "MEDIUM",
                "Shadow fallback: entity is not resolved",
                confidence,
            )
        unsafe_reason = shadow_financial_unsafe_reason(shadow_result)
        if unsafe_reason is not None:
            return _governance_decision("LEGACY", True, "MEDIUM", unsafe_reason, confidence)
        reason = (
            "LLM financial safety checks passed"
            if default_reason != "A/B authority selected LLM"
            else default_reason
        )
        return _governance_decision("LLM", False, "LOW", reason, confidence)

    def _decision_engine_output(self, context: dict[str, Any]) -> dict[str, Any] | None:
        if isinstance(context.get("decision_engine_output"), dict):
            return context["decision_engine_output"]
        if self.db is None:
            return None
        return MigrationDecisionEngine(self.db).recommendation()

    def _analytics_signals(
        self,
        context: dict[str, Any],
        decision_engine_output: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if isinstance(context.get("analytics_signals"), dict):
            return context["analytics_signals"]
        if self.db is None:
            return {}
        return {
            **ShadowAnalyticsService(self.db).summary(),
            "risk_areas": (
                decision_engine_output.get("risk_areas", [])
                if isinstance(decision_engine_output, dict)
                else []
            ),
        }


def _governance_decision(
    primary_source: str,
    fallback_required: bool,
    risk_level: str,
    reason: str,
    confidence: float,
) -> dict[str, Any]:
    return {
        "primary_source": primary_source,
        "fallback_required": fallback_required,
        "risk_level": risk_level,
        "reason": reason,
        "confidence": confidence,
    }


def _mode(value: FinancialMigrationMode | str) -> FinancialMigrationMode:
    if isinstance(value, FinancialMigrationMode):
        return value
    try:
        return FinancialMigrationMode(str(value))
    except ValueError:
        return FinancialMigrationMode.OFF


def _financial_llm_ready(
    shadow_result: dict[str, Any],
    legacy_result: dict[str, Any] | list[dict[str, Any]],
) -> bool:
    financial = (
        shadow_result.get("financial")
        if isinstance(shadow_result.get("financial"), dict)
        else {}
    )
    return (
        _confidence(shadow_result) >= 0.90
        and _shadow_has_entity(shadow_result)
        and legacy_has_resolved_entity(legacy_result)
        and decimal_or_none(financial.get("amount")) is not None
    )


def _work_decision(shadow_result: dict[str, Any], analytics: dict[str, Any]) -> dict[str, Any]:
    confidence = _confidence(shadow_result)
    work = shadow_result.get("work") if isinstance(shadow_result.get("work"), dict) else {}
    entity_accuracy = _analytics_accuracy(analytics, "entity")
    if entity_accuracy > 0.90 and work.get("quantity") is not None:
        return _governance_decision(
            "LLM",
            False,
            "LOW",
            "LLM work entity accuracy and quantity checks passed",
            confidence,
        )
    return _governance_decision(
        "LEGACY",
        True,
        "MEDIUM",
        "LLM work authority checks failed",
        confidence,
    )


def _setup_decision(shadow_result: dict[str, Any], analytics: dict[str, Any]) -> dict[str, Any]:
    confidence = _confidence(shadow_result)
    entity_accuracy = _analytics_accuracy(analytics, "entity")
    if entity_accuracy > 0.92 and _shadow_has_entity(shadow_result):
        return _governance_decision(
            "LLM",
            False,
            "LOW",
            "LLM setup entity extraction is stable",
            confidence,
        )
    return _governance_decision(
        "LEGACY",
        True,
        "MEDIUM",
        "LLM setup authority checks failed",
        confidence,
    )


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
