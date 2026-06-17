import os
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
from app.services.llm_v2_interpreter import LLMv2Interpreter
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

    legacy_start = perf_counter()
    graph = _extract_graph(text)
    entity_context = list(db.scalars(select(Worker).where(Worker.project_id == project_id)))
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
    interpretations = cache.set_legacy_result(
        _build_legacy_pending_interpretations(
            project_id,
            text,
            graph,
            canonical_event,
            entity_context,
        )
    )
    legacy_shadow_payload = _shadow_legacy_payload(interpretations)
    cache.set_timing("legacy_duration_ms", _elapsed_ms(legacy_start))
    shadow_result: dict[str, Any] | None = None

    if canonical_event.type == CanonicalEventType.FINANCIAL:
        shadow_start = perf_counter()
        shadow_result = _cached_shadow_result(cache, text, project_id)
        cache.set_timing("shadow_duration_ms", _elapsed_ms(shadow_start))
        governance_start = perf_counter()
        governance_context = GovernanceContextBuilder(db).build(
            event_type=canonical_event.type.value,
            legacy_result=legacy_shadow_payload,
            shadow_result=shadow_result,
            migration_mode=get_financial_migration_mode(),
        )
        governance = cache.set_governance_result(
            UnifiedGovernanceEngine(db).evaluate(
                {
                    **governance_context,
                    "event_type": canonical_event.type.value,
                    "shadow_result": shadow_result,
                    "legacy_result": legacy_shadow_payload,
                    "migration_mode": get_financial_migration_mode(),
                }
            )
        )
        cache.set_timing("governance_duration_ms", _elapsed_ms(governance_start))
        fallback_required = bool(governance["fallback_required"])
        _debug_print(
            "governance",
            {
                "event_type": canonical_event.type.value,
                "governance": governance,
                "legacy": legacy_shadow_payload,
                "shadow": shadow_result,
            },
        )
        chosen_system = "SHADOW" if governance["primary_source"] == "LLM" else "LEGACY"
        queue_financial_decision(
            cache,
            project_id=project_id,
            input_text=text,
            legacy_json=legacy_shadow_payload,
            shadow_json=shadow_result,
            chosen_system=chosen_system,
            reason=governance["reason"],
        )
        if chosen_system == "SHADOW":
            interpretations = _build_shadow_financial_interpretations(
                project_id,
                text,
                shadow_result,
                interpretations,
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

    _run_shadow_interpretation(db, project_id, text, legacy_shadow_payload, cache, shadow_result)
    record_pipeline_performance(
        project_id=project_id,
        input_text=text,
        total_duration_ms=_elapsed_ms(total_start),
        legacy_duration_ms=cache.timings_ms.get("legacy_duration_ms", 0.0),
        shadow_duration_ms=cache.timings_ms.get("shadow_duration_ms", 0.0),
        governance_duration_ms=cache.timings_ms.get("governance_duration_ms", 0.0),
        fallback_required=fallback_required,
    )
    return interpretations


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


def _safe_shadow_result(input_text: str, project_id: int) -> dict[str, Any]:
    try:
        return _llm_v2_interpreter().interpret(input_text, project_id)
    except Exception:
        return {
            "intent": "NOTE",
            "entities": [],
            "financial": {"amount": None, "direction": "NONE"},
            "work": {"quantity": None, "unit": None},
            "confidence": 0.0,
            "ambiguity": True,
            "missing_fields": [],
            "reasoning": "shadow financial interpreter failed",
            "_shadow_failed": True,
        }


def _cached_shadow_result(
    cache: RequestCache,
    input_text: str,
    project_id: int,
) -> dict[str, Any]:
    cached = cache.get_shadow_result()
    if cached is not None:
        return cached
    return cache.set_shadow_result(_safe_shadow_result(input_text, project_id))


def _run_shadow_interpretation(
    db: Session,
    project_id: int,
    input_text: str,
    legacy_result: list[dict[str, Any]],
    cache: RequestCache,
    shadow_result: dict[str, Any] | None = None,
) -> None:
    try:
        if shadow_result is not None and shadow_result.get("_shadow_failed") is True:
            return
        if shadow_result is None:
            shadow_start = perf_counter()
            shadow_result = _cached_shadow_result(cache, input_text, project_id)
            cache.set_timing("shadow_duration_ms", _elapsed_ms(shadow_start))
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


def _build_shadow_financial_interpretations(
    project_id: int,
    raw_text: str,
    shadow_result: dict[str, Any],
    legacy_interpretations: list[PendingInterpretation],
) -> list[PendingInterpretation]:
    base = legacy_interpretations[0] if legacy_interpretations else None
    financial = (
        shadow_result.get("financial")
        if isinstance(shadow_result.get("financial"), dict)
        else {}
    )
    amount = decimal_or_none(financial.get("amount"))
    direction = _shadow_financial_direction(financial.get("direction"), base)
    entity = _shadow_entity(shadow_result, base)
    return [
        PendingInterpretation(
            project_id=project_id,
            raw_input_text=raw_text,
            canonical_event_type=CanonicalEventType.FINANCIAL.value,
            semantic_action=base.semantic_action if base is not None else "PAYMENT",
            suggested_entity_id=base.suggested_entity_id if base is not None else None,
            matched_input_text=base.matched_input_text if base is not None else None,
            extracted_entities=[entity] if entity is not None else [],
            extracted_amount=amount,
            extracted_quantity=None,
            payment_method=(
                base.payment_method if base is not None else PaymentType.BANK_TRANSFER.value
            ),
            financial_direction=direction,
            due_date=base.due_date if base is not None else None,
            description=shadow_result.get("reasoning") or raw_text,
            semantic_explanation=base.semantic_explanation if base is not None else None,
            confidence=shadow_result.get("confidence")
            if isinstance(shadow_result.get("confidence"), int | float)
            else None,
            status=PendingInterpretationStatus.PENDING,
        )
    ]


def _shadow_entity(
    shadow_result: dict[str, Any],
    base: PendingInterpretation | None,
) -> dict[str, Any] | None:
    entities = shadow_result.get("entities")
    if isinstance(entities, list) and entities and isinstance(entities[0], dict):
        name = entities[0].get("name")
        if isinstance(name, str) and name.strip():
            base_entity = (base.extracted_entities or [{}])[0] if base is not None else {}
            entity_type = base_entity.get("type") if isinstance(base_entity, dict) else None
            return {"name": name.strip(), "type": entity_type or "VENDOR"}
    if base is not None and base.extracted_entities:
        return base.extracted_entities[0]
    return None


def _shadow_financial_direction(
    value: Any,
    base: PendingInterpretation | None,
) -> FinancialDirection:
    if base is not None and base.financial_direction is not None:
        return base.financial_direction
    if value == "IN":
        return FinancialDirection.INCOMING
    return FinancialDirection.OUTGOING


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


def _debug_print(label: str, payload: dict[str, Any]) -> None:
    if os.environ.get("YARA_DEBUG_MODE", "").lower() == "true":
        print(f"[YARA_DEBUG] {label}: {payload}")
