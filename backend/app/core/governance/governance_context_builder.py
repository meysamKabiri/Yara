from typing import Any

from sqlalchemy.orm import Session

from app.core.feature_flags import FinancialMigrationMode
from app.services.shadow_migration_decision_engine import MigrationDecisionEngine


class GovernanceContextBuilder:
    def __init__(self, db: Session | None = None) -> None:
        self.db = db

    def build(
        self,
        *,
        event_type: str,
        legacy_result: dict[str, Any] | list[dict[str, Any]],
        shadow_result: dict[str, Any],
        migration_mode: FinancialMigrationMode | str,
    ) -> dict[str, Any]:
        decision_engine_output = (
            MigrationDecisionEngine(self.db).recommendation() if self.db is not None else None
        )
        return {
            "event_type": event_type,
            "intent": shadow_result.get("intent"),
            "entities": shadow_result.get("entities", []),
            "financial": _financial_summary(shadow_result),
            "confidence": shadow_result.get("confidence"),
            "legacy_result": legacy_result,
            "shadow_result": shadow_result,
            "migration_mode": migration_mode,
            "decision_engine_output": decision_engine_output,
            "analytics_signals": {
                "risk_areas": (
                    decision_engine_output.get("risk_areas", [])
                    if isinstance(decision_engine_output, dict)
                    else []
                )
            },
        }


def _financial_summary(shadow_result: dict[str, Any]) -> dict[str, Any]:
    financial = shadow_result.get("financial")
    if not isinstance(financial, dict):
        return {"amount": None, "direction": "NONE"}
    return {
        "amount": financial.get("amount"),
        "direction": financial.get("direction", "NONE"),
    }
