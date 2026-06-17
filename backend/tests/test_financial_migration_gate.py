from typing import Any

from app.core.feature_flags import FinancialMigrationMode
from app.services.financial_migration_gate import FinancialMigrationGate


def _legacy(
    *,
    entity: str = "میثم",
    amount: str = "200000000.00",
    direction: str = "OUTGOING",
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
    amount: int = 200000000,
    direction: str = "OUT",
    confidence: float = 0.9,
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


def _ready_decision() -> dict[str, Any]:
    return {"recommended_migrations": {"FINANCIAL": {"ready": True}}}


def test_off_mode_always_uses_legacy() -> None:
    decision = FinancialMigrationGate().decide(
        _legacy(),
        _shadow(),
        _ready_decision(),
        FinancialMigrationMode.OFF,
    )

    assert decision["chosen_system"] == "LEGACY"


def test_shadow_only_mode_does_not_execute_shadow() -> None:
    decision = FinancialMigrationGate().decide(
        _legacy(),
        _shadow(),
        _ready_decision(),
        FinancialMigrationMode.SHADOW_ONLY,
    )

    assert decision["chosen_system"] == "LEGACY"
    assert "Shadow-only" in decision["reason"]


def test_a_b_test_selects_one_path(monkeypatch) -> None:
    monkeypatch.setattr("app.services.financial_migration_gate.random.random", lambda: 0.75)

    decision = FinancialMigrationGate().decide(
        _legacy(),
        _shadow(),
        _ready_decision(),
        FinancialMigrationMode.A_B_TEST,
    )

    assert decision["chosen_system"] == "SHADOW"


def test_llm_primary_success_uses_shadow() -> None:
    decision = FinancialMigrationGate().decide(
        _legacy(),
        _shadow(confidence=0.95),
        _ready_decision(),
        FinancialMigrationMode.LLM_PRIMARY,
    )

    assert decision["chosen_system"] == "SHADOW"


def test_llm_primary_fallback_conditions_use_legacy() -> None:
    gate = FinancialMigrationGate()

    assert (
        gate.decide(
            _legacy(),
            _shadow(confidence=0.4),
            _ready_decision(),
            FinancialMigrationMode.LLM_PRIMARY,
        )["chosen_system"]
        == "LEGACY"
    )
    assert (
        gate.decide(
            _legacy(),
            _shadow(ambiguity=True),
            _ready_decision(),
            FinancialMigrationMode.LLM_PRIMARY,
        )["chosen_system"]
        == "LEGACY"
    )
    assert (
        gate.decide(
            _legacy(suggested_entity_id=None),
            _shadow(),
            _ready_decision(),
            FinancialMigrationMode.LLM_PRIMARY,
        )["chosen_system"]
        == "LEGACY"
    )


def test_mismatch_safety_override_forces_legacy() -> None:
    decision = FinancialMigrationGate().decide(
        _legacy(entity="علی"),
        _shadow(entity="میثم", confidence=0.95),
        _ready_decision(),
        FinancialMigrationMode.LLM_PRIMARY,
    )

    assert decision["chosen_system"] == "LEGACY"
    assert "Safety override" in decision["reason"]
