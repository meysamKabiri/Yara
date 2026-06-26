from __future__ import annotations

from typing import Any

from app.services.persian_money_engine import normalize_text


def normalize_outgoing_payment_role(interpretation: dict[str, Any]) -> dict[str, Any]:
    """Normalize final response role fields for plain outgoing payments."""
    if not _is_plain_outgoing_payment(interpretation):
        return interpretation

    text = str(
        interpretation.get("matched_input_text")
        or interpretation.get("raw_input_text")
        or ""
    )
    if _has_explicit_client_role_evidence(text):
        return interpretation

    _downgrade_client_entity(interpretation.get("extracted_entities"))

    structured = interpretation.get("structured_interpretation")
    if isinstance(structured, dict):
        _downgrade_client_entity(structured.get("entities"))
        _downgrade_client_entity(structured.get("extracted_entities"))
        _downgrade_client_entity(structured.get("entity"))

    return interpretation


def normalize_outgoing_payment_roles_in_result(result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    interpretations = result.get("interpretations")
    if isinstance(interpretations, list):
        for item in interpretations:
            if isinstance(item, dict):
                normalize_outgoing_payment_role(item)
    return result


def _is_plain_outgoing_payment(interpretation: dict[str, Any]) -> bool:
    return (
        interpretation.get("canonical_event_type") == "FINANCIAL_EVENT"
        and interpretation.get("semantic_action") == "PAYMENT"
        and _value(interpretation.get("financial_direction")) == "OUTGOING"
    )


def _downgrade_client_entity(value: Any) -> None:
    if isinstance(value, list):
        if value and isinstance(value[0], dict):
            _downgrade_client_entity(value[0])
        return
    if not isinstance(value, dict):
        return
    role = _value(value.get("project_role") or value.get("type") or value.get("role"))
    if role != "CLIENT":
        return
    value["project_role"] = "OTHER"
    if "type" in value:
        value["type"] = "OTHER"
    if "role" in value:
        value["role"] = "OTHER"
    profile = value.get("profile")
    if isinstance(profile, dict) and _value(profile.get("project_role")) == "CLIENT":
        profile["project_role"] = "OTHER"


def _has_explicit_client_role_evidence(raw_text: str) -> bool:
    normalized = normalize_text(raw_text)
    return any(
        term in normalized
        for term in (
            "کارفرما",
            "کارفرمای پروژه",
            "مالک",
            "مالک پروژه",
            "client",
            "owner",
        )
    )


def _value(value: Any) -> str | None:
    if hasattr(value, "value"):
        value = value.value
    return value if isinstance(value, str) else None
