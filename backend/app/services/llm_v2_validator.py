import re
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import ValidationError

from app.models.core import Worker
from app.schemas.llm_v2 import (
    LLMv2Action,
    LLMv2FinancialDirection,
    LLMv2Intent,
    LLMv2Interpretation,
    LLMv2PaymentMethod,
)
from app.services.persian_money_engine import normalize_text, parse_persian_money


class LLMv2ValidationError(ValueError):
    def __init__(self, message: str, raw: dict[str, Any] | None = None):
        self.message = message
        self.raw = raw
        super().__init__(message)


def _normalize_match(value: str) -> str:
    normalized = normalize_text(value).replace("\u200c", " ").strip()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"^(مش|آقای|اقای|خانم)\s+", "", normalized)
    return normalized


def _resolve_entity(name: str, entity_context: list[Worker]) -> Worker | None:
    normalized = _normalize_match(name)
    if not normalized:
        return None
    buckets: list[list[Worker]] = [
        [w for w in entity_context if _normalize_match(w.name) == normalized],
        [w for w in entity_context if _normalize_match(w.name).startswith(normalized)],
        [
            w
            for w in entity_context
            if normalized in _normalize_match(w.name).split()
        ],
        [w for w in entity_context if normalized in _normalize_match(w.name)],
    ]
    for matches in buckets:
        unique = {worker.id: worker for worker in matches}
        if len(unique) == 1:
            return next(iter(unique.values()))
        if len(unique) > 1:
            return None
    return None


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

        self._validate_action_intent_consistency(interpretation)
        self._validate_financial_fields(interpretation)
        self._validate_work_fields(interpretation, raw)

        return interpretation

    def resolve_entities(
        self,
        interpretation: LLMv2Interpretation,
        entity_context: list[Worker],
    ) -> dict[int, Worker | None]:
        return {
            i: _resolve_entity(entity.name, entity_context)
            for i, entity in enumerate(interpretation.entities)
        }

    def normalize_amount(self, raw_value: Any, raw_text: str | None = None) -> Decimal | None:
        if isinstance(raw_value, int | float) and not isinstance(raw_value, bool):
            return Decimal(str(raw_value))
        if isinstance(raw_value, str):
            try:
                raw_clean = raw_value.replace(",", "").replace("،", "")
                if raw_clean.isdigit() or (raw_clean.startswith("-") and raw_clean[1:].isdigit()):
                    return Decimal(raw_clean)
                amount = parse_persian_money(raw_value)
                if amount is not None:
                    return Decimal(amount)
            except (InvalidOperation, ValueError):
                pass
        if raw_text:
            return self._extract_amount_from_text(raw_text)
        return None

    def normalize_quantity(self, raw_value: Any) -> Decimal | None:
        if isinstance(raw_value, int | float) and not isinstance(raw_value, bool):
            return Decimal(str(raw_value))
        return None

    def _validate_action_intent_consistency(self, interpretation: LLMv2Interpretation) -> None:
        intent_action_map = {
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
        normalized = normalize_text(text)
        patterns = [
            r"(\d+(?:\.\d+)?)\s*(?:میلیون|ملیون|میلیارد|هزار|تومان)",
            r"(?:میلیون|ملیون|میلیارد|هزار|تومان)\s*(\d+(?:\.\d+)?)",
        ]
        for pattern in patterns:
            match = re.search(pattern, normalized)
            if match is not None:
                try:
                    return Decimal(match.group(1))
                except (InvalidOperation, ValueError):
                    pass
        return None
