from typing import Any

from app.core.feature_flags import FinancialMigrationMode
from app.core.llm_authority_controller import LLMAuthorityController


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


def test_llm_used_when_financial_confidence_is_high() -> None:
    decision = LLMAuthorityController().decide(
        unified_pipeline_context={"event_type": "FINANCIAL_EVENT"},
        shadow_result=_shadow(confidence=0.95),
        legacy_result=_legacy(),
        migration_mode=FinancialMigrationMode.LLM_PRIMARY,
        analytics_signals={},
    )

    assert decision["primary_source"] == "LLM"
    assert decision["fallback_required"] is False


def test_legacy_fallback_when_ambiguity_exists() -> None:
    decision = LLMAuthorityController().decide(
        unified_pipeline_context={"event_type": "FINANCIAL_EVENT"},
        shadow_result=_shadow(ambiguity=True),
        legacy_result=_legacy(),
        migration_mode=FinancialMigrationMode.LLM_PRIMARY,
        analytics_signals={},
    )

    assert decision["primary_source"] == "LEGACY"
    assert decision["fallback_required"] is True


def test_safety_override_forces_legacy_on_amount_conflict() -> None:
    decision = LLMAuthorityController().decide(
        unified_pipeline_context={"event_type": "FINANCIAL_EVENT"},
        shadow_result=_shadow(amount=100000000),
        legacy_result=_legacy(amount="200000000.00"),
        migration_mode=FinancialMigrationMode.LLM_PRIMARY,
        analytics_signals={},
    )

    assert decision["primary_source"] == "LEGACY"
    assert "amount conflict" in decision["reason"]


def test_safety_override_forces_legacy_on_high_entity_risk() -> None:
    decision = LLMAuthorityController().decide(
        unified_pipeline_context={"event_type": "FINANCIAL_EVENT"},
        shadow_result=_shadow(),
        legacy_result=_legacy(),
        migration_mode=FinancialMigrationMode.LLM_PRIMARY,
        analytics_signals={
            "risk_areas": [
                {
                    "domain": "FINANCIAL",
                    "issue": "Entity mismatch frequency: 20/100 samples",
                    "severity": "HIGH",
                }
            ]
        },
    )

    assert decision["primary_source"] == "LEGACY"
    assert "entity mismatch risk" in decision["reason"]
