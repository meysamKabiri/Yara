import os
import re
from decimal import Decimal
from time import perf_counter
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.feature_flags import get_financial_migration_mode
from app.core.governance.governance_context_builder import GovernanceContextBuilder
from app.core.governance.unified_governance_engine import UnifiedGovernanceEngine
from app.core.observability.decision_logger import (
    flush_decision_logs,
    queue_financial_decision,
    queue_shadow_decision,
)
from app.core.observability.performance_logger import record_pipeline_performance
from app.core.runtime.request_cache import RequestCache, new_request_cache
from app.core.validation.financial_validator import decimal_or_none
from app.dev_tools.semantic_firewall.firewall import (
    SemanticFirewallError,
    SemanticFirewallService,
)
from app.models.core import (
    FinancialDirection,
    PaymentType,
    PendingInterpretation,
    PendingInterpretationStatus,
    Project,
    Worker,
)
from app.schemas.llm_v2 import LLMv2FinancialDirection, LLMv2PaymentMethod
from app.services.llm_v2_interpreter import LLMv2Interpreter
from app.services.llm_v2_validator import LLMv2Validator, LLMv2ValidationError
from app.services.persian_money_engine import normalize_text
from app.services.persian_money_engine import parse_persian_money
from app.services.persian_role_extractor import PersianRoleExtractor
from app.services.semantic_normalizer import CanonicalEventType, SemanticNormalizerService


def process_input(
    db: Session,
    project_id: int,
    text: str,
    request_cache: RequestCache | None = None,
) -> list[PendingInterpretation]:
    cache = request_cache or new_request_cache()
    total_start = perf_counter()
    fallback_required = False
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    entity_context = list(db.scalars(select(Worker).where(Worker.project_id == project_id)))

    llm_v2_start = perf_counter()
    llm_v2_result = _safe_llm_v2_result(text, project_id)
    cache.set_timing("llm_v2_duration_ms", _elapsed_ms(llm_v2_start))

    llm_v2_valid = False
    validated_interpretation = None
    entity_resolutions: dict[int, Worker | None] = {}
    if not llm_v2_result.get("_llm_v2_failed"):
        try:
            validator = LLMv2Validator()
            validated_interpretation = validator.validate(llm_v2_result, entity_context)
            entity_resolutions = validator.resolve_entities(validated_interpretation, entity_context)
            llm_v2_valid = True
        except LLMv2ValidationError:
            llm_v2_valid = False

    if llm_v2_valid and validated_interpretation is not None:
        interpretations = _build_llm_v2_interpretations(
            project_id,
            text,
            validated_interpretation,
            entity_resolutions,
        )
        cache.set_timing("legacy_duration_ms", 0.0)
        cache.set_timing("governance_duration_ms", 0.0)
        _debug_print(
            "llm_v2_primary",
            {
                "intent": validated_interpretation.intent.value,
                "action": validated_interpretation.action.value,
                "entities": [e.name for e in validated_interpretation.entities],
                "entity_resolutions": {
                    str(i): w.name if w else None
                    for i, w in entity_resolutions.items()
                },
            },
        )
        for interpretation in interpretations:
            db.add(interpretation)
        db.commit()
        for interpretation in interpretations:
            db.refresh(interpretation)
        record_pipeline_performance(
            project_id=project_id,
            input_text=text,
            total_duration_ms=_elapsed_ms(total_start),
            legacy_duration_ms=0.0,
            shadow_duration_ms=cache.timings_ms.get("llm_v2_duration_ms", 0.0),
            governance_duration_ms=0.0,
            fallback_required=False,
        )
        return interpretations

    fallback_required = True
    _debug_print("llm_v2_fallback", {"reason": "LLM v2 invalid or failed"})

    profile_update = _build_profile_update_interpretation(project_id, text, entity_context)
    if profile_update is not None:
        db.add(profile_update)
        db.commit()
        db.refresh(profile_update)
        return [profile_update]

    legacy_start = perf_counter()
    graph = _extract_graph(text)
    canonical_event = SemanticNormalizerService().normalize(graph, text, entity_context)
    try:
        firewall_decision = SemanticFirewallService().validate(
            canonical_event,
            text,
            entity_context,
            graph,
        )
    except SemanticFirewallError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    canonical_event = firewall_decision.event
    legacy_interpretations = _build_legacy_pending_interpretations(
        project_id,
        text,
        graph,
        canonical_event,
        entity_context,
    )
    cache.set_legacy_result(_shadow_legacy_payload(legacy_interpretations))
    cache.set_timing("legacy_duration_ms", _elapsed_ms(legacy_start))
    interpretations = legacy_interpretations

    shadow_result: dict[str, Any] | None = llm_v2_result if not llm_v2_result.get("_llm_v2_failed") else None

    if canonical_event.type == CanonicalEventType.FINANCIAL and shadow_result is not None:
        governance_start = perf_counter()
        governance_context = GovernanceContextBuilder(db).build(
            event_type=canonical_event.type.value,
            legacy_result=_shadow_legacy_payload(legacy_interpretations),
            shadow_result=shadow_result,
            migration_mode=get_financial_migration_mode(),
        )
        governance = cache.set_governance_result(
            UnifiedGovernanceEngine(db).evaluate(
                {
                    **governance_context,
                    "event_type": canonical_event.type.value,
                    "shadow_result": shadow_result,
                    "legacy_result": _shadow_legacy_payload(legacy_interpretations),
                    "migration_mode": get_financial_migration_mode(),
                }
            )
        )
        cache.set_timing("governance_duration_ms", _elapsed_ms(governance_start))
        chosen_system = "LLM_V2" if llm_v2_valid else "LEGACY"
        queue_financial_decision(
            cache,
            project_id=project_id,
            input_text=text,
            legacy_json=_shadow_legacy_payload(legacy_interpretations),
            shadow_json=shadow_result,
            chosen_system=chosen_system,
            reason=governance["reason"] if llm_v2_valid else "LLM v2 primary fallback",
        )
    else:
        cache.set_timing("shadow_duration_ms", 0.0)
        cache.set_timing("governance_duration_ms", 0.0)

    for interpretation in interpretations:
        db.add(interpretation)
    flush_decision_logs(db, cache, log_type="financial")
    db.commit()
    for interpretation in interpretations:
        db.refresh(interpretation)

    _run_shadow_interpretation(db, project_id, text, _shadow_legacy_payload(legacy_interpretations), cache, shadow_result)
    record_pipeline_performance(
        project_id=project_id,
        input_text=text,
        total_duration_ms=_elapsed_ms(total_start),
        legacy_duration_ms=cache.timings_ms.get("legacy_duration_ms", 0.0),
        shadow_duration_ms=cache.timings_ms.get("llm_v2_duration_ms", 0.0),
        governance_duration_ms=cache.timings_ms.get("governance_duration_ms", 0.0),
        fallback_required=fallback_required,
    )
    return interpretations


def _build_llm_v2_interpretations(
    project_id: int,
    raw_text: str,
    interpretation: Any,
    entity_resolutions: dict[int, Worker | None],
) -> list[PendingInterpretation]:
    from app.schemas.llm_v2 import (
        LLMv2Action,
        LLMv2FinancialDirection,
        LLMv2Intent,
        LLMv2PaymentMethod,
    )

    intent_str = interpretation.intent.value
    action_str = interpretation.action.value
    _repair_llm_v2_setup_role_from_text(interpretation, raw_text)

    entities_json = []
    suggested_entity_id = None
    for i, entity in enumerate(interpretation.entities):
        project_role_str = entity.project_role.value if hasattr(entity.project_role, "value") else entity.project_role
        entity_dict = {
            "name": entity.name,
            "kind": entity.kind.value if hasattr(entity.kind, "value") else entity.kind,
            "project_role": project_role_str,
            "role_detail": entity.role_detail,
            "type": _llm_v2_project_role_to_worker_type(project_role_str),
        }
        if entity.phone is not None:
            entity_dict["phone"] = entity.phone
        if entity.account_number is not None:
            entity_dict["account_number"] = entity.account_number
        if entity.daily_rate is not None:
            entity_dict["daily_rate"] = str(entity.daily_rate)
        if entity.notes is not None:
            entity_dict["notes"] = entity.notes
        if entity.field_updates is not None:
            entity_dict["field_updates"] = entity.field_updates
        entities_json.append(entity_dict)
        if i == 0:
            resolved = entity_resolutions.get(i)
            if resolved is not None:
                suggested_entity_id = resolved.id

    financial_direction = _llm_v2_financial_direction(interpretation.financial.direction, interpretation.action, raw_text)
    canonical_type = _llm_v2_intent_to_canonical(intent_str)
    semantic_action = _llm_v2_action_to_semantic(action_str)
    payment_method = (
        _llm_v2_payment_method(interpretation.financial.payment_method, action_str)
        if canonical_type == "FINANCIAL_EVENT"
        else None
    )

    amount = interpretation.financial.amount
    parsed_text_amount = parse_persian_money(raw_text) if intent_str == "FINANCIAL" else None
    if parsed_text_amount is not None:
        amount = parsed_text_amount
        interpretation.financial.amount = Decimal(str(parsed_text_amount))
    if amount is not None:
        amount = Decimal(str(amount))

    quantity = interpretation.work.quantity
    if quantity is not None:
        quantity = Decimal(str(quantity))

    return [
        PendingInterpretation(
            project_id=project_id,
            raw_input_text=raw_text,
            canonical_event_type=canonical_type,
            semantic_action=semantic_action,
            suggested_entity_id=suggested_entity_id,
            matched_input_text=(
                interpretation.entities[0].name
                if interpretation.entities
                and suggested_entity_id is not None
                else None
            ),
            extracted_entities=entities_json or None,
            extracted_amount=amount,
            extracted_quantity=quantity,
            payment_method=payment_method,
            financial_direction=financial_direction,
            due_date=interpretation.financial.due_date_text,
            description=(
                interpretation.work.description
                or interpretation.note.text
                or interpretation.reasoning_summary
                or raw_text
            ),
            confidence=interpretation.confidence,
            structured_interpretation=_json_safe(interpretation.model_dump()),
            status=PendingInterpretationStatus.PENDING,
        )
    ]


def _build_profile_update_interpretation(
    project_id: int,
    raw_text: str,
    entity_context: list[Worker],
) -> PendingInterpretation | None:
    normalized = normalize_text(raw_text)
    updates: dict[str, str | int] = {}
    phone_match = re.search(r"09\d{9,12}", normalized.replace(" ", ""))
    if phone_match and any(term in normalized for term in ["شماره تماس", "شماره موبایل", "موبایل", "تلفن"]):
        updates["phone"] = phone_match.group()
    account_match = re.search(r"\d{8,26}", normalized.replace(" ", ""))
    if account_match and any(term in normalized for term in ["شماره حساب", "شماره کارت", "حساب", "کارت", "شبا"]):
        updates["account_number"] = account_match.group()
    if any(term in normalized for term in ["دستمزد روزانه", "روزی", "روزانه"]):
        amount = parse_persian_money(raw_text)
        if amount is None:
            number_match = re.search(r"\d{4,}", normalized.replace(" ", ""))
            amount = int(number_match.group()) if number_match is not None else None
        if amount is not None:
            updates["daily_rate"] = amount
    if not updates:
        return None

    entity = _best_profile_update_entity(normalized, entity_context)
    name = entity.name if entity is not None else _profile_update_name(raw_text, normalized, updates)
    if not name:
        return None
    entity_type = entity.type.value if entity is not None else "DAILY_WORKER"
    extracted_entity = {
        "name": name,
        "type": entity_type,
        "project_role": entity_type,
        "field_updates": updates,
        **updates,
    }
    return PendingInterpretation(
        project_id=project_id,
        raw_input_text=raw_text,
        canonical_event_type="SETUP_EVENT",
        semantic_action="ENTITY_UPDATE",
        suggested_entity_id=entity.id if entity is not None else None,
        matched_input_text=name if entity is not None else None,
        extracted_entities=[extracted_entity],
        extracted_amount=None,
        extracted_quantity=None,
        payment_method=None,
        financial_direction=None,
        due_date=None,
        description=raw_text,
        confidence=0.9,
        structured_interpretation=None,
        status=PendingInterpretationStatus.PENDING,
    )


def _best_profile_update_entity(normalized: str, entity_context: list[Worker]) -> Worker | None:
    matches = [worker for worker in entity_context if normalize_text(worker.name) in normalized]
    if len(matches) == 1:
        return matches[0]
    if matches:
        return max(matches, key=lambda worker: len(worker.name))
    return None


def _profile_update_name(raw_text: str, normalized: str, updates: dict[str, str | int]) -> str | None:
    text = normalized
    for value in updates.values():
        text = text.replace(str(value), " ")
    text = re.sub(r"شماره تماس|شماره موبایل|شماره حساب|شماره کارت|دستمزد روزانه|موبایل|تلفن|حساب|کارت|شبا|روزی|روزانه|است|می دیم|میدیم|به", " ", text)
    name = re.sub(r"\s+", " ", text).strip()
    return name or None


def _repair_llm_v2_setup_role_from_text(interpretation: Any, raw_text: str) -> None:
    from app.schemas.llm_v2 import LLMv2Action, LLMv2Intent, LLMv2ProjectRole

    if interpretation.intent != LLMv2Intent.SETUP or interpretation.action != LLMv2Action.ADD_ENTITY:
        return
    if not interpretation.entities:
        return
    extracted = PersianRoleExtractor().extract(raw_text)
    if extracted is None:
        return

    entity = interpretation.entities[0]
    normalized_entity = normalize_text(entity.name).replace("\u200c", " ")
    normalized_extracted = normalize_text(extracted.name).replace("\u200c", " ")
    if normalized_entity and normalized_entity not in normalized_extracted and normalized_extracted not in normalized_entity:
        return

    if extracted.worker_type.value in LLMv2ProjectRole.__members__:
        entity.project_role = LLMv2ProjectRole(extracted.worker_type.value)
        entity.role_detail = extracted.role_phrase


def _llm_v2_intent_to_canonical(intent: str) -> str:
    mapping = {
        "SETUP": "SETUP_EVENT",
        "WORK": "WORK_EVENT",
        "FINANCIAL": "FINANCIAL_EVENT",
        "NOTE": "NOTE_EVENT",
        "DOCUMENT": "NOTE_EVENT",
    }
    return mapping.get(intent, "NOTE_EVENT")


def _llm_v2_action_to_semantic(action: str) -> str:
    mapping = {
        "ADD_ENTITY": "SETUP",
        "UPDATE_ENTITY": "ENTITY_UPDATE",
        "WORK_LOG": "INCREMENT",
        "PAYMENT_IN": "PAYMENT",
        "PAYMENT_OUT": "PAYMENT",
        "PURCHASE_PAID": "PURCHASE_PAID",
        "DEBT_CREATED": "DEBT_CREATED",
        "CHECK_PAYMENT": "CHECK_PAYMENT",
        "NOTE": "NOTE",
    }
    return mapping.get(action, "NOTE")


def _llm_v2_project_role_to_worker_type(project_role: str) -> str:
    mapping = {
        "CLIENT": "CLIENT",
        "DAILY_WORKER": "DAILY_WORKER",
        "SKILLED_WORKER": "SKILLED_WORKER",
        "VENDOR": "VENDOR",
        "OTHER": "DAILY_WORKER",
    }
    return mapping.get(project_role, "DAILY_WORKER")


def _llm_v2_financial_direction(
    direction: Any,
    action: Any,
    raw_text: str,
) -> FinancialDirection | None:
    action_str = action.value if hasattr(action, "value") else (action or "")
    if action_str == "PURCHASE_PAID":
        return FinancialDirection.OUTGOING
    if action_str == "DEBT_CREATED":
        return FinancialDirection.DEBT
    if action_str in {"CHECK_PAYMENT"}:
        return FinancialDirection.DEFERRED
    if isinstance(direction, LLMv2FinancialDirection):
        direction = direction.value
    if direction == "IN":
        return FinancialDirection.INCOMING
    if direction == "OUT":
        return FinancialDirection.OUTGOING
    return None


def _llm_v2_payment_method(method: Any, action: str) -> str | None:
    if isinstance(method, LLMv2PaymentMethod):
        method = method.value
    if method in {"CASH", "BANK_TRANSFER", "CHECK", "OTHER"}:
        return method
    if action == "CHECK_PAYMENT":
        return PaymentType.CHECK.value
    if action == "PURCHASE_PAID":
        return PaymentType.CASH.value
    return PaymentType.BANK_TRANSFER.value


def _build_legacy_pending_interpretations(
    project_id: int,
    text: str,
    graph: dict[str, Any],
    canonical_event: Any,
    entity_context: list[Worker],
) -> list[PendingInterpretation]:
    from app.api.projects import _build_pending_interpretations

    return _build_pending_interpretations(project_id, text, graph, canonical_event, entity_context)


def _extract_graph(text: str) -> dict[str, Any]:
    from app.api import projects

    return projects.extract_graph(text)


def _llm_v2_interpreter() -> Any:
    from app.api import projects

    interpreter_class = getattr(projects, "LLMv2Interpreter", LLMv2Interpreter)
    return interpreter_class()


def _safe_llm_v2_result(input_text: str, project_id: int) -> dict[str, Any]:
    try:
        return _llm_v2_interpreter().interpret(input_text, project_id)
    except Exception:
        return {
            "intent": "NOTE",
            "action": "NOTE",
            "entities": [],
            "financial": {
                "amount": None, "direction": "NONE",
                "payment_method": None, "due_date_text": None,
            },
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": input_text},
            "confidence": 0.0,
            "ambiguity": True,
            "missing_fields": [],
            "reasoning_summary": "LLM v2 interpreter failed",
            "_llm_v2_failed": True,
        }


def _run_shadow_interpretation(
    db: Session,
    project_id: int,
    input_text: str,
    legacy_result: list[dict[str, Any]],
    cache: RequestCache,
    shadow_result: dict[str, Any] | None = None,
) -> None:
    try:
        if shadow_result is not None and shadow_result.get("_llm_v2_failed") is True:
            return
        if shadow_result is None:
            shadow_result = _safe_llm_v2_result(input_text, project_id)
            if shadow_result.get("_llm_v2_failed"):
                return
        queue_shadow_decision(
            cache,
            project_id=project_id,
            input_text=input_text,
            legacy_result=legacy_result,
            shadow_result=shadow_result,
        )
        flush_decision_logs(db, cache, log_type="shadow")
    except Exception:
        db.rollback()


def _shadow_legacy_payload(
    interpretations: list[PendingInterpretation],
) -> list[dict[str, Any]]:
    return [
        {
            "id": interpretation.id,
            "canonical_event_type": interpretation.canonical_event_type,
            "semantic_action": interpretation.semantic_action,
            "suggested_entity_id": interpretation.suggested_entity_id,
            "matched_input_text": interpretation.matched_input_text,
            "extracted_entities": interpretation.extracted_entities,
            "extracted_amount": interpretation.extracted_amount,
            "extracted_quantity": interpretation.extracted_quantity,
            "payment_method": interpretation.payment_method,
            "financial_direction": (
                interpretation.financial_direction.value
                if interpretation.financial_direction is not None
                else None
            ),
            "due_date": interpretation.due_date,
            "description": interpretation.description,
            "confidence": interpretation.confidence,
        }
        for interpretation in interpretations
    ]


def _elapsed_ms(start: float) -> float:
    return (perf_counter() - start) * 1000


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value


def _debug_print(label: str, payload: dict[str, Any]) -> None:
    if os.environ.get("YARA_DEBUG_MODE", "").lower() == "true":
        print(f"[YARA_DEBUG] {label}: {payload}")
