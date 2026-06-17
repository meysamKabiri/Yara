import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.dependencies.database import DbSession
from app.dev_tools.semantic_firewall.firewall import (
    SemanticFirewallError,
    SemanticFirewallService,
)
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
    ExtractedEventCreate,
    ExtractedEventRead,
    ExtractedEventUpdate,
    HistoryEntryRead,
    InvoiceCreate,
    InvoiceRead,
    NaturalInputInterpretationResult,
    NaturalInputCreate,
    NaturalInputResult,
    PaymentCreate,
    PaymentRead,
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
    WorkLogCreate,
    WorkLogRead,
    WorkLogUpdate,
)
from app.services.entity_registry import EntityRegistryService
from app.services.llm_extraction import extract, extract_graph
from app.services.persian_money_engine import normalize_text, parse_persian_money
from app.services.semantic_normalizer import (
    CanonicalEvent,
    CanonicalEventType,
    SemanticNormalizerService,
)

router = APIRouter(tags=["projects"])


def _get_project(db: DbSession, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def _get_raw_entry(db: DbSession, project_id: int, raw_entry_id: int) -> RawEntry:
    raw_entry = db.get(RawEntry, raw_entry_id)
    if raw_entry is None or raw_entry.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Raw entry not found")
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found")
    return worker


def _get_work_log(db: DbSession, work_log_id: int) -> WorkLog:
    work_log = db.get(WorkLog, work_log_id)
    if work_log is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work log not found")
    return work_log


def _get_invoice(db: DbSession, project_id: int, invoice_id: int) -> Invoice:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None or invoice.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
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
    return ProjectTotals(money_in=money_in, money_out=money_out, net=money_in - money_out)


def _work_log_total(quantity: Decimal, rate_per_unit: Decimal | None) -> Decimal | None:
    if rate_per_unit is None:
        return None
    return quantity * rate_per_unit


def _invoice_paid_amount(db: DbSession, invoice_id: int) -> Decimal:
    return db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.related_invoice_id == invoice_id
        )
    )


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
    if role == "WORKER" or event_type == "WORK_LOG":
        return WorkerType.DAILY_WORKER
    return WorkerType.DAILY_WORKER


def _role_to_state_role(role: str | None, text: str, intent: str | None = None) -> WorkerStateRole:
    normalized = normalize_text(text)
    if role == "CLIENT":
        return WorkerStateRole.CLIENT
    if role == "VENDOR" or intent == "INVOICE" or "خرید" in normalized or "فاکتور" in normalized:
        return WorkerStateRole.VENDOR
    if "کارفرما" in normalized:
        return WorkerStateRole.CLIENT
    if "جوشکار" in normalized or "برقکار" in normalized or role == "SKILLED":
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
        select(Worker).where(Worker.project_id == project_id, Worker.name == normalized_name)
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
        "conflict_warnings": conflict_warnings if isinstance(conflict_warnings, list) else [],
    }


def _semantic_history_fields_from_pending(
    interpretation: PendingInterpretation,
) -> dict[str, Any]:
    explanation = interpretation.semantic_explanation
    return {
        "rule_id": explanation.get("triggered_rule") if isinstance(explanation, dict) else None,
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
        payment_method = None
        if canonical_event.action in {"CHECK_PAYMENT", "DEFERRED_PAYMENT"}:
            payment_method = PaymentType.CHECK.value
        elif canonical_event.type == CanonicalEventType.FINANCIAL:
            payment_method = PaymentType.BANK_TRANSFER.value
        draft_entities = _draft_entities(event_graph, canonical_event, raw_text)
        raw_entity_name = _draft_entity_name(draft_entities)
        resolved_entity = _resolve_existing_entity(raw_entity_name, entity_context)
        financial_direction = _financial_direction(
            raw_text,
            canonical_event.type,
            canonical_event.action,
            resolved_entity,
        )
        if resolved_entity is not None and draft_entities:
            draft_entities[0] = {
                **draft_entities[0],
                "name": resolved_entity.name,
                "type": resolved_entity.type.value,
            }
        interpretations.append(
            PendingInterpretation(
                project_id=project_id,
                raw_input_text=raw_text,
                canonical_event_type=canonical_event.type.value,
                semantic_action=canonical_event.action,
                suggested_entity_id=resolved_entity.id if resolved_entity is not None else None,
                matched_input_text=(
                    raw_entity_name
                    if resolved_entity is not None and raw_entity_name != resolved_entity.name
                    else None
                ),
                extracted_entities=draft_entities,
                extracted_amount=_graph_amount(event_graph, raw_text),
                extracted_quantity=_graph_quantity(event_graph),
                payment_method=payment_method,
                financial_direction=financial_direction,
                due_date=_extract_due_date(raw_text),
                description=_draft_description(event_graph, raw_text),
                semantic_explanation=canonical_event.metadata.get("semantic_explanation"),
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
    if entity_name is None:
        return []
    return [{"name": entity_name, "type": _graph_role_guess(graph) or "WORKER"}]


def _parse_setup_entities_from_text(text: str) -> list[dict[str, Any]]:
    normalized = normalize_text(text)
    if not _has_worker_setup_phrase(normalized):
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
                "type": "WORKER",
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


def _resolve_existing_entity(name: str | None, entity_context: list[Worker]) -> Worker | None:
    if name is None:
        return None
    normalized = _normalize_entity_match_text(name)
    if not normalized:
        return None
    buckets: list[list[Worker]] = [
        [worker for worker in entity_context if _normalize_entity_match_text(worker.name) == normalized],
        [worker for worker in entity_context if _normalize_entity_match_text(worker.name).startswith(normalized)],
        [
            worker
            for worker in entity_context
            if normalized in _normalize_entity_match_text(worker.name).split()
        ],
        [worker for worker in entity_context if normalized in _normalize_entity_match_text(worker.name)],
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
    if resolved_entity is not None and resolved_entity.type == WorkerType.CLIENT:
        if any(phrase in normalized for phrase in ["پول داد", "پرداخت کرد", "واریز کرد", "داد برای"]):
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


def _validate_llm_events(raw_events: list[dict[str, Any]], raw_text: str) -> list[ExtractedEvent]:
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
    return Decimal(amount) if amount is not None else None


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


@router.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: DbSession) -> Project:
    project = Project(name=payload.name)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/projects", response_model=list[ProjectRead])
def list_projects(db: DbSession) -> list[Project]:
    return list(db.scalars(select(Project).order_by(Project.created_at.desc(), Project.id.desc())))


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
def create_raw_entry(project_id: int, payload: RawEntryCreate, db: DbSession) -> RawEntry:
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
    response_model=NaturalInputInterpretationResult,
    status_code=status.HTTP_201_CREATED,
)
def process_natural_input(
    project_id: int,
    payload: NaturalInputCreate,
    db: DbSession,
) -> NaturalInputInterpretationResult:
    _get_project(db, project_id)
    graph = extract_graph(payload.text)
    entity_context = list(db.scalars(select(Worker).where(Worker.project_id == project_id)))
    canonical_event = SemanticNormalizerService().normalize(graph, payload.text, entity_context)
    try:
        firewall_decision = SemanticFirewallService().validate(
            canonical_event,
            payload.text,
            entity_context,
            graph,
        )
    except SemanticFirewallError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    canonical_event = firewall_decision.event
    interpretations = _build_pending_interpretations(
        project_id,
        payload.text,
        graph,
        canonical_event,
        entity_context,
    )
    for interpretation in interpretations:
        db.add(interpretation)
    db.commit()
    for interpretation in interpretations:
        db.refresh(interpretation)
    return NaturalInputInterpretationResult(interpretations=interpretations)


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
                    [PendingInterpretationStatus.PENDING, PendingInterpretationStatus.EDITED]
                )
            )
            .order_by(PendingInterpretation.created_at.desc(), PendingInterpretation.id.desc())
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
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Interpretation is closed")
    for key, value in payload.model_dump(exclude_unset=True).items():
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
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Interpretation confirmed")
    interpretation.status = PendingInterpretationStatus.DISCARDED
    db.commit()
    db.refresh(interpretation)
    return interpretation


@router.post(
    "/pending-interpretations/{interpretation_id}/confirm",
    response_model=NaturalInputResult,
)
def confirm_pending_interpretation(
    interpretation_id: int,
    db: DbSession,
) -> NaturalInputResult:
    interpretation = _get_pending_interpretation(db, interpretation_id)
    if interpretation.status not in {
        PendingInterpretationStatus.PENDING,
        PendingInterpretationStatus.EDITED,
    }:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Interpretation is closed")
    result = _execute_pending_interpretation(db, interpretation)
    interpretation.status = PendingInterpretationStatus.CONFIRMED
    db.commit()
    db.refresh(interpretation)
    return result


def _get_pending_interpretation(db: DbSession, interpretation_id: int) -> PendingInterpretation:
    interpretation = db.get(PendingInterpretation, interpretation_id)
    if interpretation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interpretation not found")
    return interpretation


def _execute_pending_interpretation(
    db: DbSession,
    interpretation: PendingInterpretation,
) -> NaturalInputResult:
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
        created = EntityRegistryService(db, interpretation.project_id).apply_setup(
            interpretation.extracted_entities or []
        )
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
        updated = registry.update_entities(entities) if _has_entity_field_updates(entities) else []
        if not updated:
            updated = registry.update_entity_by_partial_match(interpretation.raw_input_text)
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
            delta=_history_delta(canonical_event_type=event_type, semantic_action=action),
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
        if not _pending_allows_new_entity(interpretation):
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
        state = _find_or_create_worker_state(db, interpretation.project_id, pending_worker.name, role)
        if state.worker_id != pending_worker.id:
            state.worker_id = pending_worker.id
            state.role = role
        workers.append(pending_worker)
    else:
        state = _find_or_create_worker_state(db, interpretation.project_id, entity_name, role)
        worker = db.get(Worker, state.worker_id)
        if worker is not None:
            workers.append(worker)
    states.append(state)

    if event_type == CanonicalEventType.WORK.value:
        quantity = interpretation.extracted_quantity or Decimal("1")
        if state.role == WorkerStateRole.DAILY:
            state.total_days_worked += quantity
            delta = _history_delta(canonical_event_type=event_type, semantic_action=action, days=quantity)
        else:
            state.total_quantity += quantity
            state.unit = state.unit or _unit_from_text(interpretation.raw_input_text, state.role)
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
            unit=WorkUnit.DAY if state.role == WorkerStateRole.DAILY else WorkUnit.CUSTOM,
            quantity=quantity,
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
    elif event_type == CanonicalEventType.FINANCIAL.value and interpretation.financial_direction == FinancialDirection.DEBT:
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
            payment_type = PaymentType(interpretation.payment_method or PaymentType.BANK_TRANSFER.value)
            direction = interpretation.financial_direction or FinancialDirection.OUTGOING
            if direction == FinancialDirection.INCOMING:
                state.role = WorkerStateRole.CLIENT
                state.financial_balance += amount
            else:
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


def _pending_worker(db: DbSession, interpretation: PendingInterpretation) -> Worker | None:
    if interpretation.suggested_entity_id is None:
        return None
    worker = db.get(Worker, interpretation.suggested_entity_id)
    if worker is None or worker.project_id != interpretation.project_id:
        return None
    return worker


def _pending_allows_new_entity(interpretation: PendingInterpretation) -> bool:
    entities = interpretation.extracted_entities or []
    return bool(entities and entities[0].get("create_new") is True)


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
    return _role_to_state_role(None, interpretation.raw_input_text, interpretation.semantic_action)


def _has_entity_field_updates(entities: list[dict]) -> bool:
    for entity in entities:
        updates = entity.get("field_updates") if isinstance(entity.get("field_updates"), dict) else entity
        if any(updates.get(key) for key in ["phone", "account_number", "role_detail"]):
            return True
    return False


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
        return "INVOICE" if semantic_action in {"INVOICE", "DEBT_CREATED"} else "PAYMENT"
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
            entity_type = entity.get("type") or entity.get("role_guess") or "WORKER"
            field_updates = entity.get("field_updates")
            updates = field_updates if isinstance(field_updates, dict) else entity
            setup_entities.append(
                {
                    "type": entity_type,
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
                "type": graph.get("role_guess") or "WORKER",
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
            _role_to_worker_type(
                None,
                raw_event.get("type") if isinstance(raw_event.get("type"), str) else None,
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
                _role_to_worker_type(
                    first.get("role_guess") if isinstance(first.get("role_guess"), str) else None,
                    raw_event.get("type") if isinstance(raw_event.get("type"), str) else None,
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


@router.get("/projects/{project_id}/workers", response_model=list[WorkerRead])
def list_workers(project_id: int, db: DbSession) -> list[Worker]:
    _get_project(db, project_id)
    return list(
        db.scalars(
            select(Worker)
            .where(Worker.project_id == project_id)
            .order_by(Worker.created_at.desc(), Worker.id.desc())
        )
    )


@router.get("/projects/{project_id}/worker-states", response_model=list[WorkerStateRead])
def list_worker_states(project_id: int, db: DbSession) -> list[WorkerState]:
    _get_project(db, project_id)
    return list(
        db.scalars(
            select(WorkerState)
            .where(WorkerState.project_id == project_id)
            .order_by(WorkerState.updated_at.desc(), WorkerState.id.desc())
        )
    )


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
    invoice = Invoice(project_id=project_id, status=InvoiceStatus.OPEN, **payload.model_dump())
    db.add(invoice)
    state = _find_or_create_worker_state(db, project_id, vendor.name, WorkerStateRole.VENDOR)
    state.financial_balance += payload.total_amount
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
    _get_worker(db, project_id, payload.entity_id)
    invoice = None
    if payload.related_invoice_id is not None:
        invoice = _get_invoice(db, project_id, payload.related_invoice_id)
        if invoice.vendor_id != payload.entity_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Payment entity must match invoice vendor",
            )
    payment = Payment(project_id=project_id, **payload.model_dump())
    db.add(payment)
    db.flush()
    entity = _get_worker(db, project_id, payload.entity_id)
    state_role = (
        WorkerStateRole.CLIENT
        if payload.direction == FinancialDirection.INCOMING or entity.type == WorkerType.CLIENT
        else WorkerStateRole.VENDOR
        if entity.type == WorkerType.VENDOR
        else WorkerStateRole.DAILY
    )
    state = _find_or_create_worker_state(db, project_id, entity.name, state_role)
    if payload.direction == FinancialDirection.INCOMING:
        state.financial_balance += payload.amount
    else:
        state.financial_balance -= payload.amount
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
    total_work_amount = db.scalar(
        select(func.coalesce(func.sum(WorkLog.total_amount), 0)).where(
            WorkLog.project_id == project_id
        )
    )
    total_invoice_amount = db.scalar(
        select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
            Invoice.project_id == project_id
        )
    )
    total_payments = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.project_id == project_id)
    )
    vendor_states = db.scalars(
        select(WorkerState).where(
            WorkerState.project_id == project_id,
            WorkerState.role == WorkerStateRole.VENDOR,
        )
    )
    vendor_debts = []
    for state in vendor_states:
        invoice_total = db.scalar(
            select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
                Invoice.project_id == project_id,
                Invoice.vendor_id == state.worker_id,
            )
        )
        paid_total = db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.project_id == project_id,
                Payment.entity_id == state.worker_id,
            )
        )
        vendor_debts.append(
            {
                "vendor_id": state.worker_id,
                "vendor_name": state.name,
                "invoice_total": str(invoice_total),
                "paid_total": str(paid_total),
                "debt": str(state.financial_balance),
            }
        )

    return {
        "total_work_amount": str(total_work_amount),
        "total_invoice_amount": str(total_invoice_amount),
        "total_payments": str(total_payments),
        "vendor_debts": vendor_debts,
    }


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
            ai_confidence=float(event.confidence) if event.confidence is not None else None,
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
        select(func.count()).select_from(RawEntry).where(RawEntry.project_id == project_id)
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
        .where(ExtractedEvent.project_id == project_id, ExtractedEvent.user_edited.is_(True))
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
