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
    WorkerType,
)
from app.schemas.llm_v2 import LLMv2FinancialDirection, LLMv2PaymentMethod
from app.services.llm_v2_interpreter import LLMv2Interpreter
from app.services.llm_v2_validator import LLMv2Validator, LLMv2ValidationError, resolve_candidates
from app.services.entity_normalizer import match_score, normalize_name
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

    fast_work_log = None if len(chunks) > 1 else _build_daily_work_log_interpretation(project_id, text, entity_context)
    if fast_work_log is not None:
        _emit_fast_path_started(db, fast_work_log)
        db.add(fast_work_log)
        db.commit()
        db.refresh(fast_work_log)
        cache.set_legacy_result(_shadow_legacy_payload([fast_work_log]))
        cache.set_timing("llm_v2_duration_ms", 0.0)
        cache.set_timing("legacy_duration_ms", 0.0)
        cache.set_timing("governance_duration_ms", 0.0)
        _emit_fast_path_matched(db, fast_work_log)
        _emit_event(db, "PENDING_INTERPRETATION_SAVED", {
            "interpretation_count": 1,
            "path": "fast_daily_work_log",
            "fast_path_type": _fast_path_type(fast_work_log),
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
        return [fast_work_log]

    fast_safe_note = None if len(chunks) > 1 else _build_safe_note_interpretation(project_id, text)
    if fast_safe_note is not None:
        db.add(fast_safe_note)
        db.commit()
        db.refresh(fast_safe_note)
        cache.set_legacy_result(_shadow_legacy_payload([fast_safe_note]))
        cache.set_timing("llm_v2_duration_ms", 0.0)
        cache.set_timing("legacy_duration_ms", 0.0)
        cache.set_timing("governance_duration_ms", 0.0)
        _emit_event(db, "PENDING_INTERPRETATION_SAVED", {
            "interpretation_count": 1,
            "path": "safe_note_fast_path",
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
        return [fast_safe_note]

    fast_setup = None if len(chunks) > 1 else _build_role_assignment_interpretation(project_id, text, entity_context)
    if (
        fast_setup is not None
        and not _role_assignment_has_profile_fields(fast_setup)
        and not _is_name_before_role_statement(text)
    ):
        fast_setup = None
    if fast_setup is not None:
        _emit_fast_path_started(db, fast_setup)
        db.add(fast_setup)
        db.commit()
        db.refresh(fast_setup)
        cache.set_timing("llm_v2_duration_ms", 0.0)
        cache.set_timing("legacy_duration_ms", 0.0)
        cache.set_timing("governance_duration_ms", 0.0)
        _emit_fast_path_matched(db, fast_setup)
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

    safe_note = _build_safe_note_interpretation(project_id, text)
    if safe_note is not None:
        db.add(safe_note)
        db.commit()
        db.refresh(safe_note)
        cache.set_legacy_result(_shadow_legacy_payload([safe_note]))
        cache.set_timing("legacy_duration_ms", 0.0)
        _emit_event(db, "PENDING_INTERPRETATION_SAVED", {
            "interpretation_count": 1,
            "path": "safe_note_fallback",
        })
        return [safe_note]

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
        fast_work_log = _build_daily_work_log_interpretation(project_id, chunk, entity_context)
        if fast_work_log is not None:
            _emit_fast_path_started(db, fast_work_log)
            _retarget_interpretation_to_raw_text(fast_work_log, raw_text, chunk)
            interpretations.append(fast_work_log)
            _emit_fast_path_matched(db, fast_work_log)
            _emit_chunk_processed(db, chunk_index, chunk, "FAST_PATH")
            continue

        safe_note = _build_safe_note_interpretation(project_id, chunk)
        if safe_note is not None:
            _retarget_interpretation_to_raw_text(safe_note, raw_text, chunk)
            interpretations.append(safe_note)
            _emit_chunk_processed(db, chunk_index, chunk, "FAST_PATH")
            continue

        fast_setup = _build_role_assignment_interpretation(project_id, chunk, entity_context)
        if fast_setup is not None:
            _emit_fast_path_started(db, fast_setup)
            _retarget_interpretation_to_raw_text(fast_setup, raw_text, chunk)
            interpretations.append(fast_setup)
            _emit_fast_path_matched(db, fast_setup)
            _emit_chunk_processed(db, chunk_index, chunk, "FAST_PATH")
            continue

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

    _resolve_same_input_entities_in_pending_interpretations(interpretations)

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


def _resolve_same_input_entities_in_pending_interpretations(
    interpretations: list[PendingInterpretation],
) -> None:
    token_map: dict[str, list[tuple[str, str]]] = {}
    for pi in interpretations:
        entities = _get_pi_entities(pi)
        if not entities:
            continue
        for entity in entities:
            name = (entity.get("name") or "").strip()
            if not name:
                continue
            tokens = name.split()
            role = entity.get("project_role") or entity.get("type") or ""
            is_full = len(tokens) >= 2 or (role not in ("", "OTHER"))
            if is_full:
                for token in tokens:
                    token_map.setdefault(token, [])
                    entry = (name, role)
                    if entry not in token_map[token]:
                        token_map[token].append(entry)
    unambiguous: dict[str, tuple[str, str]] = {}
    for token, candidates in token_map.items():
        if len(candidates) == 1:
            unambiguous[token] = candidates[0]
    for pi in interpretations:
        entities = _get_pi_entities(pi)
        if not entities:
            continue
        si = pi.structured_interpretation
        si_entities: list[dict] | None = None
        if isinstance(si, dict):
            raw = si.get("entities")
            if isinstance(raw, list):
                si_entities = raw
        for i, entity in enumerate(entities):
            name = (entity.get("name") or "").strip()
            if not name:
                continue
            tokens = name.split()
            if len(tokens) == 1 and name in unambiguous:
                full_name, full_role = unambiguous[name]
                entity["name"] = full_name
                current_role = entity.get("project_role") or entity.get("type") or ""
                if current_role in ("", "OTHER"):
                    entity["project_role"] = full_role
                    entity["type"] = full_role
                if si_entities is not None and i < len(si_entities):
                    si_entity = si_entities[i]
                    if isinstance(si_entity, dict):
                        si_entity["name"] = full_name
                        if si_entity.get("project_role") in ("", "OTHER", None):
                            si_entity["project_role"] = full_role
        _repair_client_paid_direction(interpretations=[pi])


def _get_pi_entities(pi: PendingInterpretation) -> list[dict] | None:
    raw = pi.extracted_entities
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return [raw]
    return None


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

    normalized_name_match = _unique_normalized_entity_match(entity_name, entity_context)
    if normalized_name_match is not None and _is_role_compatible(normalized_name_match.type.value, expected_role):
        return normalized_name_match.id

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


def _unique_normalized_entity_match(name: str, entity_context: list[Worker]) -> Worker | None:
    normalized = normalize_name(name)
    if not normalized:
        return None
    matches = [
        worker
        for worker in entity_context
        if normalize_name(worker.name) == normalized
        or (len(normalized.split()) == 1 and normalized in normalize_name(worker.name).split())
    ]
    return matches[0] if len(matches) == 1 else None


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
    _repair_llm_v2_safe_note_from_text(interpretation, event_text)
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
        interpretation.intent = LLMv2Intent.FINANCIAL
        interpretation.action = LLMv2Action.PAYMENT_IN
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
        if "چک" in normalize_text(event_text):
            semantic_action = "CHECK_PAYMENT"
            financial_direction = FinancialDirection.DEFERRED
            interpretation.action = LLMv2Action.CHECK_PAYMENT
        elif _has_unpaid_purchase_terms(event_text):
            semantic_action = "DEBT_CREATED"
            financial_direction = FinancialDirection.DEBT
            interpretation.action = LLMv2Action.DEBT_CREATED
        elif action_str not in {"DEBT_CREATED", "CHECK_PAYMENT"}:
            semantic_action = "PURCHASE_PAID"
            financial_direction = FinancialDirection.OUTGOING
            interpretation.action = LLMv2Action.PURCHASE_PAID
        interpretation.intent = LLMv2Intent.FINANCIAL
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
        if semantic_action == "CHECK_PAYMENT":
            payment_method = PaymentType.CHECK.value
        elif semantic_action == "DEBT_CREATED":
            payment_method = None
        else:
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

    if _should_repair_client_paid_direction(event_text, entities_json, canonical_type, semantic_action, financial_direction):
        financial_direction = FinancialDirection.INCOMING
        interpretation.financial.direction = LLMv2FinancialDirection.IN
        if action_str == "PAYMENT_OUT":
            interpretation.action = LLMv2Action.PAYMENT_IN

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


def _repair_client_paid_direction(interpretations: list[PendingInterpretation]) -> None:
    for interpretation in interpretations:
        entities = interpretation.extracted_entities or []
        if not _should_repair_client_paid_direction(
            interpretation.matched_input_text or interpretation.description or interpretation.raw_input_text,
            entities,
            interpretation.canonical_event_type,
            interpretation.semantic_action,
            interpretation.financial_direction,
        ):
            continue
        interpretation.financial_direction = FinancialDirection.INCOMING
        structured = interpretation.structured_interpretation
        if isinstance(structured, dict):
            structured["action"] = "PAYMENT_IN"
            financial = structured.get("financial")
            if isinstance(financial, dict):
                financial["direction"] = "IN"
            interpretation.structured_interpretation = structured


def _should_repair_client_paid_direction(
    raw_text: str | None,
    entities_json: list[dict[str, Any]] | None,
    canonical_type: str | None,
    semantic_action: str | None,
    financial_direction: Any,
) -> bool:
    if (
        canonical_type != "FINANCIAL_EVENT"
        or semantic_action != "PAYMENT"
        or financial_direction != FinancialDirection.OUTGOING
        or not entities_json
    ):
        return False
    first = entities_json[0]
    role = first.get("project_role") or first.get("type")
    if role != "CLIENT":
        return False
    normalized = normalize_text(raw_text or "")
    return _looks_like_ambiguous_client_payment(normalized)


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
    if "اضافه" in normalized and PersianRoleExtractor().extract(raw_text) is not None:
        return None
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


def _build_safe_note_interpretation(
    project_id: int,
    raw_text: str,
) -> PendingInterpretation | None:
    normalized = normalize_text(raw_text)
    if _text_has_financial_signal(raw_text):
        return None
    if _has_explicit_setup_or_profile_text(normalized):
        return None
    if not _has_plain_note_text(normalized):
        return None
    structured = {
        "intent": "NOTE",
        "action": "NOTE",
        "entities": [],
        "financial": {
            "amount": None,
            "direction": "NONE",
            "payment_method": None,
            "due_date_text": None,
        },
        "work": {"quantity": None, "unit": None, "description": None},
        "note": {"text": raw_text},
        "confidence": 0.85,
        "ambiguity": False,
        "missing_fields": [],
        "reasoning_summary": "deterministic safe note",
    }
    return PendingInterpretation(
        project_id=project_id,
        raw_input_text=raw_text,
        canonical_event_type="NOTE_EVENT",
        semantic_action="NOTE",
        suggested_entity_id=None,
        matched_input_text=None,
        extracted_entities=None,
        extracted_amount=None,
        extracted_quantity=None,
        payment_method=None,
        financial_direction=None,
        due_date=None,
        description=raw_text,
        confidence=0.85,
        structured_interpretation=structured,
        status=PendingInterpretationStatus.PENDING,
    )


_PERSIAN_INT_WORDS = {
    "یک": Decimal("1"),
    "یه": Decimal("1"),
    "دو": Decimal("2"),
    "سه": Decimal("3"),
    "چهار": Decimal("4"),
    "پنج": Decimal("5"),
    "شش": Decimal("6"),
    "هفت": Decimal("7"),
    "هشت": Decimal("8"),
    "نه": Decimal("9"),
    "ده": Decimal("10"),
    "یازده": Decimal("11"),
    "دوازده": Decimal("12"),
    "سیزده": Decimal("13"),
    "چهارده": Decimal("14"),
    "پانزده": Decimal("15"),
    "شانزده": Decimal("16"),
    "هفده": Decimal("17"),
    "هجده": Decimal("18"),
    "نوزده": Decimal("19"),
    "بیست": Decimal("20"),
}

_WORK_PERIOD_PATTERNS = [
    "ماه اردیبهشت",
    "هفته گذشته",
    "هفته قبل",
    "دیروز",
    "امروز",
]


def _build_daily_work_log_interpretation(
    project_id: int,
    raw_text: str,
    entity_context: list[Worker],
) -> PendingInterpretation | None:
    normalized = normalize_text(raw_text).replace("\u200c", " ")
    if _text_has_financial_signal(raw_text):
        return None
    if "کار کرد" not in normalized and "کار کرده" not in normalized:
        return None

    quantity = _daily_work_quantity(normalized)
    if quantity is None or quantity <= 0:
        return None
    name = _daily_work_name(normalized)
    if name is None:
        return None
    period_label = _daily_work_period_label(normalized)
    matched_worker = _unique_normalized_entity_match(name, entity_context)
    display_name = matched_worker.name if matched_worker is not None else name
    entity: dict[str, Any] = {
        "name": display_name,
        "kind": "PERSON",
        "project_role": "DAILY_WORKER",
        "role_detail": None,
        "type": "DAILY_WORKER",
        "phone": None,
        "account_number": None,
        "daily_rate": str(matched_worker.daily_rate) if matched_worker and matched_worker.daily_rate is not None else None,
        "notes": None,
        "field_updates": None,
    }
    if matched_worker is None:
        entity["requires_confirmation"] = True
        entity["create_new"] = True
        resolution = resolve_candidates(name, entity_context)
        if resolution["candidates"]:
            entity["candidate_matches"] = resolution["candidates"]

    structured = {
        "intent": "WORK",
        "action": "WORK_LOG",
        "entities": [entity],
        "financial": {
            "amount": None,
            "direction": "NONE",
            "payment_method": None,
            "due_date_text": None,
        },
        "work": {
            "quantity": float(quantity),
            "unit": "day",
            "description": raw_text,
            "period_label": period_label,
        },
        "note": {"text": None},
        "confidence": 0.94,
        "ambiguity": matched_worker is None,
        "missing_fields": [] if matched_worker is not None else ["entity"],
        "reasoning_summary": "deterministic daily worker attendance fast path",
    }
    semantic_explanation = {
        "triggered_rule": "WORK_RULE_01",
        "event_type": "WORK_EVENT",
        "matched_signals": ["کار کرد" if "کار کرد" in normalized else "کار کرده"],
        "decision_path": [
            "deterministic daily worker attendance fast path",
            "event classified as WORK_EVENT",
        ],
    }
    return PendingInterpretation(
        project_id=project_id,
        raw_input_text=raw_text,
        canonical_event_type="WORK_EVENT",
        semantic_action="WORK_LOG",
        suggested_entity_id=matched_worker.id if matched_worker is not None else None,
        matched_input_text=name if matched_worker is not None and name != matched_worker.name else None,
        extracted_entities=[entity],
        extracted_amount=None,
        extracted_quantity=quantity,
        payment_method=None,
        financial_direction=None,
        due_date=None,
        description=raw_text if period_label is None else f"{period_label} - {raw_text}",
        semantic_explanation=semantic_explanation,
        confidence=0.94,
        structured_interpretation=structured,
        status=PendingInterpretationStatus.PENDING,
    )


def _daily_work_period_label(normalized: str) -> str | None:
    for pattern in _WORK_PERIOD_PATTERNS:
        if pattern in normalized:
            return pattern
    return None


def _daily_work_name(normalized: str) -> str | None:
    text = re.split(r"\s+(?:امروز|دیروز|هفته قبل|هفته گذشته|ماه اردیبهشت|در هفته قبل|در هفته گذشته)\b", normalized, maxsplit=1)[0]
    text = re.split(r"\s+(?:[۰-۹٠-٩\d]+|[آ-ی]+)\s+روز\b", text, maxsplit=1)[0]
    text = text.replace("در ", " ")
    name = re.sub(r"\s+", " ", text).strip(" ،,")
    return name or None


def _daily_work_quantity(normalized: str) -> Decimal | None:
    explicit = _explicit_day_count(normalized)
    if explicit is not None:
        return explicit
    weekday_count = _weekday_day_count(normalized)
    if weekday_count is not None:
        return weekday_count
    if "امروز" in normalized or "دیروز" in normalized:
        return Decimal("1")
    return None


def _explicit_day_count(normalized: str) -> Decimal | None:
    match = re.search(r"(?P<count>[۰-۹٠-٩\d]+|[آ-ی]+)\s+روز(?:\s+و\s+(?P<half>نصفی|نیم))?", normalized)
    if match is None:
        return None
    count = _parse_persian_int(match.group("count"))
    if count is None:
        return None
    if match.group("half"):
        count += Decimal("0.5")
    return count


def _weekday_day_count(normalized: str) -> Decimal | None:
    matches = list(re.finditer(r"(یک\s*شنبه|دو\s*شنبه|سه\s*شنبه|چهار\s*شنبه|پنج\s*شنبه|شنبه|جمعه)", normalized))
    if not matches:
        return None
    total = Decimal("0")
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        segment = normalized[match.end():end]
        total += Decimal("0.5") if any(term in segment for term in ["نصفه روز", "نیم روز", "نصفی"]) else Decimal("1")
    return total


def _parse_persian_int(value: str) -> Decimal | None:
    normalized = value.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")).strip()
    if normalized.isdigit():
        return Decimal(normalized)
    return _PERSIAN_INT_WORDS.get(normalized)


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
    incoming_project_payment = detect_incoming_project_payment(raw_text)
    if any(term in normalized for term in ["پروژه", "حساب پروژه"]) and incoming_project_payment is None:
        return None
    if detect_purchase_payment(raw_text) is not None or any(term in normalized for term in ["خرید", "خریدم", "خرید کردم"]):
        return None

    direction = _financial_payment_fast_path_direction(normalized)
    if direction is None and _looks_like_ambiguous_client_payment(normalized):
        possible_name = _financial_payment_fast_path_name(normalized, "IN")
        matched_worker = _unique_normalized_entity_match(possible_name or "", entity_context)
        if matched_worker is not None and matched_worker.type == WorkerType.CLIENT:
            direction = "IN"
    if direction is None:
        return None
    name = _financial_payment_fast_path_name(normalized, direction)
    if name is None:
        return None

    matched_worker = _unique_normalized_entity_match(name, entity_context)
    role = (
        "CLIENT"
        if direction == "IN" and matched_worker is not None and matched_worker.type == WorkerType.CLIENT
        else _financial_payment_fast_path_role(normalized, direction)
    )
    payment_method = _financial_payment_fast_path_payment_method(normalized)
    if incoming_project_payment is not None:
        payment_method = PaymentType.BANK_TRANSFER.value
    preserve_raw_project_deposit_name = incoming_project_payment is not None and "واریز" in normalized
    display_name = (
        matched_worker.name
        if matched_worker is not None and not preserve_raw_project_deposit_name
        else name
    )
    entity: dict[str, Any] = {
        "name": display_name,
        "kind": "PERSON",
        "project_role": role,
        "role_detail": None,
        "type": role,
    }
    resolution = resolve_candidates(name, entity_context)
    if (matched_worker is None or preserve_raw_project_deposit_name) and resolution["candidates"]:
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
        suggested_entity_id=matched_worker.id if matched_worker is not None else None,
        matched_input_text=name if matched_worker is not None and name != matched_worker.name else None,
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
        for phrase in [" دادم", " پول دادم", " پرداخت کردم", " پرداخت شد", " پرداختم", " کارت زدم", " واریز کردم"]
    ):
        return "OUT"
    if "از " in normalized and " گرفتم" in normalized:
        return "IN"
    if " واریز کرد" in normalized:
        if not normalized.strip().startswith("به "):
            return "IN"
    return None


def _looks_like_ambiguous_client_payment(normalized: str) -> bool:
    if re.search(r"(?:^|\s)به\s+", normalized):
        return False
    if any(term in normalized for term in ["خرید", "خریدم", "بابت خرید"]):
        return False
    return any(phrase in normalized for phrase in [" پرداخت کرد", " پول داد", " دیگر پرداخت کرد"])


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
    if direction == "OUT":
        name = _strip_payment_purpose_from_name(name)
    if not name or name in {"به", "از"}:
        return None
    if any(term in name for term in ["پروژه", "حساب", "کارت"]):
        return None
    return name


def _strip_payment_purpose_from_name(name: str) -> str:
    for marker in (" بابت ", " برای ", " در ازای "):
        if marker in name:
            return name.split(marker, 1)[0].strip(" ،,")
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
    if _text_has_financial_signal(raw_text) or not _is_role_assignment_text(raw_text):
        return None
    normalized = normalize_text(raw_text)
    if any(term in normalized for term in ["کارگرها", "کارگرهای پروژه"]):
        return None
    extracted = PersianRoleExtractor().extract(raw_text)
    if extracted is None or extracted.confidence < 0.6:
        return None
    role = extracted.worker_type.value
    extracted_name = _role_assignment_display_name(raw_text, extracted, entity_context)
    resolution = resolve_candidates(extracted_name, entity_context)
    entity: dict[str, Any] = {
        "name": extracted_name,
        "kind": "PERSON",
        "project_role": role,
        "role_detail": extracted.role_phrase if role == "SKILLED_WORKER" else None,
        "type": role,
    }
    field_updates: dict[str, str] = {}
    phone_match = re.search(r"09\d{9,12}", normalize_text(raw_text).replace(" ", ""))
    if phone_match:
        field_updates["phone"] = phone_match.group()
        entity["phone"] = phone_match.group()
    account_match = re.search(r"\d{12,26}", normalize_text(raw_text).replace(" ", ""))
    if account_match and any(term in normalize_text(raw_text) for term in ["شماره حساب", "شماره کارت", "حساب", "کارت", "شبا"]):
        field_updates["account_number"] = account_match.group()
        entity["account_number"] = account_match.group()
    if field_updates:
        entity["field_updates"] = field_updates
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
        "reasoning_summary": f"{extracted_name} نقش {extracted.role_phrase} دارد",
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


def _role_assignment_has_profile_fields(interpretation: PendingInterpretation) -> bool:
    entities = interpretation.extracted_entities or []
    if not entities:
        return False
    first = entities[0]
    if not isinstance(first, dict):
        return False
    updates = first.get("field_updates")
    return isinstance(updates, dict) and bool(updates)


def _is_name_before_role_statement(raw_text: str) -> bool:
    normalized = normalize_text(raw_text)
    if "اضافه" in normalized:
        return False
    extracted = PersianRoleExtractor().extract(raw_text)
    if extracted is None:
        return False
    role_index = normalized.find(extracted.role_phrase)
    name_index = normalized.find(extracted.name)
    return name_index >= 0 and role_index >= 0 and name_index < role_index


def _dedupe_repeated_name(name: str) -> str:
    parts = name.split()
    if len(parts) % 2 != 0:
        return name
    midpoint = len(parts) // 2
    if parts[:midpoint] == parts[midpoint:]:
        return " ".join(parts[:midpoint])
    return name


_ROLE_QUALIFIERS_PRESERVED_IN_NAMES = {
    "تاسیساتی",
}


def _role_assignment_display_name(
    raw_text: str,
    extracted: Any,
    entity_context: list[Worker],
) -> str:
    base_name = _dedupe_repeated_name(extracted.name)
    role_phrase = getattr(extracted, "role_phrase", "")
    if role_phrase not in _ROLE_QUALIFIERS_PRESERVED_IN_NAMES:
        return base_name
    if len(base_name.split()) != 1:
        return base_name
    normalized_text = normalize_text(raw_text).replace("\u200c", " ")
    qualified_name = f"{base_name} {role_phrase}"
    if qualified_name not in normalized_text:
        return base_name
    if not entity_context:
        return qualified_name
    existing_base_match = _unique_normalized_entity_match(base_name, entity_context)
    return qualified_name if existing_base_match is not None else base_name


def _is_role_assignment_text(raw_text: str) -> bool:
    normalized = normalize_text(raw_text)
    if any(term in normalized for term in ["امروز", "کار کرد", "کارکرد", "اومد", "آمد", "زد"]):
        return False
    return any(term in normalized for term in [" است", " هست", "می باشد", "میباشد", "اضافه شد", "به پروژه اضافه"])


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


def _repair_llm_v2_safe_note_from_text(interpretation: Any, raw_text: str) -> None:
    from app.schemas.llm_v2 import LLMv2Action, LLMv2Intent

    if interpretation.intent not in {LLMv2Intent.SETUP, LLMv2Intent.SET_ROLE}:
        return
    normalized = normalize_text(raw_text)
    if _has_explicit_setup_or_profile_text(normalized):
        return
    if not _has_note_or_unsupported_work_text(normalized):
        return
    interpretation.intent = LLMv2Intent.NOTE
    interpretation.action = LLMv2Action.NOTE
    interpretation.entities = []
    interpretation.note.text = raw_text
    interpretation.financial.amount = None
    interpretation.financial.direction = LLMv2FinancialDirection.NONE
    interpretation.financial.payment_method = None
    interpretation.work.quantity = None
    interpretation.work.unit = None
    interpretation.work.description = None


def _has_explicit_setup_or_profile_text(normalized_text: str) -> bool:
    return any(
        term in normalized_text
        for term in (
            "کارفرمای پروژه است",
            "کارگر پروژه است",
            "به پروژه اضافه",
            "اضافه شد",
            "شماره تماس",
            "شماره موبایل",
            "شماره حساب",
            "دستمزد روزانه",
        )
    )


def _has_note_or_unsupported_work_text(normalized_text: str) -> bool:
    return any(
        term in normalized_text
        for term in (
            "درخواست",
            "گفت",
            "خواست",
            "تایید",
            "تأیید",
            "به پایان رسید",
            "تمام شد",
            "تغییر داد",
            "شروع شد",
            "کار کرد",
            "روز کار کرد",
            "هفته قبل",
            "هفته گذشته",
            "ماه اردیبهشت",
        )
    )


def _has_plain_note_text(normalized_text: str) -> bool:
    if _is_client_request_note_text(normalized_text):
        return True
    return any(
        term in normalized_text
        for term in (
            "درخواست",
            "تایید",
            "تأیید",
            "به پایان رسید",
            "تمام شد",
            "تغییر داد",
            "شروع شد",
        )
    )


def _is_client_request_note_text(normalized_text: str) -> bool:
    if _has_explicit_payment_or_profile_text(normalized_text):
        return False
    return any(
        phrase in normalized_text
        for phrase in (
            "کارفرما گفت",
            "کارفرما درخواست کرد",
            "کارفرما خواست",
            "مشتری گفت",
            "مشتری درخواست کرد",
            "مشتری خواست",
        )
    )


def _has_explicit_payment_or_profile_text(normalized_text: str) -> bool:
    return any(
        term in normalized_text
        for term in (
            "پرداخت",
            "واریز",
            "پول داد",
            "خرید",
            "میلیون",
            "تومان",
            "شماره تماس",
            "شماره موبایل",
            "شماره حساب",
            "شماره کارت",
            "دستمزد روزانه",
            "کارفرمای پروژه است",
            "کارگر پروژه است",
            "به پروژه اضافه",
            "اضافه شد",
        )
    )


def _has_unpaid_purchase_terms(raw_text: str) -> bool:
    normalized = normalize_text(raw_text)
    return any(
        term in normalized
        for term in (
            "نسیه",
            "ندادم",
            "هنوز ندادم",
            "پرداخت نشده",
            "هنوز پرداخت نشده",
            "تسویه نشده",
            "بدهی",
        )
    )


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
    normalized_text = normalize_text(text)
    if (
        "اضافه شد" in normalized_text
        and normalized_text.count("اضافه شد") == 1
        and any(term in normalized_text for term in ["شماره تماس", "شماره موبایل"])
        and PersianRoleExtractor().extract(text) is not None
    ):
        return [text]
    separators = re.compile(r"[.\n;؛]")
    candidate_chunks = [c.strip() for c in separators.split(text) if c.strip()]
    if len(candidate_chunks) < 2:
        return [text]

    def _has_signal(chunk: str) -> bool:
        chunk = normalize_text(chunk)
        money_terms = {"تومان", "تومن", "میلیون", "میلیارد", "ریال"}
        financial_verbs = {"دادم", "داد", "گرفتم", "گرفت", "پرداخت", "پرداختم", "خریدم", "خرید", "واریز", "پول داد"}
        profile_terms = {"شماره تماس", "شماره موبایل", "شماره حساب", "شماره کارت", "دستمزد روزانه", "حساب"}
        setup_terms = {
            " است",
            " هست",
            "می باشد",
            "میباشد",
            "اضافه شد",
            "به پروژه اضافه",
            "کارگر",
            "کارفرما",
            "سرامیک کار",
            "برق کار",
            "لوله کش",
            "نقاش",
            "کابینت کار",
            "گچ کار",
            "کناف کار",
            "نما کار",
            "فروشنده",
        }
        has_money = any(t in chunk for t in money_terms)
        has_financial_verb = any(v in chunk for v in financial_verbs)
        has_profile = any(p in chunk for p in profile_terms)
        has_setup = any(s in chunk for s in setup_terms)
        has_daily_work = ("کار کرد" in chunk or "کار کرده" in chunk) and not has_money
        return (has_money and has_financial_verb) or has_profile or has_setup or has_daily_work

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
