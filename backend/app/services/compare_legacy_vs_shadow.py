from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.persian_money_engine import normalize_text


def compare_legacy_vs_shadow(
    legacy_result: dict[str, Any] | list[dict[str, Any]],
    shadow_result: dict[str, Any],
) -> dict[str, bool]:
    legacy = _first_legacy_item(legacy_result)
    return {
        "intent_match": _legacy_intent(legacy) == shadow_result.get("intent"),
        "entity_match": _entity_names(legacy) == _entity_names(shadow_result),
        "amount_match": _amount(legacy) == _amount(shadow_result),
        "direction_match": _legacy_direction(legacy) == _shadow_direction(shadow_result),
    }


def _first_legacy_item(value: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
    if isinstance(value, list):
        return value[0] if value and isinstance(value[0], dict) else {}
    interpretations = value.get("interpretations") if isinstance(value, dict) else None
    if isinstance(interpretations, list):
        if interpretations and isinstance(interpretations[0], dict):
            return interpretations[0]
        return {}
    return value if isinstance(value, dict) else {}


def _legacy_intent(value: dict[str, Any]) -> str | None:
    event_type = value.get("canonical_event_type") or value.get("intent") or value.get("type")
    mapping = {
        "SETUP_EVENT": "SETUP",
        "WORK_EVENT": "WORK",
        "FINANCIAL_EVENT": "FINANCIAL",
        "NOTE_EVENT": "NOTE",
    }
    return mapping.get(str(event_type), str(event_type) if event_type is not None else None)


def _entity_names(value: dict[str, Any]) -> list[str]:
    entities = value.get("entities") or value.get("extracted_entities") or []
    names: list[str] = []
    if isinstance(entities, list):
        for entity in entities:
            if isinstance(entity, dict) and isinstance(entity.get("name"), str):
                names.append(_normalize_name(entity["name"]))
    entity = value.get("entity")
    if isinstance(entity, str):
        names.append(_normalize_name(entity))
    return sorted(name for name in names if name)


def _amount(value: dict[str, Any]) -> Decimal | None:
    financial = value.get("financial")
    raw_amount = financial.get("amount") if isinstance(financial, dict) else None
    raw_amount = value.get("extracted_amount", raw_amount)
    if raw_amount is None:
        return None
    try:
        return Decimal(str(raw_amount))
    except (InvalidOperation, ValueError):
        return None


def _legacy_direction(value: dict[str, Any]) -> str | None:
    direction = value.get("financial_direction")
    if direction == "INCOMING":
        return "IN"
    if direction in {"OUTGOING", "DEBT", "DEFERRED"}:
        return "OUT"
    if _legacy_intent(value) != "FINANCIAL":
        return "NONE"
    return None


def _shadow_direction(value: dict[str, Any]) -> str | None:
    financial = value.get("financial")
    if isinstance(financial, dict):
        direction = financial.get("direction")
        if direction in {"IN", "OUT", "NONE"}:
            return direction
    return None


def _normalize_name(value: str) -> str:
    normalized = normalize_text(value).replace("\u200c", " ").strip()
    return " ".join(normalized.split())
