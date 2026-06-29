from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from app.services.input_normalizer import ROLE_TOKEN_MAP, clean_entity_name

ALLOWED_DOMAINS = {"SETUP", "FINANCIAL", "WORK", "CONTACT", "ACCOUNT", "NOTE", "OTHER"}
ALLOWED_ENTITY_TYPES = {"PERSON", "COMPANY", "UNKNOWN"}
ALLOWED_PROJECT_ROLES = {"CLIENT", "VENDOR", "DAILY_WORKER", "SKILLED_WORKER", "OTHER"}
ALLOWED_ACTIONS = {
    "CREATE_OR_UPDATE_PROFILE",
    "UPDATE_PHONE",
    "UPDATE_ACCOUNT",
    "REGISTER_PAYMENT",
    "REGISTER_INVOICE",
    "REGISTER_WORK_LOG",
    "ADD_NOTE",
    "OTHER",
}
ALLOWED_FINANCIAL_DIRECTIONS = {"INCOMING", "OUTGOING", "NONE", "UNKNOWN"}

ROLE_WORDS = tuple(sorted(ROLE_TOKEN_MAP.keys(), key=len, reverse=True))


@dataclass(frozen=True)
class ControlledClassification:
    domain: str
    action: str
    entity_type: str
    project_role: str
    selected_name: str | None
    role_detail: str | None
    financial_direction: str
    amount: Decimal | None
    phone: str | None
    account_number: str | None
    confidence: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "action": self.action,
            "entity_type": self.entity_type,
            "project_role": self.project_role,
            "selected_name": self.selected_name,
            "role_detail": self.role_detail,
            "financial_direction": self.financial_direction,
            "amount": int(self.amount) if self.amount is not None and self.amount == self.amount.to_integral() else self.amount,
            "phone": self.phone,
            "account_number": self.account_number,
            "confidence": self.confidence,
        }


def validate_controlled_classification(
    raw_output: dict[str, Any],
    normalized_input: dict[str, Any],
) -> ControlledClassification:
    if not isinstance(raw_output, dict):
        return safe_controlled_classification()

    domain = _enum(raw_output.get("domain"), ALLOWED_DOMAINS, "OTHER")
    action = _enum(raw_output.get("action"), ALLOWED_ACTIONS, "OTHER")
    entity_type = _enum(raw_output.get("entity_type"), ALLOWED_ENTITY_TYPES, "UNKNOWN")
    project_role = _enum(raw_output.get("project_role"), ALLOWED_PROJECT_ROLES, "OTHER")
    financial_direction = _enum(
        raw_output.get("financial_direction"),
        ALLOWED_FINANCIAL_DIRECTIONS,
        "UNKNOWN",
    )

    name = _valid_selected_name(raw_output.get("selected_name"), normalized_input)
    role_detail = _role_detail(raw_output.get("role_detail"), normalized_input)
    amount = _candidate_number(raw_output.get("amount"), normalized_input.get("amount_candidates"))
    phone = _candidate_text(raw_output.get("phone"), normalized_input.get("phone_candidates"))
    account_number = _candidate_text(
        raw_output.get("account_number"),
        normalized_input.get("account_candidates"),
    )

    if domain == "CONTACT":
        action = "UPDATE_PHONE" if phone else action
    elif domain == "ACCOUNT":
        action = "UPDATE_ACCOUNT" if account_number else action
    elif domain == "WORK":
        action = "REGISTER_WORK_LOG"
    elif domain == "NOTE":
        action = "ADD_NOTE"

    return ControlledClassification(
        domain=domain,
        action=action,
        entity_type=entity_type,
        project_role=project_role,
        selected_name=name,
        role_detail=role_detail,
        financial_direction=financial_direction,
        amount=amount,
        phone=phone,
        account_number=account_number,
        confidence=_confidence(raw_output.get("confidence")),
    )


def safe_controlled_classification() -> ControlledClassification:
    return ControlledClassification(
        domain="OTHER",
        action="OTHER",
        entity_type="UNKNOWN",
        project_role="OTHER",
        selected_name=None,
        role_detail=None,
        financial_direction="UNKNOWN",
        amount=None,
        phone=None,
        account_number=None,
        confidence=0.0,
    )


def controlled_to_llm_v2_schema(
    classification: ControlledClassification,
    raw_text: str,
) -> dict[str, Any]:
    intent, action = _legacy_intent_action(classification)
    entity: dict[str, Any] | None = None
    if classification.selected_name is not None:
        entity = {
            "name": classification.selected_name,
            "kind": classification.entity_type,
            "project_role": classification.project_role,
            "role_detail": classification.role_detail,
            "phone": classification.phone,
            "account_number": classification.account_number,
            "daily_rate": None,
            "notes": None,
            "field_updates": None,
        }
        updates = {}
        if classification.phone:
            updates["phone"] = classification.phone
        if classification.account_number:
            updates["account_number"] = classification.account_number
        if updates:
            entity["field_updates"] = updates

    return {
        "intent": intent,
        "action": action,
        "entities": [entity] if entity is not None else [],
        "financial": {
            "amount": int(classification.amount) if classification.amount is not None else None,
            "direction": _legacy_direction(classification.financial_direction),
            "payment_method": None,
            "due_date_text": None,
        },
        "work": {"quantity": None, "unit": None, "description": None},
        "note": {"text": raw_text if intent == "NOTE" else None},
        "confidence": classification.confidence,
        "ambiguity": classification.confidence < 0.5 or classification.action == "OTHER",
        "missing_fields": [],
        "reasoning_summary": "controlled classification contract",
    }


def _legacy_intent_action(classification: ControlledClassification) -> tuple[str, str]:
    if classification.action == "UPDATE_PHONE" or classification.domain == "CONTACT":
        return "SETUP", "UPDATE_ENTITY"
    if classification.action == "UPDATE_ACCOUNT" or classification.domain == "ACCOUNT":
        return "SETUP", "UPDATE_ENTITY"
    if classification.action == "REGISTER_WORK_LOG":
        return "WORK", "WORK_LOG"
    if classification.action == "REGISTER_PAYMENT":
        return "FINANCIAL", "PAYMENT_IN" if classification.financial_direction == "INCOMING" else "PAYMENT_OUT"
    if classification.action == "REGISTER_INVOICE":
        return "FINANCIAL", "DEBT_CREATED"
    if classification.action == "ADD_NOTE" or classification.domain in {"NOTE", "OTHER"}:
        return "NOTE", "NOTE"
    if classification.action == "CREATE_OR_UPDATE_PROFILE":
        return "SET_ROLE", "SET_ROLE"
    return "NOTE", "NOTE"


def _legacy_direction(direction: str) -> str:
    if direction == "INCOMING":
        return "IN"
    if direction == "OUTGOING":
        return "OUT"
    return "NONE"


def _enum(value: Any, allowed: set[str], fallback: str) -> str:
    if isinstance(value, str) and value.strip().upper() in allowed:
        return value.strip().upper()
    return fallback


def _valid_selected_name(value: Any, normalized_input: dict[str, Any]) -> str | None:
    candidates = [
        candidate
        for candidate in normalized_input.get("name_candidates") or []
        if isinstance(candidate, str) and candidate.strip()
    ]
    clean_value = clean_entity_name(str(value)) if isinstance(value, str) else None
    if candidates:
        if clean_value in candidates and not _name_is_corrupt(clean_value):
            return clean_value
        return candidates[0]
    if clean_value and not _name_is_corrupt(clean_value):
        return clean_value
    return None


def _name_is_corrupt(value: str) -> bool:
    compact = value.strip()
    if not compact:
        return True
    if re.search(r"[:：؛;،,\-_/|۰-۹٠-٩0-9]", compact):
        return True
    return any(token in compact for token in ROLE_WORDS)


def _role_detail(value: Any, normalized_input: dict[str, Any]) -> str | None:
    if isinstance(value, str) and value.strip():
        detail = value.strip()
    else:
        role_candidates = normalized_input.get("role_candidates") or []
        first = role_candidates[0] if role_candidates and isinstance(role_candidates[0], dict) else {}
        detail = str(first.get("token") or "").strip()
    return detail or None


def _candidate_number(value: Any, candidates: Any) -> Decimal | None:
    normalized_candidates = [_decimal(candidate) for candidate in candidates or []]
    normalized_candidates = [candidate for candidate in normalized_candidates if candidate is not None]
    value_decimal = _decimal(value)
    if normalized_candidates:
        return value_decimal if value_decimal in normalized_candidates else normalized_candidates[0]
    return value_decimal


def _candidate_text(value: Any, candidates: Any) -> str | None:
    normalized_candidates = [str(candidate).strip() for candidate in candidates or [] if str(candidate).strip()]
    value_text = str(value).strip() if value is not None else None
    if normalized_candidates:
        return value_text if value_text in normalized_candidates else normalized_candidates[0]
    return value_text or None


def _decimal(value: Any) -> Decimal | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return max(0.0, min(float(value), 1.0))
