import inspect
import logging
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
from app.core.llm_cache import get_llm_cache, llm_cache_key, set_llm_cache
from app.core.observability_service import track_event
from app.core.observability.decision_logger import (
    flush_decision_logs,
    queue_financial_decision,
    queue_shadow_decision,
)

from app.core.observability.performance_logger import record_pipeline_performance
from app.core.runtime.request_cache import RequestCache, new_request_cache
from app.core.trace_context import get_job_id, get_trace_id
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
from app.services.llm_v2_validator import LLMv2Validator, LLMv2ValidationError, resolve_candidates
from app.services.persian_money_engine import normalize_text
from app.services.persian_money_engine import parse_persian_money
from app.services.persian_project_payment import detect_incoming_project_payment
from app.services.persian_project_payment import detect_purchase_payment
from app.services.persian_role_extractor import PersianRoleExtractor
from app.services.semantic_normalizer import CanonicalEventType, SemanticNormalizerService

logger = logging.getLogger(__name__)


def _emit_event(db: Session, event_name, payload=None, duration_ms=None):
    try:
        trace_id = get_trace_id()
        if trace_id:
            track_event(db=db, trace_id=trace_id, event_name=event_name, payload=payload, duration_ms=duration_ms)
    except Exception:
        pass


def _emit_multi_event_split_applied(db: Session, chunks: list[str]) -> None:
    _emit_event(db, "MULTI_EVENT_SPLIT_APPLIED", {
        "chunk_count": len(chunks),
        "chunks": [
            {"chunk_index": index, "chunk_text": chunk}
            for index, chunk in enumerate(chunks)
        ],
    })


def _emit_chunk_processed(
    db: Session,
    chunk_index: int,
    chunk_text: str,
    processing_path: str,
) -> None:
    _emit_event(db, "MULTI_EVENT_CHUNK_PROCESSED", {
        "chunk_index": chunk_index,
        "chunk_text": chunk_text,
        "processing_path": processing_path,
    })


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
    chunks = _split_multi_event_text(text)
    split_attempted = False

    if len(chunks) > 1:
        split_attempted = True
        _emit_multi_event_split_applied(db, chunks)
        interpretations = _process_split_fallback_chunks(
            db,
            project_id,
            text,
            chunks,
            entity_context,
            cache,
            total_start,
        )
        if interpretations:
            return interpretations

    fast_profile_update = None if len(chunks) > 1 else _build_profile_update_interpretation(project_id, text, entity_context)
    if fast_profile_update is not None and not _is_phone_or_account_update(fast_profile_update):
        fast_profile_update = None
    if fast_profile_update is not None:
        _emit_fast_path_started(db, fast_profile_update)
        db.add(fast_profile_update)
        db.commit()
        db.refresh(fast_profile_update)
        cache.set_timing("llm_v2_duration_ms", 0.0)
        cache.set_timing("legacy_duration_ms", 0.0)
        cache.set_timing("governance_duration_ms", 0.0)
        _emit_fast_path_matched(db, fast_profile_update)
        _emit_event(db, "PENDING_INTERPRETATION_SAVED", {
            "interpretation_count": 1,
            "path": "fast_profile_update",
            "fast_path_type": _fast_path_type(fast_profile_update),
            "skipped_llm": True,
        })
        record_pipeline_performance(
            project_id=project_id,
            input_text=text,
            total_duration_ms=_elapsed_ms(total_start),
            legacy_duration_ms=0.0,
            shadow_duration_ms=0.0,
            governance_duration_ms=0.0,
            fallback_required=False,
        )
        return [fast_profile_update]

    fast_financial_payment = None if len(chunks) > 1 else _build_financial_payment_fast_path_interpretation(
        project_id,
        text,
        entity_context,
    )
    if fast_financial_payment is not None:
        _emit_fast_path_started(db, fast_financial_payment)
        db.add(fast_financial_payment)
        db.commit()
        db.refresh(fast_financial_payment)
        cache.set_timing("llm_v2_duration_ms", 0.0)
        cache.set_timing("legacy_duration_ms", 0.0)
        cache.set_timing("governance_duration_ms", 0.0)
        _emit_fast_path_matched(db, fast_financial_payment)
        _emit_event(db, "PENDING_INTERPRETATION_SAVED", {
            "interpretation_count": 1,
            "path": "fast_financial_payment",
            "fast_path_type": _fast_path_type(fast_financial_payment),
            "skipped_llm": True,
        })
        record_pipeline_performance(
            project_id=project_id,
            input_text=text,
            total_duration_ms=_elapsed_ms(total_start),
            legacy_duration_ms=0.0,
            shadow_duration_ms=0.0,
            governance_duration_ms=0.0,
            fallback_required=False,
        )
        return [fast_financial_payment]

    fast_setup = None if len(chunks) > 1 else _build_role_assignment_interpretation(project_id, text, entity_context)
    if fast_setup is not None:
        db.add(fast_setup)
        db.commit()
        db.refresh(fast_setup)
        cache.set_timing("llm_v2_duration_ms", 0.0)
        cache.set_timing("legacy_duration_ms", 0.0)
        cache.set_timing("governance_duration_ms", 0.0)
        _emit_event(db, "PENDING_INTERPRETATION_SAVED", {
            "interpretation_count": 1,
            "path": "fast_setup",
        })
        record_pipeline_performance(
            project_id=project_id,
            input_text=text,
            total_duration_ms=_elapsed_ms(total_start),
            legacy_duration_ms=0.0,
            shadow_duration_ms=0.0,
            governance_duration_ms=0.0,
            fallback_required=False,
        )
        return [fast_setup]

    llm_v2_start = perf_counter()
    llm_v2_result = _safe_llm_v2_result(text, project_id, cache, db=db)
    cache.set_timing("llm_v2_duration_ms", _elapsed_ms(llm_v2_start))

    llm_v2_valid = False
    validated_interpretations: list[Any] = []
    if not llm_v2_result.get("_llm_v2_failed"):
        try:
            validator = LLMv2Validator()
            if "events" in llm_v2_result:
                validated_interpretations = validator.validate_multi(llm_v2_result, entity_context)
            else:
                single = validator.validate(llm_v2_result, entity_context)
                validated_interpretations = [single]
            llm_v2_valid = True
        except LLMv2ValidationError:
            llm_v2_valid = False

    if llm_v2_valid and validated_interpretations:
        interpretations = _build_llm_v2_interpretations(
            project_id,
            text,
            validated_interpretations,
            entity_context,
        )
        cache.set_timing("legacy_duration_ms", 0.0)
        cache.set_timing("governance_duration_ms", 0.0)
        for vi in validated_interpretations:
            _debug_print(
                "llm_v2_primary",
                {
                    "intent": vi.intent.value,
                    "action": vi.action.value,
                    "entities": [e.name for e in vi.entities],
                },
            )
        for interpretation in interpretations:
            db.add(interpretation)
        db.commit()
        for interpretation in interpretations:
            db.refresh(interpretation)
        _emit_event(db, "PENDING_INTERPRETATION_SAVED", {
            "interpretation_count": len(interpretations),
            "path": "llm_v2_primary",
        })
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

    if len(chunks) > 1:
        if not split_attempted:
            _emit_multi_event_split_applied(db, chunks)
        interpretations = _process_split_fallback_chunks(
            db,
            project_id,
            text,
            chunks,
            entity_context,
            cache,
            total_start,
        )
        if interpretations:
            return interpretations

    profile_update = _build_profile_update_interpretation(project_id, text, entity_context)
    if profile_update is not None:
        db.add(profile_update)
        db.commit()
        db.refresh(profile_update)
        _emit_event(db, "PENDING_INTERPRETATION_SAVED", {
            "interpretation_count": 1,
            "path": "profile_update",
        })
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
    _block_ambiguous_setup_creations(legacy_interpretations, entity_context)
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

    _emit_event(db, "PENDING_INTERPRETATION_SAVED", {
        "interpretation_count": len(interpretations),
        "path": "legacy",
    })

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


def _process_split_fallback_chunks(
    db: Session,
    project_id: int,
    raw_text: str,
    chunks: list[str],
    entity_context: list[Worker],
    cache: RequestCache,
    total_start: float,
) -> list[PendingInterpretation]:
    interpretations: list[PendingInterpretation] = []
    legacy_duration_ms = 0.0
    llm_duration_ms = cache.timings_ms.get("llm_v2_duration_ms", 0.0)

    for chunk_index, chunk in enumerate(chunks):
        profile_update = _build_profile_update_interpretation(project_id, chunk, entity_context)
        if profile_update is not None and _is_phone_or_account_update(profile_update):
            _emit_fast_path_started(db, profile_update)
            _retarget_interpretation_to_raw_text(profile_update, raw_text, chunk)
            interpretations.append(profile_update)
            _emit_fast_path_matched(db, profile_update)
            _emit_chunk_processed(db, chunk_index, chunk, "FAST_PATH")
            continue

        fast_financial_payment = _build_financial_payment_fast_path_interpretation(project_id, chunk, entity_context)
        if fast_financial_payment is not None:
            _emit_fast_path_started(db, fast_financial_payment)
            _retarget_interpretation_to_raw_text(fast_financial_payment, raw_text, chunk)
            interpretations.append(fast_financial_payment)
            _emit_fast_path_matched(db, fast_financial_payment)
            _emit_chunk_processed(db, chunk_index, chunk, "FAST_PATH")
            continue

        chunk_llm_start = perf_counter()
        chunk_llm_result = _safe_llm_v2_result(
            chunk,
            project_id,
            cache,
            db=db,
            event_payload={"chunk_index": chunk_index, "chunk_text": chunk},
        )
        llm_duration_ms += _elapsed_ms(chunk_llm_start)
        chunk_interpretations = _validated_llm_v2_chunk_interpretations(
            project_id,
            raw_text,
            chunk,
            chunk_llm_result,
            entity_context,
        )
        if chunk_interpretations:
            interpretations.extend(chunk_interpretations)
            _emit_chunk_processed(db, chunk_index, chunk, "LLM")
            continue

        profile_update = _build_profile_update_interpretation(project_id, chunk, entity_context)
        if profile_update is not None:
            _retarget_interpretation_to_raw_text(profile_update, raw_text, chunk)
            interpretations.append(profile_update)
            _emit_chunk_processed(db, chunk_index, chunk, "FALLBACK")
            continue

        fast_setup = _build_role_assignment_interpretation(project_id, chunk, entity_context)
        if fast_setup is not None:
            _retarget_interpretation_to_raw_text(fast_setup, raw_text, chunk)
            interpretations.append(fast_setup)
            _emit_chunk_processed(db, chunk_index, chunk, "FALLBACK")
            continue

        legacy_start = perf_counter()
        graph = _extract_graph(chunk)
        canonical_event = SemanticNormalizerService().normalize(graph, chunk, entity_context)
        try:
            firewall_decision = SemanticFirewallService().validate(
                canonical_event,
                chunk,
                entity_context,
                graph,
            )
        except SemanticFirewallError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        canonical_event = firewall_decision.event
        chunk_legacy = _build_legacy_pending_interpretations(
            project_id,
            chunk,
            graph,
            canonical_event,
            entity_context,
        )
        _block_ambiguous_setup_creations(chunk_legacy, entity_context)
        for interpretation in chunk_legacy:
            _retarget_interpretation_to_raw_text(interpretation, raw_text, chunk)
        interpretations.extend(chunk_legacy)
        legacy_duration_ms += _elapsed_ms(legacy_start)
        _emit_chunk_processed(db, chunk_index, chunk, "FALLBACK")

    if not interpretations:
        return []

    cache.set_timing("llm_v2_duration_ms", llm_duration_ms)
    cache.set_timing("legacy_duration_ms", legacy_duration_ms)
    cache.set_timing("governance_duration_ms", 0.0)
    cache.set_legacy_result(_shadow_legacy_payload(interpretations))

    for interpretation in interpretations:
        db.add(interpretation)
    db.commit()
    for interpretation in interpretations:
        db.refresh(interpretation)

    _emit_event(db, "PENDING_INTERPRETATION_SAVED", {
        "interpretation_count": len(interpretations),
        "path": "split_fallback",
    })
    record_pipeline_performance(
        project_id=project_id,
        input_text=raw_text,
        total_duration_ms=_elapsed_ms(total_start),
        legacy_duration_ms=legacy_duration_ms,
        shadow_duration_ms=llm_duration_ms,
        governance_duration_ms=0.0,
        fallback_required=True,
    )
    return interpretations


def _validated_llm_v2_chunk_interpretations(
    project_id: int,
    raw_text: str,
    chunk: str,
    llm_v2_result: dict[str, Any],
    entity_context: list[Worker],
) -> list[PendingInterpretation]:
    if llm_v2_result.get("_llm_v2_failed"):
        return []
    try:
        validator = LLMv2Validator()
        if "events" in llm_v2_result:
            validated = validator.validate_multi(llm_v2_result, entity_context)
            validated = [
                interpretation
                for interpretation in validated
                if _llm_v2_event_belongs_to_chunk(interpretation, chunk)
            ]
        else:
            validated = [validator.validate(llm_v2_result, entity_context)]
            if not _llm_v2_event_belongs_to_chunk(validated[0], chunk):
                return []
    except LLMv2ValidationError:
        return []
    interpretations = _build_llm_v2_interpretations(project_id, chunk, validated, entity_context)
    for interpretation in interpretations:
        _retarget_interpretation_to_raw_text(interpretation, raw_text, chunk)
        if interpretation.matched_input_text is None:
            interpretation.matched_input_text = chunk
    return interpretations


def _llm_v2_event_belongs_to_chunk(interpretation: Any, chunk: str) -> bool:
    chunk_normalized = normalize_text(chunk).replace("\u200c", " ")
    matched_text = getattr(interpretation, "matched_text", None)
    if isinstance(matched_text, str) and matched_text.strip():
        matched_normalized = normalize_text(matched_text).replace("\u200c", " ")
        if matched_normalized in chunk_normalized or chunk_normalized in matched_normalized:
            return True

    entities = getattr(interpretation, "entities", []) or []
    entity_names = [
        normalize_text(entity.name).replace("\u200c", " ")
        for entity in entities
        if getattr(entity, "name", None)
    ]
    has_entity_match = any(name and name in chunk_normalized for name in entity_names)
    if not has_entity_match:
        return False

    chunk_amount = parse_persian_money(chunk)
    interpretation_amount = getattr(getattr(interpretation, "financial", None), "amount", None)
    if chunk_amount is not None and interpretation_amount is not None:
        return Decimal(str(chunk_amount)) == Decimal(str(interpretation_amount))

    quantity = getattr(getattr(interpretation, "work", None), "quantity", None)
    if quantity is not None:
        return str(quantity) in chunk_normalized

    return chunk_amount is None and interpretation_amount is None


def _retarget_interpretation_to_raw_text(
    interpretation: PendingInterpretation,
    raw_text: str,
    chunk: str,
) -> None:
    interpretation.raw_input_text = raw_text
    interpretation.matched_input_text = chunk


def _is_role_compatible(worker_type: str, expected_role: str | None) -> bool:
    if expected_role is None or expected_role == "OTHER":
        return True
    if expected_role == "VENDOR" and worker_type == "VENDOR":
        return True
    if expected_role == "CLIENT" and worker_type == "CLIENT":
        return True
    if worker_type == expected_role:
        return True
    return False


def _expected_financial_role(
    entities_json: list[dict[str, Any]] | None,
    semantic_action: str | None,
    financial_direction: Any,
) -> str | None:
    if not entities_json:
        return None
    first = entities_json[0]
    role = first.get("project_role") or first.get("type")
    if role:
        return role
    if semantic_action in ("PURCHASE_PAID", "PURCHASE", "PURCHASE_UNPAID"):
        return "VENDOR"
    if financial_direction == FinancialDirection.INCOMING:
        return "CLIENT"
    return None


def _resolve_financial_counterparty(
    entities_json: list[dict[str, Any]] | None,
    entity_context: list[Worker],
    canonical_type: str,
    semantic_action: str | None,
    financial_direction: Any,
) -> int | None:
    if canonical_type != "FINANCIAL_EVENT" or not entities_json:
        return None
    first = entities_json[0]
    candidates = first.get("candidate_matches")
    if not isinstance(candidates, list):
        candidates = []
    expected_role = _expected_financial_role(entities_json, semantic_action, financial_direction)
    entity_name = first.get("name")
    if isinstance(entity_name, str):
        entity_name = entity_name.strip()
    else:
        entity_name = ""

    clients = [w for w in entity_context if w.type.value == "CLIENT"]

    # 1. exact match + role compatible
    for c in candidates:
        if (
            isinstance(c, dict)
            and c.get("match_type") == "exact"
            and isinstance(c.get("person_id"), int)
        ):
            worker = next((w for w in entity_context if w.id == c["person_id"]), None)
            if worker is not None and _is_role_compatible(worker.type.value, expected_role):
                return worker.id

    # 2. single role-compatible partial >= 0.75
    viable = []
    for c in candidates:
        if not isinstance(c, dict) or not isinstance(c.get("person_id"), int):
            continue
        score = c.get("score", 0)
        if not isinstance(score, (int, float)):
            continue
        worker = next((w for w in entity_context if w.id == c["person_id"]), None)
        if worker is not None and _is_role_compatible(worker.type.value, expected_role):
            viable.append((c, worker, score))
    if len(viable) == 1:
        _, worker, score = viable[0]
        if score >= 0.75:
            return worker.id

    # 3. CLIENT rule: partial >= 0.60 when exactly one project client
    if expected_role == "CLIENT" and len(clients) == 1:
        client = clients[0]
        client_in_candidates = any(c.get("person_id") == client.id for c in candidates)
        if client_in_candidates:
            return client.id
        if entity_name:
            from app.services.entity_normalizer import match_score
            if match_score(entity_name, client.name) >= 0.60:
                return client.id

    # 4. exact name match in entity_context (role-compatible)
    if entity_name:
        name_match = next(
            (w for w in entity_context if w.name == entity_name and _is_role_compatible(w.type.value, expected_role)),
            None,
        )
        if name_match is not None:
            return name_match.id

    return None


def _build_llm_v2_interpretations(
    project_id: int,
    raw_text: str,
    interpretations: list[Any],
    entity_context: list[Worker],
) -> list[PendingInterpretation]:
    results: list[PendingInterpretation] = []
    for interpretation in interpretations:
        event_text = getattr(interpretation, "matched_text", None) or raw_text
        pi = _build_one_llm_v2_interpretation(
            project_id, raw_text, interpretation, entity_context, event_text,
        )
        if pi is not None:
            results.append(pi)
    return results


def _build_one_llm_v2_interpretation(
    project_id: int,
    raw_text: str,
    interpretation: Any,
    entity_context: list[Worker],
    event_text: str,
) -> PendingInterpretation | None:
    from app.schemas.llm_v2 import (
        LLMv2Action,
        LLMv2FinancialDirection,
        LLMv2Intent,
        LLMv2PaymentMethod,
    )

    _repair_llm_v2_setup_role_from_text(interpretation, raw_text)
    incoming_project_payment = detect_incoming_project_payment(event_text)
    purchase_payment = detect_purchase_payment(event_text)

    entities_json: list[dict[str, Any]] = []
    blocked_due_to_ambiguity = False
    for i, entity in enumerate(interpretation.entities):
        project_role_str = entity.project_role.value if hasattr(entity.project_role, "value") else entity.project_role
        resolution = resolve_candidates(entity.name, entity_context)
        entity_dict: dict[str, Any] = {
            "name": entity.name,
            "kind": entity.kind.value if hasattr(entity.kind, "value") else entity.kind,
            "project_role": project_role_str,
            "role_detail": entity.role_detail,
            "type": _llm_v2_project_role_to_worker_type(project_role_str),
        }
        if interpretation.intent == LLMv2Intent.SET_ROLE and resolution["candidates"]:
            entity_dict["requires_confirmation"] = True
            entity_dict["candidate_matches"] = resolution["candidates"]
        has_profile_fields = bool(
            isinstance(entity.field_updates, dict) and entity.field_updates
            or entity.phone is not None
            or entity.account_number is not None
            or entity.daily_rate is not None
            or entity.notes is not None
        )
        if interpretation.intent == LLMv2Intent.SETUP and resolution["candidates"]:
            if has_profile_fields:
                entity_dict["requires_confirmation"] = True
                entity_dict["candidate_matches"] = resolution["candidates"]
            elif resolution["requires_confirmation"]:
                _mark_entity_creation_blocked(entity_dict, raw_text, resolution["candidates"])
                blocked_due_to_ambiguity = True
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

    _coerce_llm_v2_profile_update_action(interpretation)
    if blocked_due_to_ambiguity:
        interpretation.ambiguity = True
        if "entity_requires_confirmation" not in interpretation.missing_fields:
            interpretation.missing_fields.append("entity_requires_confirmation")
    intent_str = interpretation.intent.value
    action_str = interpretation.action.value

    financial_direction = _llm_v2_financial_direction(interpretation.financial.direction, interpretation.action, event_text)
    canonical_type = _llm_v2_intent_to_canonical(intent_str)
    semantic_action = _llm_v2_action_to_semantic(action_str)
    if incoming_project_payment is not None:
        canonical_type = "FINANCIAL_EVENT"
        semantic_action = "PAYMENT"
        financial_direction = FinancialDirection.INCOMING
        interpretation.financial.direction = LLMv2FinancialDirection.IN
        if not entities_json:
            entities_json = [
                {
                    "name": incoming_project_payment.payer_name,
                    "kind": "PERSON",
                    "project_role": "CLIENT",
                    "role_detail": None,
                    "type": "CLIENT",
                }
            ]
        else:
            entities_json[0] = {
                **entities_json[0],
                "name": incoming_project_payment.payer_name,
                "project_role": "CLIENT",
                "type": "CLIENT",
            }
        resolution = resolve_candidates(incoming_project_payment.payer_name, entity_context)
        if resolution["candidates"]:
            entities_json[0]["requires_confirmation"] = True
            entities_json[0]["candidate_matches"] = resolution["candidates"]
    elif purchase_payment is not None:
        canonical_type = "FINANCIAL_EVENT"
        if action_str not in {"DEBT_CREATED", "CHECK_PAYMENT"} and "نسیه" not in normalize_text(event_text) and "چک" not in normalize_text(event_text):
            semantic_action = "PURCHASE_PAID"
            financial_direction = FinancialDirection.OUTGOING
        if purchase_payment.vendor_name is not None:
            if not entities_json:
                entities_json = [
                    {
                        "name": purchase_payment.vendor_name,
                        "kind": "COMPANY",
                        "project_role": "VENDOR",
                        "role_detail": None,
                        "type": "VENDOR",
                    }
                ]
            else:
                entities_json[0] = {
                    **entities_json[0],
                    "name": purchase_payment.vendor_name,
                    "project_role": "VENDOR",
                    "type": "VENDOR",
                }
        elif entities_json:
            entities_json[0] = {**entities_json[0], "project_role": "VENDOR", "type": "VENDOR"}

    _repair_outgoing_unknown_counterparty_role(
        entities_json,
        canonical_type,
        semantic_action,
        financial_direction,
        event_text,
    )

    if canonical_type == "FINANCIAL_EVENT" and entities_json and "candidate_matches" not in entities_json[0]:
        fin_name = entities_json[0].get("name")
        if isinstance(fin_name, str) and fin_name.strip():
            fin_resolution = resolve_candidates(fin_name.strip(), entity_context)
            if fin_resolution["candidates"]:
                entities_json[0]["candidate_matches"] = fin_resolution["candidates"]

    payment_method = (
        _llm_v2_payment_method(interpretation.financial.payment_method, action_str)
        if canonical_type == "FINANCIAL_EVENT"
        else None
    )
    if incoming_project_payment is not None:
        payment_method = PaymentType.BANK_TRANSFER.value
    elif purchase_payment is not None:
        payment_method = payment_method or PaymentType.CASH.value

    amount = interpretation.financial.amount
    parsed_text_amount = parse_persian_money(event_text) if intent_str == "FINANCIAL" else None
    if incoming_project_payment is not None and incoming_project_payment.amount is not None:
        parsed_text_amount = incoming_project_payment.amount
    elif purchase_payment is not None and purchase_payment.amount is not None:
        parsed_text_amount = purchase_payment.amount
    if parsed_text_amount is not None:
        amount = parsed_text_amount
        interpretation.financial.amount = Decimal(str(parsed_text_amount))
    if amount is not None:
        amount = Decimal(str(amount))

    suggested_entity_id = _resolve_financial_counterparty(
        entities_json, entity_context, canonical_type, semantic_action, financial_direction
    )

    quantity = interpretation.work.quantity
    if quantity is not None:
        quantity = Decimal(str(quantity))

    matched_text = getattr(interpretation, "matched_text", None)

    return PendingInterpretation(
        project_id=project_id,
        raw_input_text=raw_text,
        canonical_event_type=canonical_type,
        semantic_action=semantic_action,
        suggested_entity_id=suggested_entity_id,
        matched_input_text=matched_text,
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
            or event_text
        ),
        confidence=interpretation.confidence,
        structured_interpretation=_json_safe(interpretation.model_dump()),
        status=PendingInterpretationStatus.PENDING,
    )


def _repair_outgoing_unknown_counterparty_role(
    entities_json: list[dict[str, Any]],
    canonical_type: str,
    semantic_action: str | None,
    financial_direction: Any,
    raw_text: str,
) -> None:
    if (
        canonical_type != "FINANCIAL_EVENT"
        or semantic_action != "PAYMENT"
        or financial_direction != FinancialDirection.OUTGOING
        or not entities_json
    ):
        return
    first = entities_json[0]
    role = first.get("project_role") or first.get("type")
    if role != "CLIENT" or _has_explicit_client_role_evidence(raw_text):
        return
    first["project_role"] = "OTHER"
    first["type"] = "OTHER"


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


def _block_ambiguous_setup_creations(
    interpretations: list[PendingInterpretation],
    entity_context: list[Worker],
) -> None:
    for interpretation in interpretations:
        if (
            interpretation.canonical_event_type != "SETUP_EVENT"
            or interpretation.semantic_action != "SETUP"
            or interpretation.suggested_entity_id is not None
        ):
            continue
        entities = interpretation.extracted_entities or []
        if not entities:
            continue
        entity = entities[0]
        name = entity.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        resolution = resolve_candidates(name, entity_context)
        if not resolution["requires_confirmation"]:
            continue
        _mark_entity_creation_blocked(entity, interpretation.raw_input_text, resolution["candidates"])
        interpretation.extracted_entities = entities


def _mark_entity_creation_blocked(
    entity: dict[str, Any],
    raw_text: str,
    candidates: list[dict[str, Any]],
) -> None:
    entity["requires_confirmation"] = True
    entity["creation_block_reason"] = "entity_creation_blocked_due_to_ambiguity"
    entity["candidate_matches"] = candidates
    entity["type"] = "OTHER"
    entity["project_role"] = "OTHER"
    entity["role_detail"] = None
    logger.info(
        "entity_creation_blocked_due_to_ambiguity",
        extra={
            "input_text": raw_text,
            "entity_name": entity.get("name"),
            "candidates": candidates,
        },
    )


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

    raw_name = _profile_update_name(raw_text, normalized, updates)
    name = raw_name or _profile_update_name(raw_text, normalized, updates)
    if not name:
        return None
    resolution = resolve_candidates(name, entity_context)
    role = "DAILY_WORKER" if "daily_rate" in updates else "OTHER"
    extracted_entity = {
        "name": name,
        "kind": "PERSON",
        "type": role,
        "project_role": role,
        "role_detail": None,
        "phone": updates.get("phone"),
        "account_number": updates.get("account_number"),
        "daily_rate": updates.get("daily_rate"),
        "notes": None,
        "field_updates": updates,
    }
    if resolution["candidates"]:
        extracted_entity["requires_confirmation"] = True
        extracted_entity["candidate_matches"] = resolution["candidates"]
    structured = _profile_update_structured_interpretation(name, role, updates)
    return PendingInterpretation(
        project_id=project_id,
        raw_input_text=raw_text,
        canonical_event_type="SETUP_EVENT",
        semantic_action="ENTITY_UPDATE",
        suggested_entity_id=None,
        matched_input_text=None,
        extracted_entities=[extracted_entity],
        extracted_amount=None,
        extracted_quantity=None,
        payment_method=None,
        financial_direction=None,
        due_date=None,
        description=raw_text,
        confidence=0.95,
        structured_interpretation=structured,
        status=PendingInterpretationStatus.PENDING,
    )


def _profile_update_structured_interpretation(
    name: str,
    role: str,
    updates: dict[str, str | int],
) -> dict[str, Any] | None:
    if "phone" not in updates and "account_number" not in updates:
        return None
    structured_entity = {
        "name": name,
        "kind": "PERSON",
        "project_role": role,
        "role_detail": None,
        "phone": updates.get("phone"),
        "account_number": updates.get("account_number"),
        "daily_rate": None,
        "notes": None,
        "field_updates": updates,
    }
    return {
        "intent": "SETUP",
        "action": "UPDATE_ENTITY",
        "entities": [structured_entity],
        "financial": {
            "amount": None,
            "direction": "NONE",
            "payment_method": None,
            "due_date_text": None,
        },
        "work": {"quantity": None, "unit": None, "description": None},
        "note": {"text": None},
        "confidence": 0.95,
        "ambiguity": False,
        "missing_fields": [],
        "reasoning_summary": "deterministic profile update fast path",
    }


_PERSIAN_AMOUNT_MARKER = (
    r"(?:\d|[۰-۹]|[٠-٩]|یک|دو|سه|چهار|پنج|شش|هفت|هشت|نه|ده|"
    r"یازده|دوازده|سیزده|چهارده|پانزده|شانزده|هفده|هجده|نوزده|"
    r"بیست|سی|چهل|پنجاه|شصت|هفتاد|هشتاد|نود|صد|هزار|میلیون|میلیارد)"
)


def _build_financial_payment_fast_path_interpretation(
    project_id: int,
    raw_text: str,
    entity_context: list[Worker],
) -> PendingInterpretation | None:
    normalized = normalize_text(raw_text)
    amount = parse_persian_money(raw_text)
    if amount is None:
        return None
    if any(separator in normalized for separator in [".", "۔", "؟", "!", "؛"]):
        return None
    if any(term in normalized for term in ["پروژه", "حساب پروژه"]):
        return None
    if detect_purchase_payment(raw_text) is not None or any(term in normalized for term in ["خرید", "خریدم", "خرید کردم"]):
        return None

    direction = _financial_payment_fast_path_direction(normalized)
    if direction is None:
        return None
    name = _financial_payment_fast_path_name(normalized, direction)
    if name is None:
        return None

    role = _financial_payment_fast_path_role(normalized, direction)
    payment_method = _financial_payment_fast_path_payment_method(normalized)
    entity: dict[str, Any] = {
        "name": name,
        "kind": "PERSON",
        "project_role": role,
        "role_detail": None,
        "type": role,
    }
    resolution = resolve_candidates(name, entity_context)
    if resolution["candidates"]:
        entity["requires_confirmation"] = True
        entity["candidate_matches"] = resolution["candidates"]

    financial_direction = (
        FinancialDirection.OUTGOING
        if direction == "OUT"
        else FinancialDirection.INCOMING
    )
    action = "PAYMENT_OUT" if direction == "OUT" else "PAYMENT_IN"
    structured = {
        "intent": "FINANCIAL",
        "action": action,
        "entities": [
            {
                **entity,
                "phone": None,
                "account_number": None,
                "daily_rate": None,
                "notes": None,
                "field_updates": None,
            }
        ],
        "financial": {
            "amount": amount,
            "direction": direction,
            "payment_method": payment_method,
            "due_date_text": None,
        },
        "work": {"quantity": None, "unit": None, "description": None},
        "note": {"text": None},
        "confidence": 0.96,
        "ambiguity": False,
        "missing_fields": [],
        "reasoning_summary": "deterministic financial payment fast path",
    }
    return PendingInterpretation(
        project_id=project_id,
        raw_input_text=raw_text,
        canonical_event_type="FINANCIAL_EVENT",
        semantic_action="PAYMENT",
        suggested_entity_id=None,
        matched_input_text=None,
        extracted_entities=[entity],
        extracted_amount=Decimal(str(amount)),
        extracted_quantity=None,
        payment_method=payment_method,
        financial_direction=financial_direction,
        due_date=None,
        description=raw_text,
        confidence=0.96,
        structured_interpretation=structured,
        status=PendingInterpretationStatus.PENDING,
    )


def _financial_payment_fast_path_direction(normalized: str) -> str | None:
    if "به " in normalized and any(
        phrase in normalized
        for phrase in [" دادم", " پول دادم", " پرداخت کردم", " پرداختم", " کارت زدم", " واریز کردم"]
    ):
        return "OUT"
    if "از " in normalized and " گرفتم" in normalized:
        return "IN"
    if " واریز کرد" in normalized:
        if not normalized.strip().startswith("به "):
            return "IN"
    return None


def _financial_payment_fast_path_name(normalized: str, direction: str) -> str | None:
    if direction == "OUT":
        match = re.search(rf"(?:^|\s)به\s+(?P<name>.+?)\s+{_PERSIAN_AMOUNT_MARKER}", normalized)
    elif "از " in normalized and " گرفتم" in normalized:
        match = re.search(rf"(?:^|\s)از\s+(?P<name>.+?)\s+{_PERSIAN_AMOUNT_MARKER}", normalized)
    else:
        match = re.search(rf"^(?P<name>.+?)\s+{_PERSIAN_AMOUNT_MARKER}", normalized)
    if match is None:
        return None
    name = re.sub(r"\s+", " ", match.group("name")).strip(" ،,")
    if not name or name in {"به", "از"}:
        return None
    if any(term in name for term in ["پروژه", "حساب", "کارت"]):
        return None
    return name


def _financial_payment_fast_path_role(normalized: str, direction: str) -> str:
    if any(term in normalized for term in ["فروشنده", "vendor"]):
        return "VENDOR"
    if any(term in normalized for term in ["کارفرما", "مالک", "client", "owner"]):
        return "CLIENT"
    if direction == "IN":
        return "CLIENT"
    return "OTHER"


def _financial_payment_fast_path_payment_method(normalized: str) -> str | None:
    bank_signals = ["حساب", "کارت", "واریز", "انتقال", "بانکی"]
    if any(signal in normalized for signal in bank_signals):
        return PaymentType.BANK_TRANSFER.value
    if any(signal in normalized for signal in ["چک", "سفته"]):
        return PaymentType.CHECK.value
    if any(signal in normalized for signal in ["نقدی", " پول دادم", " دادم", " گرفتم"]):
        return PaymentType.CASH.value
    return None


def _emit_fast_path_started(db: Session, interpretation: PendingInterpretation) -> None:
    _emit_event(db, "FAST_PATH_STARTED", {
        "fast_path_type": _fast_path_type(interpretation),
        "skipped_llm": True,
    })


def _emit_fast_path_matched(db: Session, interpretation: PendingInterpretation) -> None:
    _emit_event(db, "FAST_PATH_MATCHED", {
        "fast_path_type": _fast_path_type(interpretation),
        "skipped_llm": True,
    })


def _fast_path_type(interpretation: PendingInterpretation) -> str | None:
    if (
        interpretation.canonical_event_type == "FINANCIAL_EVENT"
        and interpretation.semantic_action == "PAYMENT"
    ):
        return "FINANCIAL_PAYMENT"
    entities = interpretation.extracted_entities or []
    first = entities[0] if entities and isinstance(entities[0], dict) else {}
    updates = first.get("field_updates") if isinstance(first, dict) else None
    if isinstance(updates, dict):
        if updates.get("phone"):
            return "PHONE_UPDATE"
        if updates.get("account_number"):
            return "ACCOUNT_UPDATE"
    return None


def _is_phone_or_account_update(interpretation: PendingInterpretation) -> bool:
    return _fast_path_type(interpretation) in {"PHONE_UPDATE", "ACCOUNT_UPDATE"}


def _build_role_assignment_interpretation(
    project_id: int,
    raw_text: str,
    entity_context: list[Worker],
) -> PendingInterpretation | None:
    if _text_has_financial_signal(raw_text) or not _is_role_only_assignment_text(raw_text):
        return None
    extracted = PersianRoleExtractor().extract(raw_text)
    if extracted is None or extracted.confidence < 0.75:
        return None
    role = extracted.worker_type.value
    resolution = resolve_candidates(extracted.name, entity_context)
    entity: dict[str, Any] = {
        "name": extracted.name,
        "kind": "PERSON",
        "project_role": role,
        "role_detail": extracted.role_phrase if role == "SKILLED_WORKER" else None,
        "type": role,
    }
    if resolution["candidates"]:
        entity["requires_confirmation"] = True
        entity["candidate_matches"] = resolution["candidates"]
    structured = {
        "intent": "SET_ROLE",
        "action": "SET_ROLE",
        "entities": [entity],
        "financial": {
            "amount": None,
            "direction": "NONE",
            "payment_method": None,
            "due_date_text": None,
        },
        "work": {"quantity": None, "unit": None, "description": None},
        "note": {"text": None},
        "confidence": extracted.confidence,
        "ambiguity": False,
        "missing_fields": [],
        "reasoning_summary": f"{extracted.name} نقش {extracted.role_phrase} دارد",
    }
    return PendingInterpretation(
        project_id=project_id,
        raw_input_text=raw_text,
        canonical_event_type="SETUP_EVENT",
        semantic_action="SET_ROLE",
        suggested_entity_id=None,
        matched_input_text=None,
        extracted_entities=[entity],
        extracted_amount=None,
        extracted_quantity=None,
        payment_method=None,
        financial_direction=None,
        due_date=None,
        description=raw_text,
        confidence=extracted.confidence,
        structured_interpretation=structured,
        status=PendingInterpretationStatus.PENDING,
    )


def _text_has_financial_signal(raw_text: str) -> bool:
    normalized = normalize_text(raw_text)
    return any(
        term in normalized
        for term in [
            "گرفتم",
            "گرفت",
            "پرداختم",
            "پرداخت",
            "خریدم",
            "خرید",
            "واریز",
            "پول داد",
            "چک",
            "میلیون",
            "تومان",
            "تومن",
        ]
    )


def _is_role_only_assignment_text(raw_text: str) -> bool:
    normalized = normalize_text(raw_text)
    if any(term in normalized for term in ["اضافه", "امروز", "کار کرد", "کارکرد", "اومد", "آمد", "زد"]):
        return False
    return any(term in normalized for term in [" است", " هست", "می باشد", "میباشد"])


def _coerce_llm_v2_profile_update_action(interpretation: Any) -> None:
    from app.schemas.llm_v2 import LLMv2Action, LLMv2Intent

    if (
        interpretation.intent not in {LLMv2Intent.SETUP, LLMv2Intent.SET_ROLE}
        or interpretation.action not in {LLMv2Action.ADD_ENTITY, LLMv2Action.SET_ROLE}
    ):
        return

    for entity in interpretation.entities:
        field_updates = entity.field_updates if isinstance(entity.field_updates, dict) else {}
        if field_updates or any(
            getattr(entity, key, None) is not None
            for key in ["phone", "account_number", "daily_rate", "notes"]
        ):
            interpretation.intent = LLMv2Intent.SETUP
            interpretation.action = LLMv2Action.UPDATE_ENTITY
            return


def _profile_update_name(raw_text: str, normalized: str, updates: dict[str, str | int]) -> str | None:
    text = normalized
    for value in updates.values():
        text = text.replace(str(value), " ")
    text = re.sub(r"شماره تماس|شماره موبایل|شماره حساب|شماره کارت|دستمزد روزانه|موبایل|تلفن|حساب|کارت|شبا|روزی|روزانه|تومان|ریال|است|می دیم|میدیم|به", " ", text)
    name = re.sub(r"\s+", " ", text).strip()
    return name or None


def _repair_llm_v2_setup_role_from_text(interpretation: Any, raw_text: str) -> None:
    from app.schemas.llm_v2 import LLMv2Action, LLMv2Intent, LLMv2ProjectRole

    if interpretation.intent not in {LLMv2Intent.SETUP, LLMv2Intent.SET_ROLE} or interpretation.action not in {
        LLMv2Action.ADD_ENTITY,
        LLMv2Action.SET_ROLE,
    }:
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
        "SET_ROLE": "SETUP_EVENT",
        "SETUP": "SETUP_EVENT",
        "WORK": "WORK_EVENT",
        "FINANCIAL": "FINANCIAL_EVENT",
        "NOTE": "NOTE_EVENT",
        "DOCUMENT": "NOTE_EVENT",
    }
    return mapping.get(intent, "NOTE_EVENT")


def _llm_v2_action_to_semantic(action: str) -> str:
    mapping = {
        "SET_ROLE": "SET_ROLE",
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
        "OTHER": "OTHER",
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
        if detect_incoming_project_payment(raw_text) is not None:
            return FinancialDirection.INCOMING
        return FinancialDirection.OUTGOING
    if detect_incoming_project_payment(raw_text) is not None:
        return FinancialDirection.INCOMING
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


def _safe_llm_v2_result(
    input_text: str,
    project_id: int,
    request_cache: RequestCache | None = None,
    db: Session | None = None,
    event_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cache_context = {"interpreter": "llm_v2"}
    key = llm_cache_key(input_text, project_id, cache_context)
    if request_cache is not None:
        cached_request_result = request_cache.get_llm_result(key)
        if cached_request_result is not None:
            return cached_request_result
    cached_result = get_llm_cache(key)
    if cached_result is not None:
        if request_cache is not None:
            request_cache.set_llm_result(key, cached_result)
        return cached_result
    try:
        interpreter = _llm_v2_interpreter()
        interpret_sig = inspect.signature(interpreter.interpret)
        if db is not None:
            _emit_event(db, "LLM_STARTED", {
                "project_id": project_id,
                "input_text_length": len(input_text),
                **(event_payload or {}),
            })
        if "db" in interpret_sig.parameters:
            result = interpreter.interpret(input_text, project_id, db=db)
        else:
            result = interpreter.interpret(input_text, project_id)
        timings = result.pop("_timings", None) if isinstance(result, dict) else None
        if timings is not None and request_cache is not None:
            for k, v in timings.items():
                if isinstance(v, (int, float)):
                    request_cache.set_timing(k, float(v))
        if not result.get("_llm_v2_failed"):
            set_llm_cache(key, result)
            if request_cache is not None:
                request_cache.set_llm_result(key, result)
        return result
    except Exception:
        result = {
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
        return result


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
            shadow_result = _safe_llm_v2_result(input_text, project_id, cache, db=db)
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


def _split_multi_event_text(text: str) -> list[str]:
    """Deterministic fallback: split text on obvious separators.

    Only splits when each resulting chunk contains a clear financial, setup,
    or profile-update signal.  This avoids over-splitting names or descriptions.
    Returns [text] when no viable split is found.
    """
    separators = re.compile(r"[.\n;؛]")
    candidate_chunks = [c.strip() for c in separators.split(text) if c.strip()]
    if len(candidate_chunks) < 2:
        return [text]

    def _has_signal(chunk: str) -> bool:
        chunk = normalize_text(chunk)
        money_terms = {"تومان", "تومن", "میلیون", "میلیارد", "ریال"}
        financial_verbs = {"دادم", "داد", "گرفتم", "گرفت", "پرداخت", "پرداختم", "خریدم", "خرید", "واریز", "پول داد"}
        profile_terms = {"شماره تماس", "شماره موبایل", "شماره حساب", "شماره کارت", "دستمزد روزانه", "حساب"}
        setup_terms = {" است", " هست", "می باشد", "میباشد", "کارگر", "کارفرما", "سرامیک کار", "فروشنده"}
        has_money = any(t in chunk for t in money_terms)
        has_financial_verb = any(v in chunk for v in financial_verbs)
        has_profile = any(p in chunk for p in profile_terms)
        has_setup = any(s in chunk for s in setup_terms)
        return (has_money and has_financial_verb) or has_profile or has_setup

    signalled = [c for c in candidate_chunks if _has_signal(c)]
    if len(signalled) < 2:
        return [text]
    return signalled


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
    from app.core.logger import log_event
    log_event(event=f"debug.{label}", payload=payload)
