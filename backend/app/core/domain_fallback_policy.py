from __future__ import annotations

from enum import StrEnum
from typing import Any


DEFAULT_FALLBACK = "NOTE"
DEFAULT_FALLBACK_DOMAIN = DEFAULT_FALLBACK

_EXPLICIT_SETUP_TEXT_SIGNALS = (
    "کارفرمای پروژه است",
    "کارفرما است",
    "کارگر پروژه است",
    "به پروژه اضافه",
    "اضافه شد",
    "به عنوان",
    "نقش",
    "تخصیص داده شد",
    "شماره تماس",
    "شماره موبایل",
    "شماره حساب",
    "دستمزد روزانه",
)
_SETUP_ACTION_SIGNALS = {
    "ADD_ENTITY",
    "UPDATE_ENTITY",
    "ENTITY_UPDATE",
    "SET_ROLE",
    "SETUP",
}
_PROFILE_FIELD_KEYS = {
    "phone",
    "account_number",
    "accountNumber",
    "card_number",
    "cardNumber",
    "daily_rate",
    "dailyRate",
    "notes",
}


def is_fallback_domain(domain: str) -> bool:
    return _domain_value(domain) == DEFAULT_FALLBACK


def is_strong_setup_signal(input_data: Any) -> bool:
    """Return True only for explicit setup/profile evidence."""
    raw_text, data = _coerce_input(input_data)
    normalized = _normalize_text(raw_text)
    if any(signal in normalized for signal in _EXPLICIT_SETUP_TEXT_SIGNALS):
        return True

    action = str(data.get("action") or data.get("semantic_action") or "").upper()
    if action in _SETUP_ACTION_SIGNALS:
        return True

    for entity in data.get("entities") or data.get("extracted_entities") or []:
        if not isinstance(entity, dict):
            continue
        field_updates = entity.get("field_updates")
        if isinstance(field_updates, dict) and _has_profile_value(field_updates):
            return True
        if _has_profile_value(entity):
            return True
    return False


def resolve_fallback(domain: Any = None, context: Any = None) -> str:
    if is_strong_setup_signal(context if context is not None else domain):
        return "SETUP"
    return DEFAULT_FALLBACK


def _has_profile_value(value: dict[str, Any]) -> bool:
    return any(value.get(key) not in (None, "") for key in _PROFILE_FIELD_KEYS)


def _coerce_input(input_data: Any) -> tuple[str, dict[str, Any]]:
    if input_data is None:
        return "", {}
    if isinstance(input_data, str):
        return input_data, {}
    if isinstance(input_data, dict):
        raw_text = (
            input_data.get("raw_text")
            or input_data.get("text")
            or input_data.get("input_text")
            or input_data.get("raw_input_text")
            or ""
        )
        interpretation = input_data.get("interpretation")
        if isinstance(interpretation, dict):
            data = {**input_data, **interpretation}
        else:
            data = input_data
        graph = input_data.get("graph")
        if isinstance(graph, dict):
            data = {**data, **_graph_setup_data(graph)}
        return str(raw_text), data
    raw_text = str(getattr(input_data, "raw_input_text", "") or getattr(input_data, "description", "") or "")
    data = {
        "action": getattr(input_data, "action", None),
        "semantic_action": getattr(input_data, "semantic_action", None),
        "entities": getattr(input_data, "extracted_entities", None) or getattr(input_data, "entities", None) or [],
    }
    return raw_text, data


def _graph_setup_data(graph: dict[str, Any]) -> dict[str, Any]:
    entities = []
    raw_entities = graph.get("entities")
    if isinstance(raw_entities, list):
        entities.extend(entity for entity in raw_entities if isinstance(entity, dict))
    setup_entities = graph.get("setup_entities")
    if isinstance(setup_entities, list):
        entities.extend(entity for entity in setup_entities if isinstance(entity, dict))
    return {"entities": entities}


def _domain_value(domain: Any) -> str:
    if isinstance(domain, StrEnum):
        return domain.value.upper()
    value = getattr(domain, "value", domain)
    return str(value or "").upper()


def _normalize_text(value: str | None) -> str:
    normalized = (value or "").strip().replace("ي", "ی").replace("ك", "ک")
    normalized = normalized.replace("\u200c", " ")
    return " ".join(normalized.split())
