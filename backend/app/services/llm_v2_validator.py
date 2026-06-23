import re
from decimal import Decimal, InvalidOperation
from typing import Any, TypedDict

from pydantic import ValidationError

from app.models.core import Worker
from app.schemas.llm_v2 import (
    LLMv2Action,
    LLMv2FinancialDirection,
    LLMv2Intent,
    LLMv2Interpretation,
    LLMv2PaymentMethod,
    LLMv2ProjectRole,
)
from app.services.entity_normalizer import compact_name, match_score, normalize_name
from app.services.persian_money_engine import normalize_text, parse_persian_money


class LLMv2ValidationError(ValueError):
    def __init__(self, message: str, raw: dict[str, Any] | None = None):
        self.message = message
        self.raw = raw
        super().__init__(message)


class EntityCandidate(TypedDict):
    person_id: int
    name: str
    score: float
    match_type: str


class EntityResolution(TypedDict):
    candidates: list[EntityCandidate]
    requires_confirmation: bool


def resolve_candidates(name: str, entity_context: list[Worker]) -> EntityResolution:
    normalized_name = normalize_name(name)
    if not normalized_name:
        return {"candidates": [], "requires_confirmation": False}

    candidates = sorted(
        [
            {
                "person_id": worker.id,
                "name": worker.name,
                "score": _candidate_score(name, worker.name),
                "match_type": _candidate_match_type(name, worker.name),
            }
            for worker in entity_context
            if _candidate_score(name, worker.name) > 0
        ],
        key=lambda candidate: (-candidate["score"], candidate["person_id"]),
    )
    return {
        "candidates": candidates,
        "requires_confirmation": bool(candidates),
    }


def _candidate_score(a: str, b: str) -> float:
    return match_score(a, b)


def _candidate_match_type(a: str, b: str) -> str:
    normalized_a = normalize_name(a)
    normalized_b = normalize_name(b)
    if normalized_a == normalized_b:
        return "exact"
    compact_a = compact_name(a)
    compact_b = compact_name(b)
    if compact_a == compact_b:
        return "compact"
    if normalized_a in normalized_b or normalized_b in normalized_a:
        return "partial"
    if compact_a in compact_b or compact_b in compact_a:
        return "partial"
    return "none"


class LLMv2Validator:
    def validate(
        self,
        raw: dict[str, Any],
        entity_context: list[Worker],
    ) -> LLMv2Interpretation:
        try:
            interpretation = LLMv2Interpretation(**raw)
        except ValidationError as exc:
            raise LLMv2ValidationError(
                f"LLM output failed schema validation: {exc.errors()}",
                raw=raw,
            ) from exc

        self._classify_entity_setup_action(interpretation)
        self._validate_action_intent_consistency(interpretation)
        self._sanitize_role_assignment_missing_fields(interpretation)
        self._apply_financial_safety_defaults(interpretation)
        self._validate_financial_fields(interpretation)
        self._validate_work_fields(interpretation, raw)

        return interpretation

    def validate_multi(
        self,
        raw: dict[str, Any],
        entity_context: list[Worker],
    ) -> list[LLMv2Interpretation]:
        events = raw.get("events")
        if not isinstance(events, list) or not events:
            return [self.validate(raw, entity_context)]
        results: list[LLMv2Interpretation] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            validated = self.validate(event, entity_context)
            results.append(validated)
        return results

    def resolve_entities(
        self,
        interpretation: LLMv2Interpretation,
        entity_context: list[Worker],
    ) -> dict[int, Worker | None]:
        return {i: None for i, _entity in enumerate(interpretation.entities)}

    def normalize_amount(self, raw_value: Any, raw_text: str | None = None) -> Decimal | None:
        if raw_text:
            parsed_text_amount = parse_persian_money(raw_text)
            if parsed_text_amount is not None:
                return Decimal(parsed_text_amount)
        if isinstance(raw_value, int | float) and not isinstance(raw_value, bool):
            return Decimal(str(raw_value))
        if isinstance(raw_value, str):
            try:
                raw_clean = raw_value.replace(",", "").replace("،", "")
                if raw_clean.isdigit() or (raw_clean.startswith("-") and raw_clean[1:].isdigit()):
                    return None
                amount = parse_persian_money(raw_value)
                if amount is not None:
                    return Decimal(amount)
            except (InvalidOperation, ValueError):
                pass
        return None

    def normalize_quantity(self, raw_value: Any) -> Decimal | None:
        if isinstance(raw_value, int | float) and not isinstance(raw_value, bool):
            return Decimal(str(raw_value))
        return None

    def _validate_action_intent_consistency(self, interpretation: LLMv2Interpretation) -> None:
        intent_action_map = {
            LLMv2Intent.SET_ROLE: {LLMv2Action.SET_ROLE},
            LLMv2Intent.SETUP: {LLMv2Action.ADD_ENTITY, LLMv2Action.UPDATE_ENTITY},
            LLMv2Intent.WORK: {LLMv2Action.WORK_LOG},
            LLMv2Intent.FINANCIAL: {
                LLMv2Action.PAYMENT_IN,
                LLMv2Action.PAYMENT_OUT,
                LLMv2Action.PURCHASE_PAID,
                LLMv2Action.DEBT_CREATED,
                LLMv2Action.CHECK_PAYMENT,
            },
            LLMv2Intent.NOTE: {LLMv2Action.NOTE},
            LLMv2Intent.DOCUMENT: {LLMv2Action.NOTE},
        }
        valid_actions = intent_action_map.get(interpretation.intent, {LLMv2Action.NOTE})
        if interpretation.action not in valid_actions:
            interpretation.ambiguity = True
            field = f"action={interpretation.action.value} incompatible with intent={interpretation.intent.value}"
            if interpretation.missing_fields is None:
                interpretation.missing_fields = []
            if field not in interpretation.missing_fields:
                interpretation.missing_fields.append(field)

    def _classify_entity_setup_action(self, interpretation: LLMv2Interpretation) -> None:
        if interpretation.intent not in {LLMv2Intent.SETUP, LLMv2Intent.SET_ROLE}:
            return
        if interpretation.action == LLMv2Action.UPDATE_ENTITY and self._has_profile_updates(interpretation):
            return
        if self._is_role_assignment_only(interpretation):
            interpretation.intent = LLMv2Intent.SET_ROLE
            interpretation.action = LLMv2Action.SET_ROLE

    def _is_role_assignment_only(self, interpretation: LLMv2Interpretation) -> bool:
        if not interpretation.entities:
            return False
        if interpretation.financial.amount is not None or interpretation.financial.direction != LLMv2FinancialDirection.NONE:
            return False
        if interpretation.work.quantity is not None or interpretation.work.description:
            return False
        if interpretation.note.text:
            return False
        if self._has_profile_updates(interpretation):
            return False
        return any(
            entity.project_role != LLMv2ProjectRole.OTHER or bool(entity.role_detail)
            for entity in interpretation.entities
        )

    def _has_profile_updates(self, interpretation: LLMv2Interpretation) -> bool:
        for entity in interpretation.entities:
            field_updates = entity.field_updates if isinstance(entity.field_updates, dict) else {}
            if any(field_updates.get(key) is not None for key in ["phone", "account_number", "daily_rate", "notes"]):
                return True
            if any(
                getattr(entity, key, None) is not None
                for key in ["phone", "account_number", "daily_rate", "notes"]
            ):
                return True
        return False

    def _sanitize_role_assignment_missing_fields(self, interpretation: LLMv2Interpretation) -> None:
        if interpretation.intent == LLMv2Intent.SET_ROLE and interpretation.action == LLMv2Action.SET_ROLE:
            interpretation.missing_fields = []

    def _validate_financial_fields(self, interpretation: LLMv2Interpretation) -> None:
        if interpretation.intent != LLMv2Intent.FINANCIAL:
            return
        if interpretation.missing_fields is None:
            interpretation.missing_fields = []
        if interpretation.financial.amount is None:
            if "amount" not in interpretation.missing_fields:
                interpretation.missing_fields.append("amount")
        if not interpretation.entities:
            if "entity" not in interpretation.missing_fields:
                interpretation.missing_fields.append("entity")
        if interpretation.financial.direction == LLMv2FinancialDirection.NONE:
            if "direction" not in interpretation.missing_fields:
                interpretation.missing_fields.append("direction")

    def _apply_financial_safety_defaults(self, interpretation: LLMv2Interpretation) -> None:
        if interpretation.intent != LLMv2Intent.FINANCIAL:
            return
        if interpretation.action == LLMv2Action.PAYMENT_IN:
            interpretation.financial.direction = LLMv2FinancialDirection.IN
            if interpretation.financial.payment_method is None:
                interpretation.financial.payment_method = LLMv2PaymentMethod.BANK_TRANSFER
            for entity in interpretation.entities:
                if entity.project_role == LLMv2ProjectRole.OTHER:
                    entity.project_role = LLMv2ProjectRole.CLIENT
            return
        if interpretation.action == LLMv2Action.PURCHASE_PAID:
            interpretation.financial.direction = LLMv2FinancialDirection.OUT
            if interpretation.financial.payment_method is None:
                interpretation.financial.payment_method = LLMv2PaymentMethod.CASH
        if interpretation.action in {LLMv2Action.PURCHASE_PAID, LLMv2Action.DEBT_CREATED}:
            for entity in interpretation.entities:
                entity.project_role = LLMv2ProjectRole.VENDOR

    def _validate_work_fields(self, interpretation: LLMv2Interpretation, raw: dict[str, Any]) -> None:
        if interpretation.intent != LLMv2Intent.WORK:
            return
        raw_work = raw.get("work") if isinstance(raw.get("work"), dict) else {}
        if interpretation.work.quantity is None:
            if isinstance(raw_work.get("quantity"), str):
                try:
                    parsed = parse_persian_money(raw_work["quantity"])
                    if parsed is not None:
                        interpretation.work.quantity = Decimal(str(parsed))
                except (InvalidOperation, ValueError):
                    pass

    def _extract_amount_from_text(self, text: str) -> Decimal | None:
        amount = parse_persian_money(text)
        return Decimal(amount) if amount is not None else None
