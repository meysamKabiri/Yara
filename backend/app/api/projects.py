import logging
import os
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from time import perf_counter
from typing import Any

from fastapi import APIRouter, Body, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.financial_role_repair import normalize_outgoing_payment_roles_in_result
from app.core.observability_service import track_event, track_timed_event
from app.core.queue import get_queue
from app.core.trace_context import get_trace_id
from app.dependencies.database import DbSession
from app.models.core import (
    CounterpartyType,
    EventCorrection,
    ExtractedEvent,
    ExtractedEventStatus,
    ExtractedEventType,
    FinancialDirection,
    HistoryChangeType,
    HistoryEntry,
    Invoice,
    InvoiceStatus,
    Payment,
    NaturalInputJob,
    NaturalInputJobStatus,
    PaymentType,
    PendingInterpretation,
    PendingInterpretationStatus,
    Project,
    RawEntry,
    RawEntryStatus,
    Worker,
    WorkerState,
    WorkerStateRole,
    WorkerType,
    WorkLog,
    WorkUnit,
)
from app.schemas.projects import (
    EntityResolutionResult,
    ExtractedEventCreate,
    ExtractedEventRead,
    ExtractedEventUpdate,
    HistoryEntryRead,
    InvoiceCreate,
    InvoiceRead,
    NaturalInputCreate,
    NaturalInputResult,
    PaymentCreate,
    PaymentRead,
    PendingInterpretationConfirm,
    PendingInterpretationRead,
    PendingInterpretationUpdate,
    ProjectCreate,
    ProjectDetail,
    ProjectRead,
    ProjectTotals,
    RawEntryCreate,
    RawEntryRead,
    WorkerCreate,
    WorkerRead,
    WorkerStateRead,
    WorkerUpdate,
    WorkLogCreate,
    WorkLogRead,
    WorkLogUpdate,
)
from app.services.domain_router_service import DomainRouterService, DomainType
from app.services.entity_registry import EntityRegistryService
from app.services.entity_resolution_service import EntityResolutionService
from app.services.execution_comparator import ExecutionComparator
from app.services.execution_engine import (
    ConfirmedFinancialInterpretation,
    ExecutionEngine,
)
from app.services.financial_summary import (
    invoice_paid_amount,
    project_operating_summary,
)
from app.services.llm_extraction import extract, extract_graph  # noqa: F401
from app.services.llm_v2_interpreter import LLMv2Interpreter  # noqa: F401
from app.services.llm_v2_validator import resolve_candidates
from app.services.persian_money_engine import (
    normalize_text,
    parse_persian_money,
)
from app.services.persian_project_payment import (
    detect_incoming_project_payment,
    detect_purchase_payment,
)
from app.services.persian_role_extractor import PersianRoleExtractor
from app.services.semantic_normalizer import (
    CanonicalEvent,
    CanonicalEventType,
)

router = APIRouter(tags=["projects"])
logger = logging.getLogger(__name__)

# Feature flag controlling which financial write engine is primary.
# Default: ExecutionEngine is primary.  Legacy writers (_execute_legacy_interpretation,
# _execute_llm_v2_interpretation) run only as shadow/comparison behind a
# savepoint rollback when this is enabled.
# Set YARA_USE_EXECUTION_ENGINE=0 to restore legacy writers as the default
# production path (not recommended).
USE_EXECUTION_ENGINE = os.getenv("YARA_USE_EXECUTION_ENGINE", "true").lower() not in {
    "0",
    "false",
    "no",
}


def _get_project(db: DbSession, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )
    return project


def _get_raw_entry(db: DbSession, project_id: int, raw_entry_id: int) -> RawEntry:
    raw_entry = db.get(RawEntry, raw_entry_id)
    if raw_entry is None or raw_entry.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Raw entry not found"
        )
    return raw_entry


def _get_event(db: DbSession, event_id: int) -> ExtractedEvent:
    event = db.get(ExtractedEvent, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Extracted event not found",
        )
    return event


def _get_worker(db: DbSession, project_id: int, worker_id: int) -> Worker:
    worker = db.get(Worker, worker_id)
    if worker is None or worker.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found"
        )
    return worker


def _get_work_log(db: DbSession, work_log_id: int) -> WorkLog:
    work_log = db.get(WorkLog, work_log_id)
    if work_log is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Work log not found"
        )
    return work_log


def _get_invoice(db: DbSession, project_id: int, invoice_id: int) -> Invoice:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None or invoice.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found"
        )
    return invoice


def _require_pending(event: ExtractedEvent) -> None:
    if event.status != ExtractedEventStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending extracted events can be changed",
        )


def _project_totals(db: DbSession, project_id: int) -> ProjectTotals:
    events = db.scalars(
        select(ExtractedEvent).where(
            ExtractedEvent.project_id == project_id,
            ExtractedEvent.status == ExtractedEventStatus.CONFIRMED,
        )
    )
    money_in = Decimal("0")
    money_out = Decimal("0")
    for event in events:
        if event.amount is None or event.type == ExtractedEventType.NOTE:
            continue
        if event.type == ExtractedEventType.MONEY_IN:
            money_in += event.amount
        elif event.type in {ExtractedEventType.MONEY_OUT, ExtractedEventType.PURCHASE}:
            money_out += event.amount
    return ProjectTotals(
        money_in=money_in, money_out=money_out, net=money_in - money_out
    )


def _work_log_total(quantity: Decimal, rate_per_unit: Decimal | None) -> Decimal | None:
    if rate_per_unit is None:
        return None
    return quantity * rate_per_unit


def _daily_worker_wage(worker: Worker | None, quantity: Decimal) -> Decimal | None:
    if (
        worker is None
        or worker.type != WorkerType.DAILY_WORKER
        or worker.daily_rate is None
    ):
        return None
    return Decimal(str(quantity)) * Decimal(str(worker.daily_rate))


SKILLED_ROLE_TERMS = {
    "welder",
    "electrician",
    "plumber",
    "painter",
    "tiler",
    "جوشکار",
    "برقکار",
    "گچ کار",
    "گچکار",
    "گچ‌کار",
    "رنگ کار",
    "رنگکار",
    "رنگ‌کار",
    "سرامیک کار",
    "سرامیککار",
    "سرامیک‌کار",
    "لوله کش",
    "لولهکش",
    "لوله‌کش",
    "سنگ کار",
    "سنگکار",
    "سنگ‌کار",
}


def _has_skilled_role(value: str | None) -> bool:
    if not value:
        return False
    normalized = normalize_text(value)
    return any(term in normalized for term in SKILLED_ROLE_TERMS)


def _display_worker_type(worker: Worker) -> WorkerType:
    if worker.type == WorkerType.DAILY_WORKER and (
        _has_skilled_role(worker.role_detail) or _has_skilled_role(worker.name)
    ):
        return WorkerType.SKILLED_WORKER
    return worker.type


def _display_worker_state_role(
    state: WorkerState, worker: Worker | None = None
) -> WorkerStateRole:
    if state.role == WorkerStateRole.DAILY and (
        _has_skilled_role(state.name)
        or (
            worker is not None
            and _display_worker_type(worker) == WorkerType.SKILLED_WORKER
        )
    ):
        return WorkerStateRole.SKILLED
    return state.role


def _invoice_paid_amount(db: DbSession, invoice_id: int) -> Decimal:
    return invoice_paid_amount(db, invoice_id)


def _refresh_invoice_status(db: DbSession, invoice: Invoice) -> None:
    paid_amount = _invoice_paid_amount(db, invoice.id)
    if paid_amount <= 0:
        invoice.status = InvoiceStatus.OPEN
    elif paid_amount >= invoice.total_amount:
        invoice.status = InvoiceStatus.PAID
    else:
        invoice.status = InvoiceStatus.PARTIAL


def _role_to_worker_type(role: str | None, event_type: str | None = None) -> WorkerType:
    if role == "CLIENT":
        return WorkerType.CLIENT
    if role == "VENDOR" or event_type == "INVOICE":
        return WorkerType.VENDOR
    if role in {"SKILLED", "SKILLED_WORKER"}:
        return WorkerType.SKILLED_WORKER
    if role == "OTHER":
        return WorkerType.OTHER
    if role == "WORKER" or event_type == "WORK_LOG":
        return WorkerType.DAILY_WORKER
    return WorkerType.OTHER


def _worker_type_for_entity(
    name: str,
    role: str | None,
    event_type: str | None = None,
) -> WorkerType:
    worker_type = _role_to_worker_type(role, event_type)
    if worker_type == WorkerType.DAILY_WORKER and _has_skilled_role(name):
        return WorkerType.SKILLED_WORKER
    return worker_type


def _role_to_state_role(
    role: str | None, text: str, intent: str | None = None
) -> WorkerStateRole:
    normalized = normalize_text(text)
    if role == "CLIENT":
        return WorkerStateRole.CLIENT
    if (
        role == "VENDOR"
        or intent == "INVOICE"
        or "خرید" in normalized
        or "فاکتور" in normalized
    ):
        return WorkerStateRole.VENDOR
    if "کارفرما" in normalized:
        return WorkerStateRole.CLIENT
    if _has_skilled_role(normalized) or role in {"SKILLED", "SKILLED_WORKER"}:
        return WorkerStateRole.SKILLED
    return WorkerStateRole.DAILY


def _find_or_create_worker(
    db: DbSession,
    project_id: int,
    name: str,
    worker_type: WorkerType,
) -> Worker:
    normalized_name = name.strip()
    worker = db.scalar(
        select(Worker).where(
            Worker.project_id == project_id,
            Worker.name == normalized_name,
            Worker.type == worker_type,
        )
    )
    if worker is not None:
        return worker
    if worker_type != WorkerType.VENDOR:
        worker = db.scalar(
            select(Worker).where(
                Worker.project_id == project_id, Worker.name == normalized_name
            )
        )
        if worker is not None:
            return worker
    worker = Worker(project_id=project_id, name=normalized_name, type=worker_type)
    db.add(worker)
    db.flush()
    return worker


def _state_role_to_worker_type(role: WorkerStateRole) -> WorkerType:
    if role == WorkerStateRole.CLIENT:
        return WorkerType.CLIENT
    if role == WorkerStateRole.VENDOR:
        return WorkerType.VENDOR
    if role == WorkerStateRole.SKILLED:
        return WorkerType.SKILLED_WORKER
    return WorkerType.DAILY_WORKER


def _find_or_create_worker_state(
    db: DbSession,
    project_id: int,
    name: str,
    role: WorkerStateRole,
) -> WorkerState:
    normalized_name = name.strip()
    state = db.scalar(
        select(WorkerState).where(
            WorkerState.project_id == project_id,
            WorkerState.name == normalized_name,
            WorkerState.role == role,
        )
    )
    if state is not None:
        return state
    if role != WorkerStateRole.VENDOR:
        state = db.scalar(
            select(WorkerState).where(
                WorkerState.project_id == project_id,
                WorkerState.name == normalized_name,
            )
        )
        if state is not None:
            return state

    worker = _find_or_create_worker(
        db,
        project_id,
        normalized_name,
        _state_role_to_worker_type(role),
    )
    state = WorkerState(
        project_id=project_id,
        worker_id=worker.id,
        name=normalized_name,
        role=role,
        total_days_worked=Decimal("0"),
        total_quantity=Decimal("0"),
        unit=None,
        financial_balance=Decimal("0"),
    )
    db.add(state)
    db.flush()
    return state


def _event_unit(value: Any) -> WorkUnit:
    if not isinstance(value, str):
        return WorkUnit.CUSTOM
    normalized = normalize_text(value)
    if normalized in {"day", "روز"}:
        return WorkUnit.DAY
    if normalized in {"meter", "متر"}:
        return WorkUnit.METER
    if normalized in {"item", "عدد"}:
        return WorkUnit.ITEM
    if normalized in {"project", "پروژه"}:
        return WorkUnit.PROJECT
    return WorkUnit.CUSTOM


def _parse_quantity(value: Any) -> Decimal | None:
    if value is None or not isinstance(value, str):
        return None
    match = re.search(r"\d+(?:\.\d+)?", normalize_text(value))
    if match is None:
        return None
    return Decimal(match.group())


def _parse_quantity_from_text(text: str) -> Decimal | None:
    normalized = normalize_text(text)
    meter_match = re.search(r"\d+(?:\.\d+)?\s*متر", normalized)
    if meter_match is not None:
        number_match = re.search(r"\d+(?:\.\d+)?", meter_match.group())
        return Decimal(number_match.group()) if number_match is not None else None
    day_match = re.search(r"\d+(?:\.\d+)?\s*روز", normalized)
    if day_match is not None:
        number_match = re.search(r"\d+(?:\.\d+)?", day_match.group())
        return Decimal(number_match.group()) if number_match is not None else None
    return None


def _unit_from_text(text: str, role: WorkerStateRole) -> str:
    normalized = normalize_text(text)
    if "متر" in normalized:
        return "meter"
    if role == WorkerStateRole.DAILY:
        return "day"
    return "unit"


def _history_delta(**values: Any) -> dict[str, str | int | float | None]:
    delta: dict[str, str | int | float | None] = {}
    for key, value in values.items():
        if isinstance(value, Decimal):
            delta[key] = str(value)
        elif isinstance(value, StrEnum):
            delta[key] = value.value
        elif isinstance(value, str | int | float) or value is None:
            delta[key] = value
        else:
            delta[key] = str(value)
    return delta


def _semantic_history_fields(event: CanonicalEvent) -> dict[str, Any]:
    explanation = event.metadata.get("semantic_explanation")
    conflict_warnings = event.metadata.get("conflict_warnings", [])
    return {
        "rule_id": event.metadata.get("rule_id"),
        "explanation": explanation if isinstance(explanation, dict) else None,
        "conflict_warnings": (
            conflict_warnings if isinstance(conflict_warnings, list) else []
        ),
    }


def _semantic_history_fields_from_pending(
    interpretation: PendingInterpretation,
) -> dict[str, Any]:
    explanation = interpretation.semantic_explanation
    return {
        "rule_id": (
            explanation.get("triggered_rule") if isinstance(explanation, dict) else None
        ),
        "explanation": explanation if isinstance(explanation, dict) else None,
        "conflict_warnings": [],
    }


def _build_pending_interpretations(
    project_id: int,
    raw_text: str,
    graph: dict[str, Any],
    canonical_event: CanonicalEvent,
    entity_context: list[Worker],
) -> list[PendingInterpretation]:
    events = graph.get("events")
    raw_events = events if isinstance(events, list) and len(events) > 1 else [None]
    interpretations: list[PendingInterpretation] = []
    for raw_event in raw_events:
        event_graph = dict(graph)
        if isinstance(raw_event, dict):
            event_graph["events"] = [raw_event]
            if raw_event.get("amount_text") is not None:
                event_graph["amount_text"] = raw_event.get("amount_text")
            if raw_event.get("quantity_text") is not None:
                event_graph["quantity_text"] = raw_event.get("quantity_text")
        effective_action = canonical_event.action
        effective_type = canonical_event.type
        if effective_type == CanonicalEventType.NOTE and _graph_setup_entities(
            event_graph
        ):
            effective_type = CanonicalEventType.SETUP
            effective_action = "SETUP"
        if (
            detect_purchase_payment(raw_text) is not None
            and effective_action == "PAYMENT"
            and not _purchase_has_debt_or_check_terms(raw_text)
        ):
            effective_action = "PURCHASE_PAID"
        payment_method = None
        if effective_action in {"CHECK_PAYMENT", "DEFERRED_PAYMENT"}:
            payment_method = PaymentType.CHECK.value
        elif effective_action == "PURCHASE_PAID":
            payment_method = PaymentType.CASH.value
        elif effective_type == CanonicalEventType.FINANCIAL:
            payment_method = _financial_payment_method_from_text(raw_text)
        incoming_project_payment = (
            detect_incoming_project_payment(raw_text)
            if effective_type == CanonicalEventType.FINANCIAL
            else None
        )
        purchase_payment = (
            detect_purchase_payment(raw_text)
            if effective_type == CanonicalEventType.FINANCIAL
            else None
        )
        draft_entities = _draft_entities(event_graph, canonical_event, raw_text)
        if incoming_project_payment is not None:
            draft_entities = [
                _pending_entity_dict(incoming_project_payment.payer_name, "CLIENT")
            ]
        elif purchase_payment is not None and purchase_payment.vendor_name is not None:
            draft_entities = [
                _pending_entity_dict(purchase_payment.vendor_name, "VENDOR")
            ]
        elif purchase_payment is not None and draft_entities:
            draft_entities[0] = {
                **draft_entities[0],
                "type": "VENDOR",
                "project_role": "VENDOR",
            }
        raw_entity_name = _draft_entity_name(draft_entities)
        resolved_entity = _resolve_existing_entity(
            raw_entity_name,
            entity_context,
            _draft_expected_role(draft_entities),
        )
        financial_direction = _financial_direction(
            raw_text,
            effective_type,
            effective_action,
            resolved_entity,
        )
        if incoming_project_payment is not None:
            financial_direction = FinancialDirection.INCOMING
            payment_method = PaymentType.BANK_TRANSFER.value
            _attach_candidate_matches(draft_entities, raw_entity_name, entity_context)
        elif purchase_payment is not None:
            if effective_action == "PURCHASE_PAID":
                financial_direction = FinancialDirection.OUTGOING
            payment_method = payment_method or PaymentType.CASH.value
        if resolved_entity is not None and draft_entities:
            draft_entities[0] = {
                **draft_entities[0],
                "name": resolved_entity.name,
                "type": resolved_entity.type.value,
                "project_role": resolved_entity.type.value,
            }
        interpretations.append(
            PendingInterpretation(
                project_id=project_id,
                raw_input_text=raw_text,
                canonical_event_type=effective_type.value,
                semantic_action=effective_action,
                suggested_entity_id=(
                    resolved_entity.id if resolved_entity is not None else None
                ),
                matched_input_text=(
                    raw_entity_name
                    if resolved_entity is not None
                    and raw_entity_name != resolved_entity.name
                    else None
                ),
                extracted_entities=draft_entities,
                extracted_amount=(
                    incoming_project_payment.amount
                    if incoming_project_payment is not None
                    and incoming_project_payment.amount is not None
                    else (
                        purchase_payment.amount
                        if purchase_payment is not None
                        and purchase_payment.amount is not None
                        else _graph_amount(event_graph, raw_text)
                    )
                ),
                extracted_quantity=_graph_quantity(event_graph),
                payment_method=payment_method,
                financial_direction=financial_direction,
                due_date=_extract_due_date(raw_text),
                description=_draft_description(event_graph, raw_text),
                semantic_explanation=canonical_event.metadata.get(
                    "semantic_explanation"
                ),
                confidence=canonical_event.metadata.get("confidence"),
                status=PendingInterpretationStatus.PENDING,
            )
        )
    return interpretations


def _draft_entities(
    graph: dict[str, Any],
    canonical_event: CanonicalEvent,
    raw_text: str,
) -> list[dict[str, Any]]:
    setup_entities = _graph_setup_entities(graph)
    if setup_entities:
        return setup_entities
    if canonical_event.type == CanonicalEventType.SETUP:
        parsed_setup_entities = _parse_setup_entities_from_text(raw_text)
        if parsed_setup_entities:
            return parsed_setup_entities
    entity_name = canonical_event.entity_name or _graph_entity_name(graph)
    if entity_name is None and canonical_event.type == CanonicalEventType.FINANCIAL:
        entity_name = _plain_outgoing_payment_counterparty_name(raw_text)
    if entity_name is None:
        return []
    role_guess = _graph_role_guess(graph)
    if role_guess is None and canonical_event.type == CanonicalEventType.FINANCIAL:
        role_guess = _pending_financial_role_guess(raw_text, canonical_event.action)
    return [_pending_entity_dict(entity_name, role_guess or "OTHER")]


def _financial_payment_method_from_text(raw_text: str) -> str:
    normalized = normalize_text(raw_text)
    bank_signals = ["حساب", "کارت", "واریز", "انتقال", "بانکی"]
    if any(signal in normalized for signal in bank_signals):
        return PaymentType.BANK_TRANSFER.value
    if any(signal in normalized for signal in ["چک", "سفته"]):
        return PaymentType.CHECK.value
    return PaymentType.CASH.value


def _plain_outgoing_payment_counterparty_name(raw_text: str) -> str | None:
    normalized = normalize_text(raw_text)
    if not any(verb in normalized for verb in ["دادم", "پرداخت کردم", "پرداختم"]):
        return None
    if any(signal in normalized for signal in ["خرید", "خریدم", "واریز", "حساب پروژه"]):
        return None

    match = re.search(
        r"\bبه\s+(?P<name>.+?)\s+(?:\d|[۰-۹]|[٠-٩]|یک|دو|سه|چهار|پنج|شش|هفت|هشت|نه|ده|صد|هزار|میلیون|میلیارد)",
        normalized,
    )
    if match is None:
        return None
    name = re.sub(r"\s+", " ", match.group("name")).strip(" ،,")
    return name or None


def _pending_financial_role_guess(raw_text: str, action: str) -> str | None:
    normalized = normalize_text(raw_text)
    if action in {"PURCHASE_PAID", "DEBT_CREATED", "CHECK_PAYMENT", "DEFERRED_PAYMENT"}:
        return "VENDOR"
    if "خرید" in normalized or "فاکتور" in normalized:
        return "VENDOR"
    return None


def _purchase_has_debt_or_check_terms(raw_text: str) -> bool:
    normalized = normalize_text(raw_text)
    return any(
        phrase in normalized
        for phrase in ["نسیه", "ندادم", "هنوز ندادم", "چک", "فاکتور", "بدهی"]
    )


def _pending_entity_dict(name: str, role: str) -> dict[str, Any]:
    entity_type = _role_to_worker_type(role).value
    return {
        "name": name,
        "type": entity_type,
        "project_role": entity_type,
    }


def _parse_setup_entities_from_text(text: str) -> list[dict[str, Any]]:
    normalized = normalize_text(text)
    if not _has_worker_setup_phrase(normalized):
        extracted_role = PersianRoleExtractor().extract(text)
        if extracted_role is not None:
            return [
                {
                    "type": extracted_role.worker_type.value,
                    "name": extracted_role.name,
                    "phone": None,
                    "account_number": None,
                    "role_detail": (
                        extracted_role.role_phrase
                        if extracted_role.worker_type == WorkerType.SKILLED_WORKER
                        else None
                    ),
                }
            ]
        return []
    names_part = re.split(r"\s+به عنوان\s+|\s+در پروژه\s+", normalized, maxsplit=1)[0]
    names_part = re.sub(r"^(کارگرها|کارگرهای پروژه)\s+", "", names_part).strip()
    raw_names = [part.strip(" ،,") for part in re.split(r"\s+و\s+|،|,", names_part)]
    entities: list[dict[str, Any]] = []
    for name in raw_names:
        if not name or name in {"و", "کارگر", "کارگرها"}:
            continue
        entities.append(
            {
                "type": "DAILY_WORKER",
                "name": name,
                "phone": None,
                "account_number": None,
                "role_detail": "کارگر ساده",
            }
        )
    return entities


def _has_worker_setup_phrase(normalized_text: str) -> bool:
    return any(
        phrase in normalized_text
        for phrase in [
            "به عنوان کارگر ساده",
            "کارگر ساده",
            "کارگرهای پروژه",
            "در پروژه کار میکنند",
            "در پروژه کار می کنند",
            "در پروژه کار می‌کنند",
        ]
    )


def _draft_entity_name(entities: list[dict[str, Any]]) -> str | None:
    if entities and isinstance(entities[0].get("name"), str):
        name = entities[0]["name"].strip()
        return name or None
    return None


def _draft_expected_role(entities: list[dict[str, Any]]) -> str | None:
    if not entities:
        return None
    role = (
        entities[0].get("project_role")
        or entities[0].get("type")
        or entities[0].get("role_guess")
    )
    if hasattr(role, "value"):
        role = role.value
    return role if isinstance(role, str) else None


def _attach_candidate_matches(
    entities: list[dict[str, Any]],
    raw_entity_name: str | None,
    entity_context: list[Worker],
) -> None:
    if not entities or not raw_entity_name:
        return
    resolution = resolve_candidates(raw_entity_name, entity_context)
    if resolution["candidates"]:
        entities[0]["candidate_matches"] = resolution["candidates"]


def _resolve_existing_entity(
    name: str | None,
    entity_context: list[Worker],
    expected_role: str | None = None,
) -> Worker | None:
    if name is None:
        return None
    normalized = _normalize_entity_match_text(name)
    if not normalized:
        return None
    compact = _compact_entity_match_text(name)
    candidates = entity_context
    if expected_role == "VENDOR":
        candidates = [
            worker for worker in entity_context if worker.type == WorkerType.VENDOR
        ]
    buckets: list[list[Worker]] = [
        [
            worker
            for worker in candidates
            if _normalize_entity_match_text(worker.name) == normalized
        ],
        [
            worker
            for worker in candidates
            if _compact_entity_match_text(worker.name) == compact
        ],
        [
            worker
            for worker in candidates
            if _normalize_entity_match_text(worker.name).startswith(normalized)
        ],
        [
            worker
            for worker in candidates
            if _compact_entity_match_text(worker.name).startswith(compact)
        ],
        [
            worker
            for worker in candidates
            if normalized in _normalize_entity_match_text(worker.name).split()
        ],
        [
            worker
            for worker in candidates
            if normalized in _normalize_entity_match_text(worker.name)
        ],
    ]
    for matches in buckets:
        unique = {worker.id: worker for worker in matches}
        if len(unique) == 1:
            return next(iter(unique.values()))
        if len(unique) > 1:
            return None
    return None


def _normalize_entity_match_text(value: str) -> str:
    normalized = normalize_text(value).replace("\u200c", " ").strip()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"^(مش|آقای|اقای|خانم)\s+", "", normalized)
    return normalized


def _compact_entity_match_text(value: str) -> str:
    return _normalize_entity_match_text(value).replace(" ", "")


def _financial_direction(
    raw_text: str,
    event_type: CanonicalEventType,
    action: str,
    resolved_entity: Worker | None,
) -> FinancialDirection | None:
    if event_type != CanonicalEventType.FINANCIAL:
        return None
    normalized = normalize_text(raw_text)
    if action in {"INVOICE", "DEBT_CREATED"}:
        return FinancialDirection.DEBT
    if action in {"CHECK_PAYMENT", "DEFERRED_PAYMENT"}:
        return FinancialDirection.DEFERRED
    if "دادم به" in normalized or "پرداخت کردم به" in normalized:
        return FinancialDirection.OUTGOING
    if action == "PURCHASE_PAID" or "خرید" in normalized:
        return FinancialDirection.OUTGOING
    if detect_incoming_project_payment(raw_text) is not None:
        return FinancialDirection.INCOMING
    if resolved_entity is not None and resolved_entity.type == WorkerType.CLIENT:
        incoming_phrases = [
            "پول داد",
            "پرداخت کرد",
            "واریز کرد",
            "داد برای",
            "برای پروژه واریز کرد",
        ]
        if any(phrase in normalized for phrase in incoming_phrases):
            return FinancialDirection.INCOMING
    return FinancialDirection.OUTGOING


def _draft_description(graph: dict[str, Any], raw_text: str) -> str:
    events = graph.get("events", [])
    if isinstance(events, list) and events and isinstance(events[0], dict):
        description = events[0].get("description")
        if isinstance(description, str) and description.strip():
            return description.strip()
    return raw_text


def _fallback_note_event(text: str) -> dict[str, Any]:
    return {
        "type": "NOTE",
        "amount_text": None,
        "counterparty_name": None,
        "counterparty_type": "UNKNOWN",
        "description": text,
        "confidence": 0.3,
    }


def _validate_llm_events(
    raw_events: list[dict[str, Any]], raw_text: str
) -> list[ExtractedEvent]:
    try:
        if not raw_events:
            raw_events = [_fallback_note_event(raw_text)]
        return [_validate_llm_event(raw_event, raw_text) for raw_event in raw_events]
    except (TypeError, ValueError, InvalidOperation):
        return [_validate_llm_event(_fallback_note_event(raw_text), raw_text)]


def _validate_llm_event(raw_event: dict[str, Any], raw_text: str) -> ExtractedEvent:
    if not isinstance(raw_event, dict):
        raise TypeError("LLM event must be an object")

    event_type = ExtractedEventType(raw_event.get("type"))
    counterparty_type = CounterpartyType(raw_event.get("counterparty_type", "UNKNOWN"))
    amount = _parse_llm_amount_text(raw_event.get("amount_text"))
    confidence = _validate_confidence(raw_event.get("confidence"))
    counterparty_name = _validate_optional_string(raw_event.get("counterparty_name"))
    description = raw_event.get("description")
    if not isinstance(description, str) or not description.strip():
        description = raw_text

    if event_type == ExtractedEventType.NOTE:
        amount = None

    return ExtractedEvent(
        type=event_type,
        amount=amount,
        counterparty_name=counterparty_name,
        counterparty_type=counterparty_type,
        description=description,
        event_date=None,
        confidence=confidence,
        ai_confidence=float(confidence),
        status=ExtractedEventStatus.PENDING,
    )


def _parse_llm_amount_text(value: Any) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    amount = parse_persian_money(value)
    if amount is not None:
        return Decimal(amount)
    return None


def _validate_confidence(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int | float):
        value = 0.3
    confidence = Decimal(str(value))
    if confidence < 0:
        return Decimal("0")
    if confidence > 1:
        return Decimal("1")
    return confidence


def _validate_event_date(value: Any) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise TypeError("event_date must be a string or null")
    return date.fromisoformat(value)


def _validate_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("value must be a string or null")
    return value or None


def _correction_value(value: Any) -> str | int | float | None:
    if value is None:
        return None
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str | int | float):
        return value
    return str(value)


@router.post(
    "/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED
)
def create_project(payload: ProjectCreate, db: DbSession) -> Project:
    project = Project(name=payload.name)
    db.add(project)
    db.commit()
    db.refresh(project)
    track_event(db=db, event_name="db.project_created", payload={"project_id": project.id, "name": project.name})
    return project


@router.get("/projects", response_model=list[ProjectRead])
def list_projects(db: DbSession) -> list[Project]:
    return list(
        db.scalars(
            select(Project).order_by(Project.created_at.desc(), Project.id.desc())
        )
    )


@router.get("/projects/{project_id}", response_model=ProjectDetail)
def get_project(project_id: int, db: DbSession) -> ProjectDetail:
    project = _get_project(db, project_id)
    return ProjectDetail(
        **ProjectRead.model_validate(project).model_dump(),
        totals=_project_totals(db, project_id),
    )


@router.post(
    "/projects/{project_id}/raw-entries",
    response_model=RawEntryRead,
    status_code=status.HTTP_201_CREATED,
)
def create_raw_entry(
    project_id: int, payload: RawEntryCreate, db: DbSession
) -> RawEntry:
    _get_project(db, project_id)
    raw_entry = RawEntry(project_id=project_id, text=payload.text)
    db.add(raw_entry)
    db.commit()
    db.refresh(raw_entry)
    return raw_entry


@router.get("/projects/{project_id}/raw-entries", response_model=list[RawEntryRead])
def list_raw_entries(project_id: int, db: DbSession) -> list[RawEntry]:
    _get_project(db, project_id)
    return list(
        db.scalars(
            select(RawEntry)
            .where(RawEntry.project_id == project_id)
            .order_by(RawEntry.created_at.desc(), RawEntry.id.desc())
        )
    )


@router.post(
    "/projects/{project_id}/natural-input",
    status_code=status.HTTP_202_ACCEPTED,
)
def process_natural_input(
    project_id: int,
    payload: NaturalInputCreate,
    db: DbSession,
):
    _get_project(db, project_id)

    job_id = str(uuid.uuid4())
    trace_id = get_trace_id() or str(uuid.uuid4())
    job = NaturalInputJob(
        job_id=job_id,
        project_id=project_id,
        trace_id=trace_id,
        status=NaturalInputJobStatus.PENDING,
    )
    db.add(job)
    db.commit()
    track_event(db=db, event_name="db.job_created", payload={"job_id": job_id, "project_id": project_id})

    queue = get_queue()
    try:
        queue.enqueue(
            "app.jobs.natural_input_job.process_natural_input_job",
            args=(job_id, project_id, payload.text),
            job_id=job_id,
            meta={"trace_id": trace_id},
        )
    except Exception as exc:
        job.status = NaturalInputJobStatus.FAILED
        job.error = str(exc)
        db.commit()
        track_event(db=db, event_name="db.job_enqueue_failed", payload={"job_id": job_id, "error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to enqueue natural input job",
        ) from exc

    track_event(db=db, event_name="db.job_enqueued", payload={"job_id": job_id, "project_id": project_id})
    return {"job_id": job_id, "status": "PENDING", "trace_id": trace_id}


@router.get("/natural-input-jobs/{job_id}")
def get_natural_input_job(job_id: str, db: DbSession) -> dict[str, Any]:
    mark_stale_natural_input_jobs_failed(db)
    job = db.query(NaturalInputJob).filter(NaturalInputJob.job_id == job_id).one_or_none()
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )
    response: dict[str, Any] = {
        "job_id": job.job_id,
        "status": job.status.value if hasattr(job.status, "value") else job.status,
        "result": normalize_outgoing_payment_roles_in_result(job.result),
        "trace_id": job.trace_id,
        "events_summary": _job_events_summary(job),
    }
    if job.error is not None:
        response["error"] = job.error
    return response


@router.get("/jobs")
def list_natural_input_jobs(db: DbSession) -> list[dict[str, Any]]:
    mark_stale_natural_input_jobs_failed(db)
    jobs = list(
        db.scalars(
            select(NaturalInputJob).order_by(
                NaturalInputJob.created_at.desc(),
                NaturalInputJob.id.desc(),
            )
        )
    )
    return [_job_list_item(job) for job in jobs]


@router.get("/jobs/{job_id}/events")
def get_natural_input_job_events(job_id: str, db: DbSession) -> dict[str, Any]:
    job = db.query(NaturalInputJob).filter(NaturalInputJob.job_id == job_id).one_or_none()
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )
    events = _job_persisted_events(job)
    if not events and job.trace_id is not None:
        from app.core.event_tracker import get_trace_events

        events = get_trace_events(job.trace_id, db=db)
    return {
        "job_id": job.job_id,
        "trace_id": job.trace_id,
        "events": sorted(events, key=lambda event: event.get("event_index", event.get("sequence_number", 0))),
    }


def mark_stale_natural_input_jobs_failed(
    db: DbSession,
    max_age_minutes: int = 15,
) -> int:
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=max_age_minutes)
    stale_jobs = list(
        db.scalars(
            select(NaturalInputJob).where(
                NaturalInputJob.status.in_(
                    [
                        NaturalInputJobStatus.PENDING,
                        NaturalInputJobStatus.RUNNING,
                    ]
                ),
                NaturalInputJob.updated_at < cutoff,
            )
        )
    )
    for job in stale_jobs:
        previous_status = job.status.value if hasattr(job.status, "value") else job.status
        job.status = NaturalInputJobStatus.FAILED
        job.error = job.error or "Job expired or worker stopped before completion"
        track_event(
            db=db,
            trace_id=job.trace_id,
            event_name="JOB_EXPIRED",
            payload={
                "job_id": job.job_id,
                "project_id": job.project_id,
                "previous_status": previous_status,
            },
        )
    if stale_jobs:
        db.commit()
    return len(stale_jobs)


def _job_list_item(job: NaturalInputJob) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "project_id": job.project_id,
        "status": job.status.value if hasattr(job.status, "value") else job.status,
        "trace_id": job.trace_id,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "duration_ms": _job_duration_ms(job),
        "error": job.error,
        "result_summary": _job_result_summary(job.result),
        "events_summary": _job_events_summary(job),
    }


def _job_duration_ms(job: NaturalInputJob) -> float | None:
    events = _job_events_summary(job)
    duration = sum(
        event["duration_ms"]
        for event in events
        if isinstance(event.get("duration_ms"), int | float)
    )
    return round(duration, 3) if duration else None


def _job_result_summary(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    interpretations = result.get("interpretations")
    summary: dict[str, Any] = {}
    if isinstance(interpretations, list):
        summary["interpretation_count"] = len(interpretations)
        actions = [
            item.get("semantic_action")
            for item in interpretations
            if isinstance(item, dict) and item.get("semantic_action")
        ]
        if actions:
            summary["semantic_actions"] = actions[:5]
    return summary or None


def _job_persisted_events(job: NaturalInputJob) -> list[dict[str, Any]]:
    if not isinstance(job.result, dict):
        return []
    events = job.result.get("_events")
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, dict)]


def _job_events_summary(job: NaturalInputJob) -> list[dict[str, Any]]:
    source_events = _job_persisted_events(job)
    if not source_events and job.trace_id is not None:
        from app.core.event_tracker import get_trace_events

        source_events = get_trace_events(job.trace_id)
    return [
        {
            "event": event.get("event_name") or event["event"],
            "sequence_number": event.get("event_index") or event.get("sequence_number"),
            "duration_ms": event.get("duration_ms"),
        }
        for event in source_events
        if event.get("event_name", event.get("event")) != "JOB_CREATED"
    ]


@router.get(
    "/projects/{project_id}/pending-interpretations",
    response_model=list[PendingInterpretationRead],
)
def list_pending_interpretations(
    project_id: int,
    db: DbSession,
) -> list[PendingInterpretation]:
    _get_project(db, project_id)
    return list(
        db.scalars(
            select(PendingInterpretation)
            .where(PendingInterpretation.project_id == project_id)
            .where(
                PendingInterpretation.status.in_(
                    [
                        PendingInterpretationStatus.PENDING,
                        PendingInterpretationStatus.EDITED,
                    ]
                )
            )
            .order_by(
                PendingInterpretation.created_at.desc(), PendingInterpretation.id.desc()
            )
        )
    )


@router.patch(
    "/pending-interpretations/{interpretation_id}",
    response_model=PendingInterpretationRead,
)
def update_pending_interpretation(
    interpretation_id: int,
    payload: PendingInterpretationUpdate,
    db: DbSession,
) -> PendingInterpretation:
    interpretation = _get_pending_interpretation(db, interpretation_id)
    if interpretation.status not in {
        PendingInterpretationStatus.PENDING,
        PendingInterpretationStatus.EDITED,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Interpretation is closed"
        )
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(interpretation, key, value)
    interpretation.status = PendingInterpretationStatus.EDITED
    db.commit()
    db.refresh(interpretation)
    return interpretation


@router.post(
    "/pending-interpretations/{interpretation_id}/discard",
    response_model=PendingInterpretationRead,
)
def discard_pending_interpretation(
    interpretation_id: int,
    db: DbSession,
) -> PendingInterpretation:
    interpretation = _get_pending_interpretation(db, interpretation_id)
    if interpretation.status == PendingInterpretationStatus.CONFIRMED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Interpretation confirmed"
        )
    interpretation.status = PendingInterpretationStatus.DISCARDED
    db.commit()
    db.refresh(interpretation)
    return interpretation


@router.post(
    "/pending-interpretations/{interpretation_id}/confirm",
    response_model=NaturalInputResult | EntityResolutionResult,
)
def confirm_pending_interpretation(
    interpretation_id: int,
    db: DbSession,
    payload: PendingInterpretationConfirm | None = Body(default=None),
) -> NaturalInputResult | EntityResolutionResult:
    db_write_start = perf_counter()
    if not isinstance(payload, PendingInterpretationConfirm):
        payload = PendingInterpretationConfirm()
    try:
        _normalize_confirm_identity_payload(payload)
        interpretation = _get_pending_interpretation(db, interpretation_id)
        if interpretation.status not in {
            PendingInterpretationStatus.PENDING,
            PendingInterpretationStatus.EDITED,
        }:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Interpretation is closed"
            )
        route = _domain_route(interpretation, db=db)
        if route["domain"] == DomainType.MIXED.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Mixed setup and financial input must be split before confirmation",
            )
        resolution_result = _resolve_entity_phase_if_needed(db, interpretation, payload)
        if resolution_result is not None:
            db.commit()
            track_event(
                db=db,
                event_name="DB_WRITE_SUCCESS",
                duration_ms=round((perf_counter() - db_write_start) * 1000, 3),
                payload={
                    "pending_interpretation_id": interpretation.id,
                    "stage": "entity_resolution",
                },
            )
            track_event(
                db=db,
                event_name="db.entity_resolved",
                payload={"interpretation_id": interpretation.id, "entity_id": resolution_result["entity_id"]},
            )
            return EntityResolutionResult(
                status="ENTITY_RESOLVED",
                entity_id=resolution_result["entity_id"],
                is_new=resolution_result["is_new"],
                name=resolution_result["name"],
                role=resolution_result["role"],
                requires_confirmation=False,
            )
        result = _execute_pending_interpretation(db, interpretation, payload)
        interpretation.status = PendingInterpretationStatus.CONFIRMED
        db.commit()
        track_event(
            db=db,
            event_name="DB_WRITE_SUCCESS",
            duration_ms=round((perf_counter() - db_write_start) * 1000, 3),
            payload={"pending_interpretation_id": interpretation.id, "stage": "confirmation"},
        )
        db.refresh(interpretation)
        track_event(
            db=db,
            event_name="db.interpretation_confirmed",
            payload={"interpretation_id": interpretation.id, "project_id": interpretation.project_id},
        )
        if not _execution_engine_primary_enabled(interpretation):
            _run_execution_engine_shadow(db, interpretation, payload, result)
        return result
    except Exception as exc:
        track_event(db=db, event_name="db.confirmation_failed", payload={"interpretation_id": interpretation_id, "error": str(exc)})
        track_event(db=db, event_name="ERROR_OCCURRED", payload={"pending_interpretation_id": interpretation_id, "error_message": str(exc)})
        raise


def _get_pending_interpretation(
    db: DbSession, interpretation_id: int
) -> PendingInterpretation:
    interpretation = db.get(PendingInterpretation, interpretation_id)
    if interpretation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Interpretation not found",
        )
    return interpretation


def _execute_pending_interpretation(
    db: DbSession,
    interpretation: PendingInterpretation,
    payload: PendingInterpretationConfirm,
) -> NaturalInputResult:
    _apply_create_new_confirmation_payload(interpretation, payload)
    _apply_confirmation_edit_payload(interpretation, payload)
    route = _domain_route(interpretation, db=db)
    if route["domain"] == DomainType.SETUP.value and _execution_engine_primary_enabled(
        interpretation
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Setup domain must not use financial execution",
        )
    if interpretation.structured_interpretation is not None:
        _validate_llm_v2_confirmation_safety(db, interpretation, payload)
        if _execution_engine_primary_enabled(interpretation):
            return _execute_with_execution_engine_primary(db, interpretation, payload)
        return _execute_llm_v2_interpretation(db, interpretation, payload)

    _validate_legacy_confirmation_safety(db, interpretation, payload)
    if _execution_engine_primary_enabled(interpretation):
        return _execute_with_execution_engine_primary(db, interpretation, payload)
    return _execute_legacy_interpretation(db, interpretation, payload)


def _apply_confirmation_edit_payload(
    interpretation: PendingInterpretation,
    payload: PendingInterpretationConfirm,
) -> None:
    if payload.amount is not None:
        interpretation.extracted_amount = payload.amount
        _set_structured_financial_value(interpretation, "amount", str(payload.amount))
    if payload.direction is not None:
        interpretation.financial_direction = payload.direction
        _set_structured_financial_value(interpretation, "direction", _structured_direction_value(payload.direction))
    if payload.payment_method is not None:
        interpretation.payment_method = payload.payment_method.value
        _set_structured_financial_value(interpretation, "payment_method", payload.payment_method.value)
    if payload.description is not None:
        interpretation.description = payload.description.strip() or None
    if payload.due_date is not None:
        interpretation.due_date = payload.due_date.strip() or None
        _set_structured_financial_value(interpretation, "due_date_text", interpretation.due_date)
    if isinstance(payload.field_updates, dict) and payload.field_updates:
        _apply_field_updates_to_pending_entity(interpretation, payload.field_updates)


def _set_structured_financial_value(
    interpretation: PendingInterpretation,
    key: str,
    value: Any,
) -> None:
    structured = interpretation.structured_interpretation
    if not isinstance(structured, dict):
        return
    financial = structured.get("financial")
    if not isinstance(financial, dict):
        financial = {}
    financial[key] = value
    structured["financial"] = financial
    interpretation.structured_interpretation = structured


def _structured_direction_value(direction: FinancialDirection) -> str:
    if direction == FinancialDirection.INCOMING:
        return "IN"
    if direction in {
        FinancialDirection.OUTGOING,
        FinancialDirection.DEBT,
        FinancialDirection.DEFERRED,
    }:
        return "OUT"
    return "NONE"


def _apply_field_updates_to_pending_entity(
    interpretation: PendingInterpretation,
    updates: dict[str, Any],
) -> None:
    allowed = {
        "phone",
        "account_number",
        "daily_rate",
        "notes",
        "role_detail",
        "project_role",
        "type",
    }
    clean = {key: value for key, value in updates.items() if key in allowed}
    if not clean:
        return
    entities = list(interpretation.extracted_entities or [{}])
    entity = dict(entities[0] if entities else {})
    field_updates = entity.get("field_updates")
    if not isinstance(field_updates, dict):
        field_updates = {}
    field_updates.update(clean)
    entity.update(clean)
    if "project_role" in clean:
        entity["type"] = clean["project_role"]
    if "type" in clean:
        entity["project_role"] = clean["type"]
    entity["field_updates"] = field_updates
    entities[0] = entity
    interpretation.extracted_entities = entities


def _normalize_confirm_identity_payload(payload: PendingInterpretationConfirm) -> int | None:
    selected_entity_id = (
        payload.entity_id
        or payload.person_id
        or payload.selected_person_id
        or payload.selected_entity_id
    )
    if selected_entity_id is not None:
        payload.entity_id = selected_entity_id
        payload.person_id = selected_entity_id
        payload.selected_person_id = selected_entity_id
        payload.selected_entity_id = selected_entity_id
    return selected_entity_id


def _selected_entity_id(payload: PendingInterpretationConfirm) -> int | None:
    return (
        payload.entity_id
        or payload.person_id
        or payload.selected_person_id
        or payload.selected_entity_id
    )


def _resolve_entity_phase_if_needed(
    db: DbSession,
    interpretation: PendingInterpretation,
    payload: PendingInterpretationConfirm,
) -> dict[str, Any] | None:
    if not _execution_engine_primary_enabled(interpretation):
        return None
    if payload.entity_id is not None and payload.confirmed:
        payload.selected_person_id = payload.entity_id
        interpretation.suggested_entity_id = payload.entity_id
        return None
    if payload.entity_id is not None and not payload.confirmed:
        return _resolve_entity_phase(db, interpretation, payload, payload.entity_id)
    if payload.selected_person_id is not None and payload.confirmed:
        payload.entity_id = payload.selected_person_id
        interpretation.suggested_entity_id = payload.selected_person_id
        return None
    if payload.selected_person_id is not None:
        return _resolve_entity_phase(
            db, interpretation, payload, payload.selected_person_id
        )

    entity_name = payload.name or _pending_entity_name(interpretation)
    entity_role = payload.role or _entity_resolution_role(interpretation)
    return _resolve_entity_phase(
        db,
        interpretation,
        payload,
        None,
        entity_name,
        entity_role,
        payload.role_detail,
        payload.create_new,
    )


def _domain_route(interpretation: PendingInterpretation, db: Session | None = None) -> dict[str, Any]:
    route_input: dict[str, Any] = {
        "semantic_action": interpretation.semantic_action,
        "action": interpretation.semantic_action,
        "entities": interpretation.extracted_entities or [],
        "extracted_entities": interpretation.extracted_entities or [],
        "financial": {
            "amount": interpretation.extracted_amount,
            "direction": interpretation.financial_direction.value if interpretation.financial_direction is not None else None,
        },
    }
    if isinstance(interpretation.structured_interpretation, dict):
        route_input.update(interpretation.structured_interpretation)
        route_input.setdefault("semantic_action", interpretation.semantic_action)
        route_input.setdefault("action", interpretation.semantic_action)
        if not route_input.get("entities"):
            route_input["entities"] = interpretation.extracted_entities or []
        if not route_input.get("extracted_entities"):
            route_input["extracted_entities"] = interpretation.extracted_entities or []
    return DomainRouterService().route(
        interpretation.raw_input_text,
        route_input,
        db=db,
    )


def _resolve_entity_phase(
    db: DbSession,
    interpretation: PendingInterpretation,
    payload: PendingInterpretationConfirm,
    entity_id: int | None = None,
    entity_name: str | None = None,
    entity_role: str | WorkerType | None = None,
    role_detail: str | None = None,
    create_new: bool = False,
) -> dict[str, Any]:
    try:
        resolved = EntityResolutionService(db, interpretation.project_id).resolve(
            entity_id=entity_id,
            name=entity_name,
            role=entity_role,
            role_detail=role_detail,
            create_new=create_new,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    interpretation.suggested_entity_id = resolved["entity_id"]
    payload.entity_id = resolved["entity_id"]
    payload.selected_person_id = resolved["entity_id"]
    entities = list(interpretation.extracted_entities or [{}])
    entity = dict(entities[0] if entities else {})
    entity.update(
        {
            "name": resolved["name"],
            "type": resolved["role"],
            "project_role": resolved["role"],
        }
    )
    entity.pop("create_new", None)
    entities[0] = entity
    interpretation.extracted_entities = entities
    return resolved


def _entity_resolution_role(interpretation: PendingInterpretation) -> str:
    entities = interpretation.extracted_entities or []
    if entities:
        entity = entities[0]
        role = (
            entity.get("project_role") or entity.get("type") or entity.get("role_guess")
        )
        if isinstance(role, str) and role:
            return role
    if interpretation.financial_direction == FinancialDirection.INCOMING:
        return WorkerType.CLIENT.value
    return WorkerType.VENDOR.value


def _execution_engine_primary_enabled(interpretation: PendingInterpretation) -> bool:
    return (
        USE_EXECUTION_ENGINE
        and interpretation.canonical_event_type == CanonicalEventType.FINANCIAL.value
    )


def _run_execution_engine_shadow(
    db: DbSession,
    interpretation: PendingInterpretation,
    payload: PendingInterpretationConfirm,
    old_result: NaturalInputResult,
) -> None:
    confirmed = _confirmed_financial_interpretation_for_shadow(
        interpretation,
        payload,
        old_result,
    )
    if confirmed is None:
        return
    try:
        state = _shadow_state_for_confirmed_person(db, confirmed)
        shadow_result = ExecutionEngine().execute_confirmed_interpretation(
            confirmed,
            db,
            state,
        )
        comparison = ExecutionComparator().compare(old_result, shadow_result)
        logger.info(
            "execution_engine_shadow_comparison",
            extra={
                "pending_interpretation_id": interpretation.id,
                "project_id": interpretation.project_id,
                "comparison": comparison,
            },
        )
    except Exception:
        logger.exception(
            "execution_engine_shadow_failed",
            extra={
                "pending_interpretation_id": interpretation.id,
                "project_id": interpretation.project_id,
            },
        )


def _execute_with_execution_engine_primary(
    db: DbSession,
    interpretation: PendingInterpretation,
    payload: PendingInterpretationConfirm,
) -> NaturalInputResult:
    raw_entry = RawEntry(
        project_id=interpretation.project_id,
        text=interpretation.raw_input_text,
        status=RawEntryStatus.PROCESSED,
    )
    db.add(raw_entry)
    db.flush()

    worker = _execution_engine_worker(db, interpretation, payload)
    state = _shadow_state_for_confirmed_person(
        db,
        ConfirmedFinancialInterpretation(
            project_id=interpretation.project_id,
            semantic_action=interpretation.semantic_action,
            amount=interpretation.extracted_amount,
            entity_id=worker.id,
            financial_direction=interpretation.financial_direction,
            payment_method=interpretation.payment_method,
            due_date=interpretation.due_date,
            description=interpretation.description,
        ),
    )
    confirmed = ConfirmedFinancialInterpretation(
        project_id=interpretation.project_id,
        semantic_action=interpretation.semantic_action,
        amount=interpretation.extracted_amount,
        entity_id=worker.id,
        financial_direction=interpretation.financial_direction,
        payment_method=interpretation.payment_method,
        due_date=interpretation.due_date,
        description=interpretation.description,
    )
    engine_result = ExecutionEngine().execute_confirmed_interpretation(
        confirmed,
        db,
        state,
    )
    payments = [
        payment
        for payment_id in _result_ids(engine_result, "payments")
        if (payment := db.get(Payment, payment_id)) is not None
    ]
    invoices = [
        invoice
        for invoice_id in _result_ids(engine_result, "invoices")
        if (invoice := db.get(Invoice, invoice_id)) is not None
    ]
    state = _shadow_state_for_confirmed_person(db, confirmed)
    states = [state] if state is not None else []
    change_type = HistoryChangeType.INVOICE if invoices else HistoryChangeType.PAYMENT
    history_entries = []
    if state is not None:
        history_entries.append(
            _add_history(
                db,
                interpretation.project_id,
                state,
                interpretation.raw_input_text,
                change_type,
                _history_delta(
                    canonical_event_type=interpretation.canonical_event_type,
                    semantic_action=interpretation.semantic_action,
                    amount=interpretation.extracted_amount,
                    balance=state.financial_balance,
                    payment_method=interpretation.payment_method,
                    due_date=interpretation.due_date,
                    financial_direction=(
                        interpretation.financial_direction.value
                        if interpretation.financial_direction is not None
                        else None
                    ),
                ),
                _semantic_history_fields_from_pending(interpretation),
            )
        )
    db.flush()
    for item in [worker, *states, *history_entries, *payments, *invoices]:
        db.refresh(item)
    result = NaturalInputResult(
        raw_entry_id=raw_entry.id,
        intent=interpretation.canonical_event_type,
        workers=[worker],
        states=states,
        history_entries=history_entries,
        work_logs=[],
        invoices=invoices,
        payments=payments,
    )
    logger.info(
        "confirmed_interpretation_executed",
        extra={
            "engine": "execution_engine",
            "pending_interpretation_id": interpretation.id,
            "project_id": interpretation.project_id,
            "summary": _execution_result_summary(result),
        },
    )
    _run_legacy_execution_shadow(db, interpretation, payload, result)
    return result


def _execution_engine_worker(
    db: DbSession,
    interpretation: PendingInterpretation,
    payload: PendingInterpretationConfirm,
) -> Worker:
    entity_id = (
        payload.entity_id
        or payload.selected_person_id
        or interpretation.suggested_entity_id
    )
    if entity_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Entity must be resolved before execution",
        )
    payload.entity_id = entity_id
    payload.selected_person_id = entity_id
    worker = _get_selected_worker(db, interpretation, payload)
    if worker is not None:
        return worker
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Entity must be resolved before execution",
    )


def _pending_allows_new_financial_vendor(interpretation: PendingInterpretation) -> bool:
    if interpretation.structured_interpretation is None:
        return _pending_allows_new_legacy_vendor(interpretation)
    try:
        from app.schemas.llm_v2 import LLMv2Interpretation

        si = LLMv2Interpretation(**interpretation.structured_interpretation)
    except Exception:
        return False
    return _pending_allows_new_llm_v2_vendor(interpretation, si)


def _result_ids(engine_result: dict[str, Any], key: str) -> list[int]:
    ids: list[int] = []
    for item in engine_result.get(key) or []:
        item_id = item.get("id") if isinstance(item, dict) else None
        if isinstance(item_id, int):
            ids.append(item_id)
    return ids


def _run_legacy_execution_shadow(
    db: DbSession,
    interpretation: PendingInterpretation,
    payload: PendingInterpretationConfirm,
    engine_result: NaturalInputResult,
) -> None:
    transaction = db.begin_nested()
    try:
        legacy_result = (
            _execute_llm_v2_interpretation(db, interpretation, payload)
            if interpretation.structured_interpretation is not None
            else _execute_legacy_interpretation(db, interpretation, payload)
        )
        comparison = ExecutionComparator().compare(
            legacy_result, _natural_result_to_engine_dict(engine_result)
        )
        logger.info(
            "legacy_execution_shadow_comparison",
            extra={
                "pending_interpretation_id": interpretation.id,
                "project_id": interpretation.project_id,
                "comparison": comparison,
            },
        )
    except Exception:
        logger.exception(
            "legacy_execution_shadow_failed",
            extra={
                "pending_interpretation_id": interpretation.id,
                "project_id": interpretation.project_id,
            },
        )
    finally:
        transaction.rollback()


def _natural_result_to_engine_dict(result: NaturalInputResult) -> dict[str, Any]:
    return {
        "payments": [
            {
                "entity_id": payment.entity_id,
                "amount": str(payment.amount),
                "type": payment.type.value,
                "direction": payment.direction.value,
                "due_date": payment.due_date,
                "related_invoice_id": payment.related_invoice_id,
            }
            for payment in result.payments
        ],
        "invoices": [
            {
                "vendor_id": invoice.vendor_id,
                "total_amount": str(invoice.total_amount),
                "description": invoice.description,
                "status": invoice.status.value,
            }
            for invoice in result.invoices
        ],
    }


def _execution_result_summary(result: NaturalInputResult) -> dict[str, Any]:
    return {
        "payments": len(result.payments),
        "invoices": len(result.invoices),
        "workers": len(result.workers),
        "states": len(result.states),
    }


def _confirmed_financial_interpretation_for_shadow(
    interpretation: PendingInterpretation,
    payload: PendingInterpretationConfirm,
    old_result: NaturalInputResult,
) -> ConfirmedFinancialInterpretation | None:
    if interpretation.canonical_event_type != CanonicalEventType.FINANCIAL.value:
        return None
    entity_id = _shadow_selected_person_id(interpretation, payload, old_result)
    return ConfirmedFinancialInterpretation(
        project_id=interpretation.project_id,
        semantic_action=interpretation.semantic_action,
        amount=interpretation.extracted_amount,
        entity_id=entity_id,
        financial_direction=interpretation.financial_direction,
        payment_method=interpretation.payment_method,
        due_date=interpretation.due_date,
        description=interpretation.description,
    )


def _shadow_selected_person_id(
    interpretation: PendingInterpretation,
    payload: PendingInterpretationConfirm,
    old_result: NaturalInputResult,
) -> int | None:
    if payload.entity_id is not None:
        return payload.entity_id
    if payload.selected_person_id is not None:
        return payload.selected_person_id
    if interpretation.suggested_entity_id is not None:
        return interpretation.suggested_entity_id
    if old_result.payments:
        return old_result.payments[0].entity_id
    if old_result.invoices:
        return old_result.invoices[0].vendor_id
    if old_result.workers:
        return old_result.workers[0].id
    return None


def _shadow_state_for_confirmed_person(
    db: DbSession,
    confirmed: ConfirmedFinancialInterpretation,
) -> WorkerState | None:
    if confirmed.entity_id is None:
        return None
    return db.scalar(
        select(WorkerState).where(
            WorkerState.project_id == confirmed.project_id,
            WorkerState.worker_id == confirmed.entity_id,
        )
    )


def _apply_create_new_confirmation_payload(
    interpretation: PendingInterpretation,
    payload: PendingInterpretationConfirm,
) -> None:
    if not payload.create_new:
        return
    if not _allows_create_new_confirmation(interpretation):
        return
    if payload.name is None and payload.role is None and payload.role_detail is None:
        return

    name = payload.name.strip() if isinstance(payload.name, str) else ""
    role = payload.role.strip() if isinstance(payload.role, str) else ""
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Create-new confirmation requires a name",
        )
    if not role:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Create-new confirmation requires a role",
        )
    worker_type = _llm_v2_role_to_worker_type(role)
    if worker_type == WorkerType.OTHER and role != "OTHER":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Create-new confirmation role is invalid",
        )

    entities = list(interpretation.extracted_entities or [{}])
    entity = dict(entities[0] if entities else {})
    entity.update(
        {
            "name": name,
            "type": worker_type.value,
            "project_role": worker_type.value,
            "create_new": True,
        }
    )
    if isinstance(payload.role_detail, str) and payload.role_detail.strip():
        entity["role_detail"] = payload.role_detail.strip()
    else:
        entity["role_detail"] = None
    if isinstance(payload.field_updates, dict) and payload.field_updates:
        entity.setdefault("field_updates", {})
        for k, v in payload.field_updates.items():
            if k in {"phone", "account_number", "daily_rate", "notes"}:
                entity[k] = v
                entity["field_updates"][k] = v
    entities[0] = entity
    interpretation.extracted_entities = entities


def _allows_create_new_confirmation(interpretation: PendingInterpretation) -> bool:
    if interpretation.canonical_event_type not in {
        CanonicalEventType.SETUP.value,
        CanonicalEventType.FINANCIAL.value,
        "SETUP_EVENT",
    }:
        return False
    if interpretation.semantic_action in {"SETUP", "SET_ROLE", "ADD_ENTITY", "ENTITY_UPDATE"}:
        return True
    structured = interpretation.structured_interpretation
    return bool(
        isinstance(structured, dict)
        and structured.get("intent") in {"SETUP", "SET_ROLE", "FINANCIAL"}
        and structured.get("action") in {"ADD_ENTITY", "SET_ROLE"}
    )


def _validate_legacy_confirmation_safety(
    db: DbSession,
    interpretation: PendingInterpretation,
    payload: PendingInterpretationConfirm,
) -> None:
    _require_explicit_entity_selection(db, interpretation, payload)
    if (
        _pending_requires_entity_confirmation(interpretation)
        and _selected_entity_id(payload) is None
        and not payload.create_new
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Entity creation requires confirmation",
        )
    if (
        interpretation.canonical_event_type == CanonicalEventType.SETUP.value
        and interpretation.semantic_action == "ENTITY_UPDATE"
        and _has_entity_field_updates(interpretation.extracted_entities or [])
        and _get_selected_worker(db, interpretation, payload) is None
        and _pending_worker(db, interpretation) is None
        and not _pending_allows_new_entity(interpretation)
        and not (payload.create_new and payload.name and payload.role)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_needs_selection_payload(db, interpretation),
        )


def _require_explicit_entity_selection(
    db: DbSession,
    interpretation: PendingInterpretation,
    payload: PendingInterpretationConfirm,
) -> None:
    import logging as _logging
    _log = _logging.getLogger(__name__)
    _log.error("DEBUG _require_explicit_entity_selection: canonical_event_type=%s semantic_action=%s create_new=%s entity_id=%s selected_person_id=%s _requires_ui=%s _is_update=%s",
               interpretation.canonical_event_type, interpretation.semantic_action,
               payload.create_new, payload.entity_id, payload.selected_person_id,
               _requires_ui_identity_decision(interpretation),
               _is_update_entity_interpretation(interpretation))
    if not _requires_ui_identity_decision(interpretation):
        return
    if (
        _selected_entity_id(payload) is not None
        and _get_selected_worker(db, interpretation, payload) is not None
    ):
        return
    if payload.create_new and not _is_update_entity_interpretation(interpretation):
        return
    if payload.create_new and _is_update_entity_interpretation(interpretation):
        if payload.name and payload.role:
            return
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=_needs_selection_payload(db, interpretation),
    )


def _is_update_entity_interpretation(interpretation: PendingInterpretation) -> bool:
    if (
        interpretation.canonical_event_type == CanonicalEventType.SETUP.value
        and interpretation.semantic_action == "ENTITY_UPDATE"
    ):
        return True
    structured = interpretation.structured_interpretation
    return bool(
        isinstance(structured, dict)
        and structured.get("intent") == "SETUP"
        and structured.get("action") == "UPDATE_ENTITY"
    )


def _needs_selection_payload(
    db: DbSession,
    interpretation: PendingInterpretation,
) -> dict[str, Any]:
    workers = {
        worker.id: worker
        for worker in db.scalars(
            select(Worker).where(Worker.project_id == interpretation.project_id)
        )
    }
    name = _pending_entity_name(interpretation) or interpretation.raw_input_text
    resolution = resolve_candidates(name, list(workers.values()))
    candidates = []
    for candidate in resolution["candidates"]:
        worker = workers.get(candidate["person_id"])
        if worker is None:
            continue
        candidates.append(
            {
                "person_id": worker.id,
                "worker_id": worker.id,
                "name": worker.name,
                "type": worker.type.value,
                "score": candidate["score"],
                "match_type": candidate["match_type"],
            }
        )
    return {
        "status": "NEEDS_SELECTION",
        "candidates": candidates,
    }


def _requires_ui_identity_decision(interpretation: PendingInterpretation) -> bool:
    if interpretation.canonical_event_type == CanonicalEventType.SETUP.value:
        return True
    structured = interpretation.structured_interpretation
    return bool(
        isinstance(structured, dict)
        and structured.get("intent") in {"SETUP", "SET_ROLE"}
        and structured.get("action") in {"SET_ROLE", "ADD_ENTITY", "UPDATE_ENTITY"}
    )


def _get_selected_worker(
    db: DbSession,
    interpretation: PendingInterpretation,
    payload: PendingInterpretationConfirm,
) -> Worker | None:
    selected_id = _selected_entity_id(payload)
    if selected_id is None:
        return None
    worker = db.get(Worker, selected_id)
    if worker is None or worker.project_id != interpretation.project_id:
        return None
    return worker


def _validate_llm_v2_confirmation_safety(
    db: DbSession,
    interpretation: PendingInterpretation,
    payload: PendingInterpretationConfirm,
) -> None:
    from app.schemas.llm_v2 import (
        LLMv2Action,
        LLMv2FinancialDirection,
        LLMv2Intent,
        LLMv2Interpretation,
        LLMv2ProjectRole,
    )

    si = LLMv2Interpretation(**interpretation.structured_interpretation)
    _require_explicit_entity_selection(db, interpretation, payload)
    if (
        _pending_requires_entity_confirmation(interpretation)
        and _selected_entity_id(payload) is None
        and not payload.create_new
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Entity creation requires confirmation",
        )
    if (
        si.intent == LLMv2Intent.SETUP
        and si.action == LLMv2Action.UPDATE_ENTITY
        and _has_entity_field_updates(interpretation.extracted_entities or [])
        and _get_selected_worker(db, interpretation, payload) is None
        and _pending_worker(db, interpretation) is None
        and not _pending_allows_new_entity(interpretation)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_needs_selection_payload(db, interpretation),
        )

    if si.intent != LLMv2Intent.FINANCIAL:
        return

    if _execution_engine_primary_enabled(interpretation) and (
        _selected_entity_id(payload) is None
        and interpretation.suggested_entity_id is None
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Entity must be resolved before execution",
        )

    amount = (
        interpretation.extracted_amount
        if interpretation.extracted_amount is not None
        else si.financial.amount
    )
    if amount is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Financial interpretation requires an amount before confirmation",
        )

    structured_direction = si.financial.direction
    if (
        structured_direction == LLMv2FinancialDirection.NONE
        and interpretation.financial_direction is None
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Financial interpretation requires a direction before confirmation",
        )

    worker = _get_selected_worker(db, interpretation, payload) or _pending_worker(
        db, interpretation
    )
    expected_role = si.entities[0].project_role if si.entities else None
    if (
        worker is not None
        and expected_role == LLMv2ProjectRole.VENDOR
        and worker.type != WorkerType.VENDOR
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Matched entity role conflicts with expected vendor role",
        )
    if worker is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Financial interpretation requires a resolved entity",
        )


def _execute_llm_v2_interpretation(
    db: DbSession,
    interpretation: PendingInterpretation,
    payload: PendingInterpretationConfirm,
) -> NaturalInputResult:
    """Deprecated — legacy structured writer for Payment/Invoice/WorkerState.

    This path writes financial records directly (Payment, Invoice, WorkerState)
    WITHOUT going through ExecutionEngine.  It is retained only for:
      - shadow/fallback execution when ExecutionEngine is primary (runs inside a
        savepoint that is always rolled back — see `_run_legacy_execution_shadow`)
      - primary execution when the YARA_USE_EXECUTION_ENGINE feature flag is
        explicitly set to 0/false (not recommended)

    Must not be used in the default production path.  New financial writes
    should only be added to ExecutionEngine.
    """
    from app.schemas.llm_v2 import (
        LLMv2Action,
        LLMv2Intent,
        LLMv2Interpretation,
    )

    si = LLMv2Interpretation(**interpretation.structured_interpretation)
    raw_entry = RawEntry(
        project_id=interpretation.project_id,
        text=interpretation.raw_input_text,
        status=RawEntryStatus.PROCESSED,
    )
    db.add(raw_entry)
    db.flush()
    semantic_history = _semantic_history_fields_from_pending(interpretation)
    workers: list[Worker] = []
    states: list[WorkerState] = []
    history_entries: list[HistoryEntry] = []
    work_logs: list[WorkLog] = []
    invoices: list[Invoice] = []
    payments: list[Payment] = []

    intent = si.intent
    action = si.action
    confirmed_action = _confirmed_llm_v2_action(interpretation, action)

    if intent == LLMv2Intent.SETUP and action == LLMv2Action.ADD_ENTITY:
        if payload.create_new:
            created = EntityRegistryService(db, interpretation.project_id).apply_setup(
                interpretation.extracted_entities or []
            )
        else:
            selected = _get_selected_worker(db, interpretation, payload)
            created = [selected] if selected is not None else []
        workers.extend(created)
        history = HistoryEntry(
            project_id=interpretation.project_id,
            input_text=interpretation.raw_input_text,
            change_type=HistoryChangeType.SETUP,
            delta=_history_delta(
                intent=intent.value,
                action=action.value,
                entities=[_entity_snapshot(entity) for entity in created],
            ),
            **semantic_history,
        )
        db.add(history)
        db.flush()
        history_entries.append(history)
        return NaturalInputResult(
            raw_entry_id=raw_entry.id,
            intent=interpretation.canonical_event_type,
            workers=workers,
            states=states,
            history_entries=history_entries,
            work_logs=work_logs,
            invoices=invoices,
            payments=payments,
        )

    if intent == LLMv2Intent.SET_ROLE and action == LLMv2Action.SET_ROLE:
        entities = interpretation.extracted_entities or []
        selected = _get_selected_worker(db, interpretation, payload)
        if selected is not None and entities:
            _apply_role_assignment(selected, entities[0])
            workers.append(selected)
        elif payload.create_new:
            workers.extend(
                EntityRegistryService(db, interpretation.project_id).apply_setup(
                    entities
                )
            )
        history = HistoryEntry(
            project_id=interpretation.project_id,
            input_text=interpretation.raw_input_text,
            change_type=HistoryChangeType.SETUP,
            delta=_history_delta(
                intent=intent.value,
                action=action.value,
                entities=[_entity_snapshot(entity) for entity in workers],
            ),
            **semantic_history,
        )
        db.add(history)
        db.flush()
        history_entries.append(history)
        return NaturalInputResult(
            raw_entry_id=raw_entry.id,
            intent=interpretation.canonical_event_type,
            workers=workers,
            states=states,
            history_entries=history_entries,
            work_logs=work_logs,
            invoices=invoices,
            payments=payments,
        )

    if intent == LLMv2Intent.SETUP and action == LLMv2Action.UPDATE_ENTITY:
        registry = EntityRegistryService(db, interpretation.project_id)
        entities = interpretation.extracted_entities or []
        selected = _get_selected_worker(db, interpretation, payload)
        updated = (
            registry.update_entity_by_id(selected.id, entities[0])
            if selected is not None and entities and _has_entity_field_updates(entities)
            else []
        )
        workers.extend(updated)
        history = HistoryEntry(
            project_id=interpretation.project_id,
            input_text=interpretation.raw_input_text,
            change_type=HistoryChangeType.ENTITY_UPDATE,
            delta=_history_delta(
                intent=intent.value,
                action=action.value,
                entities=[_entity_snapshot(entity) for entity in updated],
            ),
            **semantic_history,
        )
        db.add(history)
        db.flush()
        history_entries.append(history)
        return NaturalInputResult(
            raw_entry_id=raw_entry.id,
            intent=interpretation.canonical_event_type,
            workers=workers,
            states=states,
            history_entries=history_entries,
            work_logs=work_logs,
            invoices=invoices,
            payments=payments,
        )

    entity_name = _pending_entity_name(interpretation)
    if entity_name is None and intent != LLMv2Intent.NOTE:
        entity_name = si.entities[0].name if si.entities else None

    pending_worker = _get_selected_worker(
        db, interpretation, payload
    ) or _pending_worker(db, interpretation)
    project_role = si.entities[0].project_role if si.entities else None
    role = _llm_v2_role_to_state_role(project_role, pending_worker)

    if intent == LLMv2Intent.NOTE or (entity_name is None and not si.entities):
        history = HistoryEntry(
            project_id=interpretation.project_id,
            input_text=interpretation.raw_input_text,
            change_type=HistoryChangeType.NOTE,
            delta=_history_delta(intent=intent.value, action=action.value),
            **semantic_history,
        )
        db.add(history)
        db.flush()
        history_entries.append(history)
        return NaturalInputResult(
            raw_entry_id=raw_entry.id,
            intent=interpretation.canonical_event_type,
            workers=workers,
            states=states,
            history_entries=history_entries,
            work_logs=work_logs,
            invoices=invoices,
            payments=payments,
        )

    if (
        pending_worker is None
        and entity_name
        and payload.create_new
        and _pending_allows_new_llm_v2_vendor(interpretation, si)
    ):
        pending_worker = _find_or_create_worker(
            db,
            interpretation.project_id,
            entity_name,
            _llm_v2_role_to_worker_type(project_role),
        )
    if pending_worker is not None:
        state = _find_or_create_worker_state(
            db,
            interpretation.project_id,
            pending_worker.name,
            role,
        )
        if state.worker_id != pending_worker.id:
            state.worker_id = pending_worker.id
            state.role = role
        workers.append(pending_worker)
    elif entity_name:
        state = _find_or_create_worker_state(
            db, interpretation.project_id, entity_name, role
        )
        worker = db.get(Worker, state.worker_id)
        if worker is not None:
            workers.append(worker)
    else:
        state = None
    if state is not None:
        states.append(state)

    if intent == LLMv2Intent.WORK and state is not None:
        quantity = si.work.quantity
        if quantity is None:
            quantity = interpretation.extracted_quantity or Decimal("1")
        quantity = Decimal(str(quantity))
        if state.role == WorkerStateRole.DAILY:
            state.total_days_worked += quantity
            worker = db.get(Worker, state.worker_id)
            accrued_wage = _daily_worker_wage(worker, quantity)
            if accrued_wage is not None:
                state.financial_balance += accrued_wage
            delta = _history_delta(
                intent=intent.value,
                action=action.value,
                days=str(quantity),
                accrued_wage=str(accrued_wage) if accrued_wage is not None else None,
                daily_rate=(
                    str(worker.daily_rate)
                    if worker is not None and worker.daily_rate is not None
                    else None
                ),
                balance=str(state.financial_balance),
            )
        else:
            state.total_quantity += quantity
            state.unit = (
                state.unit
                or (si.work.unit.value if si.work.unit else None)
                or _unit_from_text(interpretation.raw_input_text, state.role)
            )
            delta = _history_delta(
                intent=intent.value,
                action=action.value,
                quantity=str(quantity),
                unit=state.unit,
            )
        work_log = WorkLog(
            project_id=interpretation.project_id,
            worker_id=state.worker_id,
            task_name=(
                si.work.description
                or interpretation.description
                or interpretation.raw_input_text
            ),
            unit=(
                WorkUnit.DAY if state.role == WorkerStateRole.DAILY else WorkUnit.CUSTOM
            ),
            quantity=quantity,
            rate_per_unit=(
                db.get(Worker, state.worker_id).daily_rate
                if state.role == WorkerStateRole.DAILY
                and db.get(Worker, state.worker_id) is not None
                else None
            ),
            total_amount=_daily_worker_wage(db.get(Worker, state.worker_id), quantity),
            description=si.work.description,
        )
        db.add(work_log)
        db.flush()
        work_logs.append(work_log)
        history_entries.append(
            _add_history(
                db,
                interpretation.project_id,
                state,
                interpretation.raw_input_text,
                HistoryChangeType.WORK,
                delta,
                semantic_history,
            )
        )

    elif (
        intent == LLMv2Intent.FINANCIAL
        and confirmed_action == LLMv2Action.DEBT_CREATED
        and state is not None
    ):
        amount = interpretation.extracted_amount
        if amount is None:
            amount = si.financial.amount
        if amount is not None and state is not None:
            amount = Decimal(str(amount))
            state.role = WorkerStateRole.VENDOR
            state.financial_balance += amount
            invoice = Invoice(
                project_id=interpretation.project_id,
                vendor_id=state.worker_id,
                total_amount=amount,
                description=interpretation.description or si.reasoning_summary,
                status=InvoiceStatus.OPEN,
            )
            db.add(invoice)
            db.flush()
            invoices.append(invoice)
        history_entries.append(
            _add_history(
                db,
                interpretation.project_id,
                state,
                interpretation.raw_input_text,
                HistoryChangeType.INVOICE,
                _history_delta(
                    intent=intent.value,
                    action=confirmed_action.value,
                    amount=str(amount) if amount else None,
                    balance=str(state.financial_balance) if state else None,
                ),
                semantic_history,
            )
        )

    elif intent == LLMv2Intent.FINANCIAL and state is not None:
        amount = interpretation.extracted_amount
        if amount is None:
            amount = si.financial.amount
        direction = _confirmed_payment_direction(interpretation, si, confirmed_action)
        if amount is not None:
            amount = Decimal(str(amount))
            payment_type = _confirmed_payment_type(interpretation, si, confirmed_action)

            if direction == FinancialDirection.INCOMING:
                state.role = WorkerStateRole.CLIENT
                state.financial_balance += amount
            else:
                if (
                    state.role != WorkerStateRole.VENDOR
                    and state.role != WorkerStateRole.CLIENT
                ):
                    state.financial_balance -= amount

            payment = Payment(
                project_id=interpretation.project_id,
                entity_id=state.worker_id,
                amount=amount,
                related_invoice_id=None,
                type=payment_type,
                due_date=interpretation.due_date or si.financial.due_date_text,
                direction=direction,
            )
            db.add(payment)
            db.flush()
            payments.append(payment)
        history_entries.append(
            _add_history(
                db,
                interpretation.project_id,
                state,
                interpretation.raw_input_text,
                HistoryChangeType.PAYMENT,
                _history_delta(
                    intent=intent.value,
                    action=confirmed_action.value,
                    amount=str(amount) if amount else None,
                    balance=str(state.financial_balance) if state else None,
                    payment_method=payment_type.value,
                    financial_direction=direction.value,
                ),
                semantic_history,
            )
        )

    elif state is not None:
        history_entries.append(
            _add_history(
                db,
                interpretation.project_id,
                state,
                interpretation.raw_input_text,
                HistoryChangeType.NOTE,
                _history_delta(intent=intent.value, action=action.value),
                semantic_history,
            )
        )

    if state is not None:
        db.flush()
        for item in [
            *workers,
            *states,
            *history_entries,
            *work_logs,
            *invoices,
            *payments,
        ]:
            db.refresh(item)

    return NaturalInputResult(
        raw_entry_id=raw_entry.id,
        intent=interpretation.canonical_event_type,
        workers=workers,
        states=states,
        history_entries=history_entries,
        work_logs=work_logs,
        invoices=invoices,
        payments=payments,
    )


def _confirmed_llm_v2_action(
    interpretation: PendingInterpretation,
    fallback: Any,
) -> Any:
    from app.schemas.llm_v2 import LLMv2Action

    semantic_action = interpretation.semantic_action
    if semantic_action == "PAYMENT":
        if interpretation.financial_direction == FinancialDirection.DEBT:
            return LLMv2Action.DEBT_CREATED
        if (
            interpretation.financial_direction == FinancialDirection.DEFERRED
            or interpretation.payment_method == PaymentType.CHECK
        ):
            return LLMv2Action.CHECK_PAYMENT
        if interpretation.financial_direction == FinancialDirection.INCOMING:
            return LLMv2Action.PAYMENT_IN
        if interpretation.financial_direction == FinancialDirection.OUTGOING:
            return LLMv2Action.PAYMENT_OUT
        return fallback
    mapping = {
        "PURCHASE_PAID": LLMv2Action.PURCHASE_PAID,
        "DEBT_CREATED": LLMv2Action.DEBT_CREATED,
        "INVOICE": LLMv2Action.DEBT_CREATED,
        "CHECK_PAYMENT": LLMv2Action.CHECK_PAYMENT,
        "DEFERRED_PAYMENT": LLMv2Action.CHECK_PAYMENT,
    }
    return mapping.get(semantic_action, fallback)


def _confirmed_payment_direction(
    interpretation: PendingInterpretation,
    si: Any,
    action: Any,
) -> FinancialDirection:
    from app.schemas.llm_v2 import LLMv2Action

    if interpretation.financial_direction in {
        FinancialDirection.INCOMING,
        FinancialDirection.OUTGOING,
        FinancialDirection.DEFERRED,
    }:
        return interpretation.financial_direction

    if action == LLMv2Action.PAYMENT_IN:
        return FinancialDirection.INCOMING

    fd = si.financial.direction
    fd_val = fd.value if hasattr(fd, "value") else (fd or "OUT")
    if fd_val == "IN":
        return FinancialDirection.INCOMING
    return FinancialDirection.OUTGOING


def _confirmed_payment_type(
    interpretation: PendingInterpretation,
    si: Any,
    action: Any,
) -> PaymentType:
    from app.schemas.llm_v2 import LLMv2Action

    if interpretation.payment_method:
        return PaymentType(interpretation.payment_method)
    if action == LLMv2Action.CHECK_PAYMENT:
        return PaymentType.CHECK
    if si.financial.payment_method:
        pm = si.financial.payment_method
        pm_val = pm.value if hasattr(pm, "value") else pm
        if pm_val in {
            PaymentType.CASH.value,
            PaymentType.BANK_TRANSFER.value,
            PaymentType.CHECK.value,
            PaymentType.OTHER.value,
        }:
            return PaymentType(pm_val)
    if action == LLMv2Action.PURCHASE_PAID:
        return PaymentType.CASH
    return PaymentType.BANK_TRANSFER


def _llm_v2_role_to_state_role(
    project_role: Any,
    worker: Worker | None = None,
) -> WorkerStateRole:
    if worker is not None:
        if worker.type.value == "CLIENT":
            return WorkerStateRole.CLIENT
        if worker.type.value in ("VENDOR",):
            return WorkerStateRole.VENDOR
        if worker.type.value in ("SKILLED_WORKER",):
            return WorkerStateRole.SKILLED
        return WorkerStateRole.DAILY
    if isinstance(project_role, str):
        role_val = project_role
    elif hasattr(project_role, "value"):
        role_val = project_role.value
    else:
        role_val = "OTHER"
    mapping = {
        "CLIENT": WorkerStateRole.CLIENT,
        "DAILY_WORKER": WorkerStateRole.DAILY,
        "SKILLED_WORKER": WorkerStateRole.SKILLED,
        "VENDOR": WorkerStateRole.VENDOR,
        "OTHER": WorkerStateRole.DAILY,
    }
    return mapping.get(role_val, WorkerStateRole.DAILY)


def _llm_v2_role_to_worker_type(project_role: Any) -> WorkerType:
    if isinstance(project_role, str):
        role_val = project_role
    elif hasattr(project_role, "value"):
        role_val = project_role.value
    else:
        role_val = "OTHER"
    mapping = {
        "CLIENT": WorkerType.CLIENT,
        "DAILY_WORKER": WorkerType.DAILY_WORKER,
        "SKILLED_WORKER": WorkerType.SKILLED_WORKER,
        "VENDOR": WorkerType.VENDOR,
        "OTHER": WorkerType.OTHER,
    }
    return mapping.get(role_val, WorkerType.OTHER)


def _execute_legacy_interpretation(
    db: DbSession,
    interpretation: PendingInterpretation,
    payload: PendingInterpretationConfirm,
) -> NaturalInputResult:
    """Deprecated — legacy writer for Payment/Invoice/WorkerState.

    This path writes financial records directly (Payment, Invoice, WorkerState
    and WorkLog financial_balance updates) WITHOUT going through ExecutionEngine.
    It is retained only for:
      - shadow/fallback execution when ExecutionEngine is primary (runs inside a
        savepoint that is always rolled back — see `_run_legacy_execution_shadow`)
      - primary execution when the YARA_USE_EXECUTION_ENGINE feature flag is
        explicitly set to 0/false (not recommended)

    Must not be used in the default production path.  New financial writes
    should only be added to ExecutionEngine.
    """
    raw_entry = RawEntry(
        project_id=interpretation.project_id,
        text=interpretation.raw_input_text,
        status=RawEntryStatus.PROCESSED,
    )
    db.add(raw_entry)
    db.flush()
    semantic_history = _semantic_history_fields_from_pending(interpretation)
    workers: list[Worker] = []
    states: list[WorkerState] = []
    history_entries: list[HistoryEntry] = []
    work_logs: list[WorkLog] = []
    invoices: list[Invoice] = []
    payments: list[Payment] = []
    event_type = interpretation.canonical_event_type
    action = interpretation.semantic_action
    entity_name = _pending_entity_name(interpretation)
    pending_worker = _pending_worker(db, interpretation)

    if event_type == CanonicalEventType.SETUP.value and action == "SETUP":
        if payload.create_new:
            created = EntityRegistryService(db, interpretation.project_id).apply_setup(
                interpretation.extracted_entities or []
            )
        else:
            selected = _get_selected_worker(db, interpretation, payload)
            created = [selected] if selected is not None else []
        workers.extend(created)
        history = HistoryEntry(
            project_id=interpretation.project_id,
            input_text=interpretation.raw_input_text,
            change_type=HistoryChangeType.SETUP,
            delta=_history_delta(
                canonical_event_type=event_type,
                semantic_action=action,
                entities=[_entity_snapshot(entity) for entity in created],
            ),
            **semantic_history,
        )
        db.add(history)
        db.flush()
        history_entries.append(history)
        return NaturalInputResult(
            raw_entry_id=raw_entry.id,
            intent=event_type,
            workers=workers,
            states=states,
            history_entries=history_entries,
            work_logs=work_logs,
            invoices=invoices,
            payments=payments,
        )

    if event_type == CanonicalEventType.SETUP.value:
        registry = EntityRegistryService(db, interpretation.project_id)
        entities = interpretation.extracted_entities or []
        selected = _get_selected_worker(db, interpretation, payload)
        if selected is not None and entities and _has_entity_field_updates(entities):
            updated = registry.update_entity_by_id(selected.id, entities[0])
        elif entities and entities[0].get("create_new") and _has_entity_field_updates(entities):
            created = registry.apply_setup(entities)
            if created:
                updated = registry.update_entity_by_id(created[0].id, entities[0])
            else:
                updated = []
        else:
            updated = []
        workers.extend(updated)
        history = HistoryEntry(
            project_id=interpretation.project_id,
            input_text=interpretation.raw_input_text,
            change_type=HistoryChangeType.ENTITY_UPDATE,
            delta=_history_delta(
                canonical_event_type=event_type,
                semantic_action=action,
                entities=[_entity_snapshot(entity) for entity in updated],
            ),
            **semantic_history,
        )
        db.add(history)
        db.flush()
        history_entries.append(history)
        return NaturalInputResult(
            raw_entry_id=raw_entry.id,
            intent=event_type,
            workers=workers,
            states=states,
            history_entries=history_entries,
            work_logs=work_logs,
            invoices=invoices,
            payments=payments,
        )

    if entity_name is None:
        history = HistoryEntry(
            project_id=interpretation.project_id,
            input_text=interpretation.raw_input_text,
            change_type=HistoryChangeType.NOTE,
            delta=_history_delta(
                canonical_event_type=event_type, semantic_action=action
            ),
            **semantic_history,
        )
        db.add(history)
        db.flush()
        history_entries.append(history)
        return NaturalInputResult(
            raw_entry_id=raw_entry.id,
            intent=event_type,
            workers=workers,
            states=states,
            history_entries=history_entries,
            work_logs=work_logs,
            invoices=invoices,
            payments=payments,
        )

    if event_type == CanonicalEventType.FINANCIAL.value and pending_worker is None:
        if not (
            _pending_allows_new_entity(interpretation)
            or _pending_allows_new_legacy_vendor(interpretation)
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Financial interpretation requires a resolved entity",
            )
        pending_worker = _find_or_create_worker(
            db,
            interpretation.project_id,
            entity_name,
            _state_role_to_worker_type(_pending_role(interpretation)),
        )

    role = _pending_role(interpretation, pending_worker)
    if pending_worker is not None:
        state = _find_or_create_worker_state(
            db,
            interpretation.project_id,
            pending_worker.name,
            role,
        )
        if state.worker_id != pending_worker.id:
            state.worker_id = pending_worker.id
            state.role = role
        workers.append(pending_worker)
    else:
        state = _find_or_create_worker_state(
            db, interpretation.project_id, entity_name, role
        )
        worker = db.get(Worker, state.worker_id)
        if worker is not None:
            workers.append(worker)
    states.append(state)

    if event_type == CanonicalEventType.WORK.value:
        quantity = interpretation.extracted_quantity or Decimal("1")
        if state.role == WorkerStateRole.DAILY:
            state.total_days_worked += quantity
            worker = db.get(Worker, state.worker_id)
            accrued_wage = _daily_worker_wage(worker, quantity)
            if accrued_wage is not None:
                state.financial_balance += accrued_wage
            delta = _history_delta(
                canonical_event_type=event_type,
                semantic_action=action,
                days=quantity,
                accrued_wage=accrued_wage,
                daily_rate=worker.daily_rate if worker is not None else None,
                balance=state.financial_balance,
            )
        else:
            state.total_quantity += quantity
            state.unit = state.unit or _unit_from_text(
                interpretation.raw_input_text, state.role
            )
            delta = _history_delta(
                canonical_event_type=event_type,
                semantic_action=action,
                quantity=quantity,
                unit=state.unit,
            )
        work_log = WorkLog(
            project_id=interpretation.project_id,
            worker_id=state.worker_id,
            task_name=interpretation.description or interpretation.raw_input_text,
            unit=(
                WorkUnit.DAY if state.role == WorkerStateRole.DAILY else WorkUnit.CUSTOM
            ),
            quantity=quantity,
            rate_per_unit=(
                db.get(Worker, state.worker_id).daily_rate
                if state.role == WorkerStateRole.DAILY
                and db.get(Worker, state.worker_id) is not None
                else None
            ),
            total_amount=_daily_worker_wage(db.get(Worker, state.worker_id), quantity),
            description=interpretation.description,
        )
        db.add(work_log)
        db.flush()
        work_logs.append(work_log)
        history_entries.append(
            _add_history(
                db,
                interpretation.project_id,
                state,
                interpretation.raw_input_text,
                HistoryChangeType.WORK,
                delta,
                semantic_history,
            )
        )
    elif (
        event_type == CanonicalEventType.FINANCIAL.value
        and interpretation.financial_direction == FinancialDirection.DEBT
    ):
        amount = interpretation.extracted_amount
        if amount is not None:
            state.role = WorkerStateRole.VENDOR
            state.financial_balance += amount
            invoice = Invoice(
                project_id=interpretation.project_id,
                vendor_id=state.worker_id,
                total_amount=amount,
                description=interpretation.description,
                status=InvoiceStatus.OPEN,
            )
            db.add(invoice)
            db.flush()
            invoices.append(invoice)
        history_entries.append(
            _add_history(
                db,
                interpretation.project_id,
                state,
                interpretation.raw_input_text,
                HistoryChangeType.INVOICE,
                _history_delta(
                    canonical_event_type=event_type,
                    semantic_action=action,
                    amount=amount,
                    balance=state.financial_balance,
                ),
                semantic_history,
            )
        )
    elif event_type == CanonicalEventType.FINANCIAL.value:
        amount = interpretation.extracted_amount
        if amount is not None:
            payment_type = PaymentType(
                interpretation.payment_method or PaymentType.BANK_TRANSFER.value
            )
            direction = (
                interpretation.financial_direction or FinancialDirection.OUTGOING
            )
            if direction == FinancialDirection.INCOMING:
                state.role = WorkerStateRole.CLIENT
                state.financial_balance += amount
            elif state.role != WorkerStateRole.VENDOR:
                state.financial_balance -= amount
            payment = Payment(
                project_id=interpretation.project_id,
                entity_id=state.worker_id,
                amount=amount,
                related_invoice_id=None,
                type=payment_type,
                due_date=interpretation.due_date,
                direction=direction,
            )
            db.add(payment)
            db.flush()
            payments.append(payment)
        history_entries.append(
            _add_history(
                db,
                interpretation.project_id,
                state,
                interpretation.raw_input_text,
                HistoryChangeType.PAYMENT,
                _history_delta(
                    canonical_event_type=event_type,
                    semantic_action=action,
                    amount=amount,
                    balance=state.financial_balance,
                    payment_method=interpretation.payment_method,
                    due_date=interpretation.due_date,
                    financial_direction=(
                        interpretation.financial_direction.value
                        if interpretation.financial_direction is not None
                        else None
                    ),
                ),
                semantic_history,
            )
        )
    else:
        history_entries.append(
            _add_history(
                db,
                interpretation.project_id,
                state,
                interpretation.raw_input_text,
                HistoryChangeType.NOTE,
                _history_delta(canonical_event_type=event_type, semantic_action=action),
                semantic_history,
            )
        )

    db.flush()
    for item in [*workers, *states, *history_entries, *work_logs, *invoices, *payments]:
        db.refresh(item)

    return NaturalInputResult(
        raw_entry_id=raw_entry.id,
        intent=event_type,
        workers=workers,
        states=states,
        history_entries=history_entries,
        work_logs=work_logs,
        invoices=invoices,
        payments=payments,
    )


def _pending_entity_name(interpretation: PendingInterpretation) -> str | None:
    entities = interpretation.extracted_entities or []
    if entities and isinstance(entities[0].get("name"), str):
        return entities[0]["name"].strip() or None
    return None


def _pending_worker(
    db: DbSession, interpretation: PendingInterpretation
) -> Worker | None:
    if interpretation.suggested_entity_id is None:
        return None
    worker = db.get(Worker, interpretation.suggested_entity_id)
    if worker is None or worker.project_id != interpretation.project_id:
        return None
    return worker


def _pending_allows_new_entity(interpretation: PendingInterpretation) -> bool:
    entities = interpretation.extracted_entities or []
    return bool(entities and entities[0].get("create_new") is True)


def _pending_requires_entity_confirmation(
    interpretation: PendingInterpretation,
) -> bool:
    entities = interpretation.extracted_entities or []
    return bool(entities and entities[0].get("requires_confirmation") is True)


def _pending_allows_new_llm_v2_vendor(
    interpretation: PendingInterpretation,
    si: Any,
) -> bool:
    entities = interpretation.extracted_entities or []
    entity = entities[0] if entities else {}
    project_role = entity.get("project_role") or entity.get("type")
    if hasattr(project_role, "value"):
        project_role = project_role.value
    if project_role != "VENDOR":
        return False
    name = entity.get("name")
    if not isinstance(name, str) or name.strip() in {
        "نامشخص",
        "طرف حساب نامشخص",
        "unknown",
        "ناشناس",
    }:
        return False
    if interpretation.suggested_entity_id is not None:
        return False
    if bool(getattr(si, "ambiguity", False)):
        return False
    confidence = interpretation.confidence
    if confidence is None:
        confidence = getattr(si, "confidence", 0)
    return float(confidence or 0) >= 0.85


def _pending_allows_new_legacy_vendor(interpretation: PendingInterpretation) -> bool:
    if interpretation.structured_interpretation is not None:
        return False
    if interpretation.canonical_event_type != CanonicalEventType.FINANCIAL.value:
        return False
    if interpretation.suggested_entity_id is not None:
        return False
    if not _pending_entity_is_vendor(interpretation):
        return False
    if _pending_entity_name_is_unknown(interpretation):
        return False
    if interpretation.confidence is None:
        return False
    return float(interpretation.confidence) >= 0.85


def _pending_entity_is_vendor(interpretation: PendingInterpretation) -> bool:
    entities = interpretation.extracted_entities or []
    entity = entities[0] if entities else {}
    role = entity.get("project_role") or entity.get("type") or entity.get("role_guess")
    if hasattr(role, "value"):
        role = role.value
    return role == "VENDOR"


def _pending_entity_name_is_unknown(interpretation: PendingInterpretation) -> bool:
    name = _pending_entity_name(interpretation)
    return name is None or name in {"نامشخص", "طرف حساب نامشخص", "unknown", "ناشناس"}


def _pending_role(
    interpretation: PendingInterpretation,
    worker: Worker | None = None,
) -> WorkerStateRole:
    if worker is not None:
        if worker.type == WorkerType.CLIENT:
            return WorkerStateRole.CLIENT
        if worker.type == WorkerType.VENDOR:
            return WorkerStateRole.VENDOR
        if worker.type == WorkerType.SKILLED_WORKER:
            return WorkerStateRole.SKILLED
        return WorkerStateRole.DAILY
    if interpretation.canonical_event_type == CanonicalEventType.FINANCIAL.value:
        if interpretation.financial_direction == FinancialDirection.INCOMING:
            return WorkerStateRole.CLIENT
        return WorkerStateRole.VENDOR
    return _role_to_state_role(
        None, interpretation.raw_input_text, interpretation.semantic_action
    )


def _has_entity_field_updates(entities: list[dict]) -> bool:
    for entity in entities:
        updates = (
            entity.get("field_updates")
            if isinstance(entity.get("field_updates"), dict)
            else entity
        )
        if any(
            updates.get(key)
            for key in ["phone", "account_number", "daily_rate", "notes"]
        ):
            return True
    return False


def _apply_role_assignment(worker: Worker, entity: dict[str, Any]) -> None:
    role_value = entity.get("project_role") or entity.get("type")
    worker_type = _llm_v2_role_to_worker_type(role_value)
    if worker_type != WorkerType.OTHER:
        worker.type = worker_type
    role_detail = entity.get("role_detail")
    if isinstance(role_detail, str) and role_detail.strip():
        worker.role_detail = role_detail.strip()


def _graph_intent(graph: dict[str, Any]) -> str:
    intent = graph.get("intent")
    if isinstance(intent, str) and intent in {
        "SETUP",
        "ENTITY_UPDATE",
        "WORK",
        "PAYMENT",
        "INVOICE",
        "NOTE",
    }:
        return intent
    events = graph.get("events", [])
    if isinstance(events, list) and events and isinstance(events[0], dict):
        event_type = events[0].get("type")
        if event_type == "WORK_LOG":
            return "WORK"
        if event_type in {"PAYMENT", "INVOICE"}:
            return str(event_type)
    return "NOTE"


def _execution_intent(
    graph: dict[str, Any],
    canonical_type: CanonicalEventType,
    semantic_action: str,
) -> str:
    if canonical_type == CanonicalEventType.SETUP:
        return "ENTITY_UPDATE" if semantic_action == "ENTITY_UPDATE" else "SETUP"
    if canonical_type == CanonicalEventType.FINANCIAL:
        return (
            "INVOICE" if semantic_action in {"INVOICE", "DEBT_CREATED"} else "PAYMENT"
        )
    if canonical_type == CanonicalEventType.WORK:
        return "WORK"
    return "NOTE"


def _entity_snapshot(entity: Worker) -> dict[str, Any]:
    return {
        "id": entity.id,
        "name": entity.name,
        "type": entity.type.value,
        "phone": entity.phone,
        "account_number": entity.account_number,
        "role_detail": entity.role_detail,
        "daily_rate": str(entity.daily_rate) if entity.daily_rate is not None else None,
        "notes": entity.notes,
    }


def _graph_entity_name(graph: dict[str, Any]) -> str | None:
    entity = graph.get("entity")
    if isinstance(entity, str) and entity.strip():
        return entity.strip()
    entities = graph.get("entities", [])
    if isinstance(entities, list) and entities and isinstance(entities[0], dict):
        name = entities[0].get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _graph_role_guess(graph: dict[str, Any]) -> str | None:
    role = graph.get("role_guess")
    if isinstance(role, str):
        return role
    entities = graph.get("entities", [])
    if isinstance(entities, list) and entities and isinstance(entities[0], dict):
        role = entities[0].get("role_guess")
        if isinstance(role, str):
            return role
    return None


def _graph_setup_entities(graph: dict[str, Any]) -> list[dict[str, Any]]:
    entities = graph.get("entities", [])
    setup_entities: list[dict[str, Any]] = []
    if isinstance(entities, list):
        for entity in entities:
            if not isinstance(entity, dict) or not isinstance(entity.get("name"), str):
                continue
            entity_type = entity.get("type") or entity.get("role_guess") or "OTHER"
            field_updates = entity.get("field_updates")
            updates = field_updates if isinstance(field_updates, dict) else entity
            setup_entities.append(
                {
                    "type": entity_type,
                    "project_role": entity_type,
                    "name": entity.get("name"),
                    "phone": updates.get("phone"),
                    "account_number": updates.get("account_number"),
                    "role_detail": updates.get("role_detail"),
                    "field_updates": updates,
                }
            )

    entity_name = graph.get("entity")
    if not setup_entities and isinstance(entity_name, str) and entity_name.strip():
        setup_entities.append(
            {
                "type": graph.get("role_guess") or "OTHER",
                "project_role": graph.get("role_guess") or "OTHER",
                "name": entity_name.strip(),
                "phone": graph.get("phone"),
                "account_number": graph.get("account_number"),
                "role_detail": graph.get("role_detail"),
            }
        )
    return setup_entities


def _graph_quantity(graph: dict[str, Any]) -> Decimal | None:
    quantity = graph.get("quantity_text")
    if isinstance(quantity, str):
        return _parse_quantity(quantity)
    events = graph.get("events", [])
    if isinstance(events, list) and events and isinstance(events[0], dict):
        return _parse_quantity(events[0].get("quantity_text"))
    return None


def _graph_amount(graph: dict[str, Any], input_text: str) -> Decimal | None:
    amount_text = graph.get("amount_text")
    if isinstance(amount_text, str):
        amount = _parse_money_decimal(amount_text)
        if amount is not None:
            return amount
    events = graph.get("events", [])
    if isinstance(events, list) and events and isinstance(events[0], dict):
        amount = _parse_money_decimal(events[0].get("amount_text"))
        if amount is not None:
            return amount
    if _has_money_unit(input_text):
        return _parse_money_decimal(input_text)
    return None


def _has_money_unit(text: str) -> bool:
    normalized = normalize_text(text)
    return any(unit in normalized for unit in ["تومان", "میلیون", "میلیارد", "هزار"])


def _extract_due_date(text: str) -> str | None:
    normalized = normalize_text(text)
    absolute_match = re.search(r"\d{1,2}\s+[آ-ی]+\s+\d{4}", normalized)
    if absolute_match is not None:
        return absolute_match.group()
    relative_match = re.search(r"\d{1,2}\s+ماه\s+دیگه", normalized)
    if relative_match is not None:
        return relative_match.group()
    return None


def _add_history(
    db: DbSession,
    project_id: int,
    state: WorkerState,
    input_text: str,
    change_type: HistoryChangeType,
    delta: dict[str, str | int | float | None],
    semantic_history: dict[str, Any] | None = None,
) -> HistoryEntry:
    history = HistoryEntry(
        project_id=project_id,
        worker_state_id=state.id,
        input_text=input_text,
        change_type=change_type,
        delta=delta,
        **(semantic_history or {}),
    )
    db.add(history)
    db.flush()
    return history


def _resolve_event_entity(
    db: DbSession,
    project_id: int,
    raw_event: dict[str, Any],
    graph: dict[str, Any],
    entity_by_name: dict[str, Worker],
) -> Worker | None:
    entity_name = raw_event.get("entity_name")
    if isinstance(entity_name, str) and entity_name.strip():
        existing = entity_by_name.get(entity_name.strip())
        if existing is not None:
            return existing
        worker = _find_or_create_worker(
            db,
            project_id,
            entity_name,
            _worker_type_for_entity(
                entity_name,
                None,
                (
                    raw_event.get("type")
                    if isinstance(raw_event.get("type"), str)
                    else None
                ),
            ),
        )
        entity_by_name[worker.name] = worker
        return worker

    for worker in entity_by_name.values():
        return worker

    entities = graph.get("entities", [])
    if isinstance(entities, list) and entities:
        first = entities[0]
        if isinstance(first, dict) and isinstance(first.get("name"), str):
            worker = _find_or_create_worker(
                db,
                project_id,
                first["name"],
                _worker_type_for_entity(
                    first["name"],
                    (
                        first.get("role_guess")
                        if isinstance(first.get("role_guess"), str)
                        else None
                    ),
                    (
                        raw_event.get("type")
                        if isinstance(raw_event.get("type"), str)
                        else None
                    ),
                ),
            )
            entity_by_name[worker.name] = worker
            return worker
    return None


def _event_description(raw_event: dict[str, Any]) -> str:
    description = raw_event.get("description")
    if isinstance(description, str) and description.strip():
        return description
    return "Natural input event"


def _parse_money_decimal(value: Any) -> Decimal | None:
    if not isinstance(value, str):
        return None
    amount = parse_persian_money(value)
    return Decimal(amount) if amount is not None else None


def _worker_read(worker: Worker) -> WorkerRead:
    return WorkerRead.model_validate(worker).model_copy(
        update={"type": _display_worker_type(worker)}
    )


def _worker_state_read(
    state: WorkerState, worker: Worker | None = None
) -> WorkerStateRead:
    return WorkerStateRead.model_validate(state).model_copy(
        update={"role": _display_worker_state_role(state, worker)}
    )


@router.post(
    "/projects/{project_id}/workers",
    response_model=WorkerRead,
    status_code=status.HTTP_201_CREATED,
)
def create_worker(project_id: int, payload: WorkerCreate, db: DbSession) -> Worker:
    _get_project(db, project_id)
    worker = Worker(project_id=project_id, **payload.model_dump())
    db.add(worker)
    db.commit()
    db.refresh(worker)
    return worker


@router.patch("/workers/{worker_id}", response_model=WorkerRead)
def update_worker(worker_id: int, payload: WorkerUpdate, db: DbSession) -> WorkerRead:
    worker = db.get(Worker, worker_id)
    if worker is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found"
        )
    values = payload.model_dump(exclude_unset=True)
    target_type = values.get("type") or worker.type
    if target_type != WorkerType.DAILY_WORKER:
        if "daily_rate" in values and values["daily_rate"] is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="daily_rate is only valid for daily workers",
            )
        if payload.type is not None:
            values["daily_rate"] = None
    for field, value in values.items():
        setattr(worker, field, value)
    db.commit()
    db.refresh(worker)
    return _worker_read(worker)


@router.get("/projects/{project_id}/workers", response_model=list[WorkerRead])
def list_workers(project_id: int, db: DbSession) -> list[WorkerRead]:
    _get_project(db, project_id)
    workers = list(
        db.scalars(
            select(Worker)
            .where(Worker.project_id == project_id)
            .order_by(Worker.created_at.desc(), Worker.id.desc())
        )
    )
    return [_worker_read(worker) for worker in workers]


@router.get(
    "/projects/{project_id}/worker-states", response_model=list[WorkerStateRead]
)
def list_worker_states(project_id: int, db: DbSession) -> list[WorkerStateRead]:
    _get_project(db, project_id)
    states = list(
        db.scalars(
            select(WorkerState)
            .where(WorkerState.project_id == project_id)
            .order_by(WorkerState.updated_at.desc(), WorkerState.id.desc())
        )
    )
    worker_ids = {state.worker_id for state in states}
    workers_by_id = (
        {
            worker.id: worker
            for worker in db.scalars(select(Worker).where(Worker.id.in_(worker_ids)))
        }
        if worker_ids
        else {}
    )
    return [
        _worker_state_read(state, workers_by_id.get(state.worker_id))
        for state in states
    ]


@router.get("/projects/{project_id}/history", response_model=list[HistoryEntryRead])
def list_history_entries(project_id: int, db: DbSession) -> list[HistoryEntry]:
    _get_project(db, project_id)
    return list(
        db.scalars(
            select(HistoryEntry)
            .where(HistoryEntry.project_id == project_id)
            .order_by(HistoryEntry.created_at.desc(), HistoryEntry.id.desc())
        )
    )


@router.post(
    "/projects/{project_id}/work-logs",
    response_model=WorkLogRead,
    status_code=status.HTTP_201_CREATED,
)
def create_work_log(project_id: int, payload: WorkLogCreate, db: DbSession) -> WorkLog:
    # LEGACY_RISK: writes WorkLog.total_amount directly without ExecutionEngine.
    # Not part of the core Payment/Invoice ledger, but includes financially
    # relevant data (total_amount).  Not a migration priority.
    _get_project(db, project_id)
    _get_worker(db, project_id, payload.worker_id)
    work_log = WorkLog(
        project_id=project_id,
        total_amount=_work_log_total(payload.quantity, payload.rate_per_unit),
        **payload.model_dump(),
    )
    db.add(work_log)
    db.commit()
    db.refresh(work_log)
    return work_log


@router.get("/projects/{project_id}/work-logs", response_model=list[WorkLogRead])
def list_work_logs(project_id: int, db: DbSession) -> list[WorkLog]:
    _get_project(db, project_id)
    return list(
        db.scalars(
            select(WorkLog)
            .where(WorkLog.project_id == project_id)
            .order_by(WorkLog.created_at.desc(), WorkLog.id.desc())
        )
    )


@router.patch("/work-logs/{work_log_id}", response_model=WorkLogRead)
def update_work_log(work_log_id: int, payload: WorkLogUpdate, db: DbSession) -> WorkLog:
    # LEGACY_RISK: updates WorkLog.total_amount without ExecutionEngine.
    # Same note as create_work_log.
    work_log = _get_work_log(db, work_log_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(work_log, field, value)
    work_log.total_amount = _work_log_total(work_log.quantity, work_log.rate_per_unit)
    db.commit()
    db.refresh(work_log)
    return work_log


@router.post(
    "/projects/{project_id}/invoices",
    response_model=InvoiceRead,
    status_code=status.HTTP_201_CREATED,
)
def create_invoice(project_id: int, payload: InvoiceCreate, db: DbSession) -> Invoice:
    _get_project(db, project_id)
    vendor = _get_worker(db, project_id, payload.vendor_id)
    if vendor.type != WorkerType.VENDOR:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Worker is not a vendor",
        )
    state = _find_or_create_worker_state(
        db, project_id, vendor.name, WorkerStateRole.VENDOR
    )
    engine_result = ExecutionEngine().execute_confirmed_interpretation(
        ConfirmedFinancialInterpretation(
            project_id=project_id,
            semantic_action="DEBT_CREATED",
            amount=payload.total_amount,
            entity_id=payload.vendor_id,
            description=payload.description,
        ),
        db,
        state,
    )
    invoice_id = _result_ids(engine_result, "invoices")[0]
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Invoice creation failed",
        )
    _add_history(
        db,
        project_id,
        state,
        payload.description or "Manual invoice",
        HistoryChangeType.INVOICE,
        _history_delta(amount=payload.total_amount, balance=state.financial_balance),
    )
    db.commit()
    db.refresh(invoice)
    return invoice


@router.get("/projects/{project_id}/invoices", response_model=list[InvoiceRead])
def list_invoices(project_id: int, db: DbSession) -> list[Invoice]:
    _get_project(db, project_id)
    return list(
        db.scalars(
            select(Invoice)
            .where(Invoice.project_id == project_id)
            .order_by(Invoice.created_at.desc(), Invoice.id.desc())
        )
    )


@router.post(
    "/projects/{project_id}/payments",
    response_model=PaymentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_payment(project_id: int, payload: PaymentCreate, db: DbSession) -> Payment:
    _get_project(db, project_id)
    entity = _get_worker(db, project_id, payload.entity_id)
    invoice = None
    if payload.related_invoice_id is not None:
        invoice = _get_invoice(db, project_id, payload.related_invoice_id)
        if invoice.vendor_id != payload.entity_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Payment entity must match invoice vendor",
            )
    state_role = (
        WorkerStateRole.CLIENT
        if payload.direction == FinancialDirection.INCOMING
        or entity.type == WorkerType.CLIENT
        else (
            WorkerStateRole.VENDOR
            if entity.type == WorkerType.VENDOR
            else WorkerStateRole.DAILY
        )
    )
    state = _find_or_create_worker_state(db, project_id, entity.name, state_role)
    action = "CHECK_PAYMENT" if payload.type == PaymentType.CHECK else "PAYMENT"
    engine_result = ExecutionEngine().execute_confirmed_interpretation(
        ConfirmedFinancialInterpretation(
            project_id=project_id,
            semantic_action=action,
            amount=payload.amount,
            entity_id=payload.entity_id,
            financial_direction=payload.direction,
            payment_method=payload.type,
            due_date=payload.due_date,
            related_invoice_id=payload.related_invoice_id,
        ),
        db,
        state,
    )
    payment_id = _result_ids(engine_result, "payments")[0]
    payment = db.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Payment creation failed",
        )
    _add_history(
        db,
        project_id,
        state,
        "Manual payment",
        HistoryChangeType.PAYMENT,
        _history_delta(
            amount=payload.amount,
            balance=state.financial_balance,
            financial_direction=payload.direction.value,
        ),
    )
    if invoice is not None:
        _refresh_invoice_status(db, invoice)
    db.commit()
    db.refresh(payment)
    return payment


@router.get("/projects/{project_id}/payments", response_model=list[PaymentRead])
def list_payments(project_id: int, db: DbSession) -> list[Payment]:
    _get_project(db, project_id)
    return list(
        db.scalars(
            select(Payment)
            .where(Payment.project_id == project_id)
            .order_by(Payment.created_at.desc(), Payment.id.desc())
        )
    )


@router.get("/projects/{project_id}/operating-summary")
def get_operating_summary(project_id: int, db: DbSession) -> dict[str, Any]:
    _get_project(db, project_id)
    return project_operating_summary(db, project_id)


@router.post(
    "/projects/{project_id}/raw-entries/{raw_entry_id}/extracted-events",
    response_model=list[ExtractedEventRead],
    status_code=status.HTTP_201_CREATED,
)
def create_extracted_events(
    project_id: int,
    raw_entry_id: int,
    payload: list[ExtractedEventCreate],
    db: DbSession,
) -> list[ExtractedEvent]:
    raw_entry = _get_raw_entry(db, project_id, raw_entry_id)
    events = [
        ExtractedEvent(
            project_id=project_id,
            raw_entry_id=raw_entry_id,
            status=ExtractedEventStatus.PENDING,
            ai_confidence=(
                float(event.confidence) if event.confidence is not None else None
            ),
            **event.model_dump(),
        )
        for event in payload
    ]
    raw_entry.status = RawEntryStatus.PROCESSED
    db.add_all(events)
    db.commit()
    for event in events:
        db.refresh(event)
    return events


@router.post(
    "/projects/{project_id}/raw-entries/{raw_entry_id}/extract",
    response_model=list[ExtractedEventRead],
    status_code=status.HTTP_201_CREATED,
)
def extract_raw_entry_events(
    project_id: int,
    raw_entry_id: int,
    db: DbSession,
) -> list[ExtractedEvent]:
    raw_entry = _get_raw_entry(db, project_id, raw_entry_id)
    try:
        events = _validate_llm_events(extract(raw_entry.text), raw_entry.text)
        for event in events:
            event.project_id = project_id
            event.raw_entry_id = raw_entry_id
            event.status = ExtractedEventStatus.PENDING
        raw_entry.status = RawEntryStatus.PROCESSED
        db.add_all(events)
        db.commit()
    except Exception as exc:
        raw_entry.status = RawEntryStatus.FAILED
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Extraction failed",
        ) from exc

    for event in events:
        db.refresh(event)
    return events


@router.get(
    "/projects/{project_id}/extracted-events/pending",
    response_model=list[ExtractedEventRead],
)
def list_pending_events(project_id: int, db: DbSession) -> list[ExtractedEvent]:
    _get_project(db, project_id)
    return list(
        db.scalars(
            select(ExtractedEvent)
            .where(
                ExtractedEvent.project_id == project_id,
                ExtractedEvent.status == ExtractedEventStatus.PENDING,
            )
            .order_by(ExtractedEvent.created_at.desc(), ExtractedEvent.id.desc())
        )
    )


@router.get(
    "/projects/{project_id}/extracted-events/confirmed",
    response_model=list[ExtractedEventRead],
)
def list_confirmed_events(project_id: int, db: DbSession) -> list[ExtractedEvent]:
    _get_project(db, project_id)
    return list(
        db.scalars(
            select(ExtractedEvent)
            .where(
                ExtractedEvent.project_id == project_id,
                ExtractedEvent.status == ExtractedEventStatus.CONFIRMED,
            )
            .order_by(ExtractedEvent.created_at.desc(), ExtractedEvent.id.desc())
        )
    )


@router.patch("/extracted-events/{event_id}", response_model=ExtractedEventRead)
def update_extracted_event(
    event_id: int,
    payload: ExtractedEventUpdate,
    db: DbSession,
) -> ExtractedEvent:
    event = _get_event(db, event_id)
    _require_pending(event)
    for field, value in payload.model_dump(exclude_unset=True).items():
        old_value = getattr(event, field)
        if old_value == value:
            continue
        db.add(
            EventCorrection(
                event_id=event.id,
                field_name=field,
                old_value=_correction_value(old_value),
                new_value=_correction_value(value),
            )
        )
        setattr(event, field, value)
        event.user_edited = True
        event.updated_by_user_at = datetime.now()
    db.commit()
    db.refresh(event)
    return event


@router.get("/analytics/projects/{project_id}")
def get_project_analytics(project_id: int, db: DbSession) -> dict[str, int | float]:
    _get_project(db, project_id)
    total_raw_entries = db.scalar(
        select(func.count())
        .select_from(RawEntry)
        .where(RawEntry.project_id == project_id)
    )
    total_extracted_events = db.scalar(
        select(func.count())
        .select_from(ExtractedEvent)
        .where(ExtractedEvent.project_id == project_id)
    )
    confirmed_events = db.scalar(
        select(func.count())
        .select_from(ExtractedEvent)
        .where(
            ExtractedEvent.project_id == project_id,
            ExtractedEvent.status == ExtractedEventStatus.CONFIRMED,
        )
    )
    discarded_events = db.scalar(
        select(func.count())
        .select_from(ExtractedEvent)
        .where(
            ExtractedEvent.project_id == project_id,
            ExtractedEvent.status == ExtractedEventStatus.DISCARDED,
        )
    )
    edited_events_count = db.scalar(
        select(func.count())
        .select_from(ExtractedEvent)
        .where(
            ExtractedEvent.project_id == project_id,
            ExtractedEvent.user_edited.is_(True),
        )
    )
    total_events = total_extracted_events or 0

    return {
        "total_raw_entries": total_raw_entries or 0,
        "total_extracted_events": total_events,
        "confirmed_events": confirmed_events or 0,
        "discarded_events": discarded_events or 0,
        "edited_events_count": edited_events_count or 0,
        "edit_rate": (edited_events_count or 0) / total_events if total_events else 0,
    }


@router.post("/extracted-events/{event_id}/confirm", response_model=ExtractedEventRead)
def confirm_extracted_event(event_id: int, db: DbSession) -> ExtractedEvent:
    event = _get_event(db, event_id)
    _require_pending(event)
    event.status = ExtractedEventStatus.CONFIRMED
    db.commit()
    db.refresh(event)
    return event


@router.post("/extracted-events/{event_id}/discard", response_model=ExtractedEventRead)
def discard_extracted_event(event_id: int, db: DbSession) -> ExtractedEvent:
    event = _get_event(db, event_id)
    _require_pending(event)
    event.status = ExtractedEventStatus.DISCARDED
    db.commit()
    db.refresh(event)
    return event
