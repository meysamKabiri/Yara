import random
from typing import Any

from app.core.feature_flags import FinancialMigrationMode
from app.core.validation.financial_validator import (
    financial_decision_ready,
    financial_outputs_match,
    legacy_has_resolved_entity,
    shadow_financial_unsafe_reason,
)
from app.services.compare_legacy_vs_shadow import compare_legacy_vs_shadow


class FinancialMigrationGate:
    def validate_llm_safety(
        self,
        legacy_result: dict[str, Any] | list[dict[str, Any]],
        shadow_result: dict[str, Any],
        decision_engine_output: dict[str, Any] | None,
    ) -> dict[str, Any]:
        diff = compare_legacy_vs_shadow(legacy_result, shadow_result)
        if not financial_outputs_match(diff):
            return _decision("LEGACY", legacy_result, "Safety override: legacy/shadow mismatch")
        if not financial_decision_ready(decision_engine_output):
            return _decision(
                "LEGACY",
                legacy_result,
                "Decision engine has not marked financial ready",
            )
        if not legacy_has_resolved_entity(legacy_result):
            return _decision("LEGACY", legacy_result, "Shadow fallback: entity is not resolved")
        unsafe_reason = shadow_financial_unsafe_reason(shadow_result)
        if unsafe_reason is not None:
            return _decision("LEGACY", legacy_result, unsafe_reason)
        return _decision("SHADOW", shadow_result, "LLM financial safety checks passed")

    def decide(
        self,
        legacy_result: dict[str, Any] | list[dict[str, Any]],
        shadow_result: dict[str, Any],
        decision_engine_output: dict[str, Any] | None,
        feature_flag: FinancialMigrationMode | str,
    ) -> dict[str, Any]:
        mode = _mode(feature_flag)
        diff = compare_legacy_vs_shadow(legacy_result, shadow_result)

        if mode == FinancialMigrationMode.OFF:
            return _decision("LEGACY", legacy_result, "Financial migration is OFF")

        if mode == FinancialMigrationMode.SHADOW_ONLY:
            return _decision("LEGACY", legacy_result, "Shadow-only mode executes legacy")

        if not financial_outputs_match(diff):
            return _decision("LEGACY", legacy_result, "Safety override: legacy/shadow mismatch")

        if mode == FinancialMigrationMode.A_B_TEST:
            if random.random() < 0.5:
                return _decision("LEGACY", legacy_result, "A/B test selected legacy")
            return _decision("SHADOW", shadow_result, "A/B test selected shadow")

        if mode == FinancialMigrationMode.LLM_PRIMARY:
            if not financial_decision_ready(decision_engine_output):
                return _decision(
                    "LEGACY",
                    legacy_result,
                    "Decision engine has not marked financial ready",
                )
            if not legacy_has_resolved_entity(legacy_result):
                return _decision("LEGACY", legacy_result, "Shadow fallback: entity is not resolved")
            unsafe_reason = shadow_financial_unsafe_reason(shadow_result)
            if unsafe_reason is not None:
                return _decision("LEGACY", legacy_result, unsafe_reason)
            return _decision("SHADOW", shadow_result, "LLM primary conditions passed")

        return _decision("LEGACY", legacy_result, "Unknown financial migration mode")


def _decision(chosen_system: str, final_result: Any, reason: str) -> dict[str, Any]:
    return {"chosen_system": chosen_system, "final_result": final_result, "reason": reason}


def _mode(value: FinancialMigrationMode | str) -> FinancialMigrationMode:
    if isinstance(value, FinancialMigrationMode):
        return value
    try:
        return FinancialMigrationMode(value)
    except ValueError:
        return FinancialMigrationMode.OFF
