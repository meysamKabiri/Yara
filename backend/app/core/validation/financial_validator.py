from decimal import Decimal, InvalidOperation
from typing import Any


def financial_outputs_match(diff: dict[str, bool]) -> bool:
    return all(
        diff.get(key) is True
        for key in ["intent_match", "entity_match", "amount_match", "direction_match"]
    )


def financial_decision_ready(decision_engine_output: dict[str, Any] | None) -> bool:
    if not isinstance(decision_engine_output, dict):
        return True
    migrations = decision_engine_output.get("recommended_migrations")
    if not isinstance(migrations, dict):
        return True
    financial = migrations.get("FINANCIAL")
    if not isinstance(financial, dict):
        return True
    return financial.get("ready") is True


def shadow_financial_unsafe_reason(shadow_result: dict[str, Any]) -> str | None:
    confidence = shadow_result.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, int | float) or confidence < 0.85:
        return "Shadow fallback: confidence below 0.85"
    if shadow_result.get("ambiguity") is True:
        return "Shadow fallback: ambiguity flag is set"
    entities = shadow_result.get("entities")
    if not isinstance(entities, list) or not any(
        isinstance(entity, dict) and entity.get("name") for entity in entities
    ):
        return "Shadow fallback: entity is not resolved"
    financial = shadow_result.get("financial")
    amount = financial.get("amount") if isinstance(financial, dict) else None
    if decimal_or_none(amount) is None:
        return "Shadow fallback: amount is invalid"
    return None


def legacy_has_resolved_entity(value: dict[str, Any] | list[dict[str, Any]]) -> bool:
    item = first_legacy_item(value)
    return item.get("suggested_entity_id") is not None


def first_legacy_item(value: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
    if isinstance(value, list):
        return value[0] if value and isinstance(value[0], dict) else {}
    return value if isinstance(value, dict) else {}


def decimal_or_none(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
