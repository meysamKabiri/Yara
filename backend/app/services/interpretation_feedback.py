from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.logger import log_event
from app.models.core import (
    FinancialDirection,
    InterpretationFeedback,
    InterpretationFeedbackErrorType,
    InterpretationFeedbackSource,
    PendingInterpretation,
)


def classify_interpretation_errors(
    system_output: dict[str, Any],
    user_final_state: dict[str, Any],
) -> list[str]:
    errors: list[InterpretationFeedbackErrorType] = []

    if _domain(system_output) != _domain(user_final_state):
        errors.append(InterpretationFeedbackErrorType.WRONG_DOMAIN)

    if _entities(system_output) != _entities(user_final_state):
        errors.append(InterpretationFeedbackErrorType.WRONG_ENTITY)

    if _amount(system_output) != _amount(user_final_state):
        errors.append(InterpretationFeedbackErrorType.WRONG_AMOUNT)

    if _roles(system_output) != _roles(user_final_state):
        errors.append(InterpretationFeedbackErrorType.WRONG_ROLE)

    if _has_missing_extraction(system_output, user_final_state):
        errors.append(InterpretationFeedbackErrorType.MISSING_EXTRACTION)

    return [error.value for error in errors]


def create_interpretation_feedback(
    db: Session,
    *,
    project_id: int,
    raw_input: str,
    system_output: dict[str, Any],
    user_final_state: dict[str, Any],
    trace_id: str | None = None,
    correction_source: InterpretationFeedbackSource = InterpretationFeedbackSource.USER_EDIT,
) -> InterpretationFeedback:
    normalized_system = _json_safe(system_output)
    normalized_final = _json_safe(user_final_state)
    error_types = classify_interpretation_errors(normalized_system, normalized_final)
    submission_hash = _submission_hash(
        project_id=project_id,
        trace_id=trace_id,
        raw_input=raw_input,
        system_output=normalized_system,
        user_final_state=normalized_final,
        correction_source=correction_source.value,
    )

    existing = db.scalar(
        select(InterpretationFeedback).where(
            InterpretationFeedback.submission_hash == submission_hash
        )
    )
    if existing is not None:
        return existing

    feedback = InterpretationFeedback(
        project_id=project_id,
        trace_id=trace_id,
        raw_input=raw_input,
        system_output=normalized_system,
        user_final_state=normalized_final,
        error_types=error_types,
        correction_source=correction_source,
        submission_hash=submission_hash,
    )
    db.add(feedback)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(InterpretationFeedback).where(
                InterpretationFeedback.submission_hash == submission_hash
            )
        )
        if existing is None:
            raise
        return existing

    log_event(
        trace_id=trace_id,
        event="interpretation.feedback_captured",
        message="Interpretation feedback captured",
        payload={
            "project_id": project_id,
            "raw_input": raw_input,
            "system_output": normalized_system,
            "user_final_state": normalized_final,
            "error_types": error_types,
            "trace_id": trace_id,
            "correction_source": correction_source.value,
        },
    )
    return feedback


def pending_interpretation_feedback_state(
    interpretation: PendingInterpretation,
) -> dict[str, Any]:
    structured = interpretation.structured_interpretation or {}
    financial = structured.get("financial") if isinstance(structured, dict) else None
    entities = (
        structured.get("entities")
        if isinstance(structured, dict) and isinstance(structured.get("entities"), list)
        else interpretation.extracted_entities
    )
    domain = None
    if isinstance(structured, dict):
        domain = structured.get("domain") or structured.get("intent")

    return _json_safe(
        {
            "domain": domain or interpretation.canonical_event_type,
            "action": interpretation.semantic_action,
            "entities": entities or [],
            "financials": {
                "amount": interpretation.extracted_amount,
                "direction": _direction_value(interpretation.financial_direction),
                "payment_method": interpretation.payment_method,
                "due_date": interpretation.due_date,
                **(financial if isinstance(financial, dict) else {}),
            },
            "work": {
                "quantity": interpretation.extracted_quantity,
                "description": interpretation.description,
            },
        }
    )


def capture_pending_interpretation_feedback(
    db: Session,
    *,
    interpretation: PendingInterpretation,
    system_output: dict[str, Any],
    trace_id: str | None,
    correction_source: InterpretationFeedbackSource = InterpretationFeedbackSource.USER_EDIT,
) -> InterpretationFeedback | None:
    final_state = pending_interpretation_feedback_state(interpretation)
    error_types = classify_interpretation_errors(system_output, final_state)
    if not error_types:
        return None
    return create_interpretation_feedback(
        db,
        project_id=interpretation.project_id,
        trace_id=trace_id,
        raw_input=interpretation.raw_input_text,
        system_output=system_output,
        user_final_state=final_state,
        correction_source=correction_source,
    )


def _domain(payload: dict[str, Any]) -> str | None:
    value = payload.get("domain") or payload.get("intent") or payload.get("canonical_event_type")
    return _normalize_scalar(value)


def _entities(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("entities") or payload.get("extracted_entities") or []
    if not isinstance(raw, list):
        return []
    normalized = [_normalize_entity(entity) for entity in raw if isinstance(entity, dict)]
    return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False))


def _normalize_entity(entity: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _normalize_scalar(value)
        for key, value in entity.items()
        if key not in {"candidate_matches", "confidence"} and not _is_blank(value)
    }


def _amount(payload: dict[str, Any]) -> Decimal | None:
    financial = payload.get("financials") or payload.get("financial") or {}
    if isinstance(financial, dict) and "amount" in financial:
        return _decimal(financial.get("amount"))
    if "amount" in payload:
        return _decimal(payload.get("amount"))
    return None


def _roles(payload: dict[str, Any]) -> list[str | None]:
    roles: list[str | None] = []
    for entity in _entities(payload):
        roles.append(
            entity.get("role")
            or entity.get("project_role")
            or entity.get("type")
            or entity.get("kind")
        )
    return sorted(roles, key=lambda value: value or "")


def _has_missing_extraction(system_value: Any, final_value: Any) -> bool:
    if _is_blank(system_value) and not _is_blank(final_value):
        return True
    if isinstance(system_value, dict) and isinstance(final_value, dict):
        for key, value in final_value.items():
            if _has_missing_extraction(system_value.get(key), value):
                return True
    if isinstance(system_value, list) and isinstance(final_value, list):
        for index, value in enumerate(final_value):
            system_item = system_value[index] if index < len(system_value) else None
            if _has_missing_extraction(system_item, value):
                return True
    return False


def _submission_hash(**payload: Any) -> str:
    serialized = json.dumps(_json_safe(payload), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, FinancialDirection):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_safe(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _normalize_scalar(value: Any) -> str | None:
    if _is_blank(value):
        return None
    return str(value).strip().upper()


def _decimal(value: Any) -> Decimal | None:
    if _is_blank(value):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _direction_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, FinancialDirection):
        return value.value
    return str(value)


def _is_blank(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}
