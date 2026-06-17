from typing import Any

from app.core.feature_flags import FinancialMigrationMode
from app.core.governance.unified_governance_engine import UnifiedGovernanceEngine


def _legacy(
    *,
    entity: str = "میثم",
    amount: str = "200000000.00",
    direction: str = "INCOMING",
    suggested_entity_id: int | None = 1,
) -> list[dict[str, Any]]:
    return [
        {
            "canonical_event_type": "FINANCIAL_EVENT",
            "extracted_entities": [{"name": entity}],
            "extracted_amount": amount,
            "financial_direction": direction,
            "suggested_entity_id": suggested_entity_id,
        }
    ]


def _shadow(
    *,
    entity: str = "میثم",
    amount: int | None = 200000000,
    direction: str = "IN",
    confidence: float = 0.95,
    ambiguity: bool = False,
) -> dict[str, Any]:
    return {
        "intent": "FINANCIAL",
        "entities": [{"name": entity, "kind": "PERSON"}] if entity else [],
        "financial": {"amount": amount, "direction": direction},
        "work": {"quantity": None, "unit": None},
        "confidence": confidence,
        "ambiguity": ambiguity,
        "missing_fields": [],
        "reasoning": "test",
    }


def _context(
    legacy: list[dict[str, Any]] | None = None,
    shadow: dict[str, Any] | None = None,
    mode: FinancialMigrationMode = FinancialMigrationMode.LLM_PRIMARY,
) -> dict[str, Any]:
    return {
        "event_type": "FINANCIAL_EVENT",
        "legacy_result": legacy or _legacy(),
        "shadow_result": shadow or _shadow(),
        "migration_mode": mode,
        "decision_engine_output": {"recommended_migrations": {"FINANCIAL": {"ready": True}}},
        "analytics_signals": {},
    }


def test_unified_governance_selects_llm_when_safe() -> None:
    decision = UnifiedGovernanceEngine().evaluate(_context())

    assert decision == {
        "primary_source": "LLM",
        "fallback_required": False,
        "risk_level": "LOW",
        "reason": "LLM financial safety checks passed",
        "confidence": 0.95,
    }


def test_unified_governance_falls_back_on_ambiguity() -> None:
    decision = UnifiedGovernanceEngine().evaluate(_context(shadow=_shadow(ambiguity=True)))

    assert decision["primary_source"] == "LEGACY"
    assert decision["fallback_required"] is True
    assert decision["risk_level"] == "HIGH"


def test_unified_governance_falls_back_on_amount_conflict() -> None:
    decision = UnifiedGovernanceEngine().evaluate(_context(shadow=_shadow(amount=100000000)))

    assert decision["primary_source"] == "LEGACY"
    assert decision["reason"] == "Safety override: amount conflict detected"


def test_unified_governance_off_mode_preserves_legacy_reason() -> None:
    decision = UnifiedGovernanceEngine().evaluate(_context(mode=FinancialMigrationMode.OFF))

    assert decision["primary_source"] == "LEGACY"
    assert decision["reason"] == "Financial migration is OFF"
