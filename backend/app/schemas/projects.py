from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.core import (
    CounterpartyType,
    ExtractedEventStatus,
    ExtractedEventType,
    HistoryChangeType,
    InvoiceStatus,
    FinancialDirection,
    PaymentType,
    PendingInterpretationStatus,
    RawEntryStatus,
    WorkerStateRole,
    WorkerType,
    WorkUnit,
)


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("Project name is required")
        return name

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class ProjectUpdate(ProjectCreate):
    pass


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime


class ProjectTotals(BaseModel):
    money_in: Decimal
    money_out: Decimal
    net: Decimal


class ProjectDetail(ProjectRead):
    totals: ProjectTotals


class ProjectSummary(BaseModel):
    total_received: Decimal
    total_paid_out: Decimal
    open_payables: Decimal
    deferred_amount: Decimal
    check_amount: Decimal
    project_balance: Decimal
    available_balance: Decimal
    total_work_amount: Decimal
    total_invoice_amount: Decimal
    client_receivable: Decimal
    vendor_debts: list[dict[str, str | int | Decimal]]
    worker_payables: list[dict[str, str | int | Decimal]]


class ProjectDetailWithSummary(ProjectDetail):
    summary: ProjectSummary | None = None


class RawEntryCreate(BaseModel):
    text: str
    idempotency_key: str | None = None


class RawEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    job_id: str | None = None
    idempotency_key: str | None = None
    text: str
    status: RawEntryStatus
    created_at: datetime
    updated_at: datetime


class ExtractedEventCreate(BaseModel):
    type: ExtractedEventType
    counterparty_name: str | None = None
    counterparty_type: CounterpartyType = CounterpartyType.UNKNOWN
    amount: Decimal | None = None
    description: str | None = None
    event_date: date | None = None
    confidence: Decimal | None = None


class ExtractedEventUpdate(BaseModel):
    type: ExtractedEventType | None = None
    counterparty_name: str | None = None
    counterparty_type: CounterpartyType | None = None
    amount: Decimal | None = None
    description: str | None = None
    event_date: date | None = None
    confidence: Decimal | None = None


class ExtractedEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    raw_entry_id: int
    type: ExtractedEventType
    counterparty_name: str | None
    counterparty_type: CounterpartyType
    amount: Decimal | None
    description: str | None
    event_date: date | None
    confidence: Decimal | None
    ai_confidence: float | None
    user_edited: bool
    updated_by_user_at: datetime | None
    status: ExtractedEventStatus
    created_at: datetime
    updated_at: datetime


class WorkerCreate(BaseModel):
    name: str
    type: WorkerType
    role_detail: str | None = None
    phone: str | None = None
    account_number: str | None = None
    daily_rate: Decimal | None = None
    notes: str | None = None


class WorkerUpdate(BaseModel):
    name: str | None = None
    type: WorkerType | None = None
    role_detail: str | None = None
    phone: str | None = None
    account_number: str | None = None
    daily_rate: Decimal | None = None
    notes: str | None = None


class WorkerRead(WorkerCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    created_at: datetime
    updated_at: datetime


class WorkLogCreate(BaseModel):
    worker_id: int
    task_name: str
    unit: WorkUnit
    quantity: Decimal
    rate_per_unit: Decimal | None = None
    description: str | None = None


class WorkLogUpdate(BaseModel):
    worker_id: int | None = None
    task_name: str | None = None
    unit: WorkUnit | None = None
    quantity: Decimal | None = None
    rate_per_unit: Decimal | None = None
    period_label: str | None = None
    description: str | None = None
    correction_note: str | None = None


class WorkLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    worker_id: int
    task_name: str
    unit: WorkUnit
    quantity: Decimal
    rate_per_unit: Decimal | None
    total_amount: Decimal | None
    period_label: str | None = None
    source_pending_interpretation_id: int | None = None
    description: str | None
    is_voided: bool = False
    void_reason: str | None = None
    voided_at: datetime | None = None
    correction_note: str | None = None
    corrected_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class TaskAssigneeSuggestion(BaseModel):
    suggested_person: dict[str, Any] | None = None
    source: str = "none"
    candidates: list[dict[str, Any]] = []


class ProjectTaskCreate(BaseModel):
    title: str
    raw_text: str | None = None
    extracted_actor: str | None = None
    assign_to_person: bool = False
    assignee_id: int | None = None
    due_date: date | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("Task title is required")
        return title


class ProjectTaskSuggestRequest(BaseModel):
    title: str
    raw_text: str | None = None
    extracted_actor: str | None = None


class ProjectTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    title: str
    description: str | None = None
    raw_text: str | None = None
    assignee_id: int | None = None
    assignee_suggestion: dict[str, Any] | None = None
    suggestion_source: str = "none"
    assignment_status: str = "unassigned"
    status: str = "PENDING"
    confidence: float | None = None
    final_task_object: dict[str, Any] | None = None
    due_date: date | None = None
    due_date_confidence: float | None = None
    due_date_source: str | None = None
    created_at: datetime
    updated_at: datetime


class ProjectTaskCreateResponse(BaseModel):
    final_task_object: dict[str, Any] | None = None
    task_id: int | None = None
    task: ProjectTaskRead
    assignment_suggestion: TaskAssigneeSuggestion
    interpretations: list[dict[str, Any]] = Field(default_factory=list)
    interpretations_deprecated: bool = True


class ProjectTaskUpdate(BaseModel):
    status: str | None = None
    assignee_id: int | None = None
    due_date: str | None = None


class ProjectTaskUpdateResponse(ProjectTaskRead):
    task_id: int
    updated: bool = True


class InvoiceCreate(BaseModel):
    vendor_id: int
    total_amount: Decimal
    description: str | None = None


class InvoiceUpdate(BaseModel):
    vendor_id: int | None = None
    total_amount: Decimal | None = None
    status: InvoiceStatus | None = None
    description: str | None = None
    correction_note: str | None = None


class InvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    vendor_id: int
    total_amount: Decimal
    description: str | None
    status: InvoiceStatus
    is_voided: bool = False
    void_reason: str | None = None
    voided_at: datetime | None = None
    correction_note: str | None = None
    corrected_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PaymentCreate(BaseModel):
    entity_id: int
    amount: Decimal
    related_invoice_id: int | None = None
    type: PaymentType
    due_date: str | None = None
    direction: FinancialDirection = FinancialDirection.OUTGOING
    description: str | None = None


class PaymentUpdate(BaseModel):
    entity_id: int | None = None
    amount: Decimal | None = None
    related_invoice_id: int | None = None
    type: PaymentType | None = None
    due_date: str | None = None
    direction: FinancialDirection | None = None
    description: str | None = None
    correction_note: str | None = None


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    entity_id: int
    amount: Decimal
    related_invoice_id: int | None
    type: PaymentType
    due_date: str | None
    direction: FinancialDirection
    description: str | None = None
    is_voided: bool = False
    void_reason: str | None = None
    voided_at: datetime | None = None
    correction_note: str | None = None
    corrected_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class WorkerStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    worker_id: int
    name: str
    role: WorkerStateRole
    total_days_worked: Decimal
    total_quantity: Decimal
    unit: str | None
    financial_balance: Decimal
    created_at: datetime
    updated_at: datetime


class HistoryEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    worker_state_id: int | None
    input_text: str
    change_type: HistoryChangeType
    delta: dict | str | int | float | None
    rule_id: str | None
    explanation: dict | None
    conflict_warnings: list[dict] | None
    is_voided: bool = False
    void_reason: str | None = None
    voided_at: datetime | None = None
    correction_note: str | None = None
    corrected_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class NoteUpdate(BaseModel):
    text: str
    correction_note: str | None = None


class VoidPayload(BaseModel):
    reason: str | None = None


class NaturalInputCreate(BaseModel):
    text: str
    idempotency_key: str | None = None


class DomainRouteRead(BaseModel):
    domain: str
    confidence: float
    required_schema: str
    ui_mode: str


class PendingInterpretationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    raw_input_text: str
    canonical_event_type: str
    semantic_action: str
    suggested_entity_id: int | None
    matched_input_text: str | None
    extracted_entities: list[dict] | None
    extracted_amount: Decimal | None
    extracted_quantity: Decimal | None
    payment_method: str | None
    financial_direction: FinancialDirection | None
    due_date: str | None
    description: str | None
    semantic_explanation: dict | None
    confidence: float | None
    structured_interpretation: dict | None = None
    domain_route: DomainRouteRead | None = None
    status: PendingInterpretationStatus
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def attach_domain_route(self) -> "PendingInterpretationRead":
        if self.domain_route is None:
            from app.core.pending_domain_route import pending_route_input
            from app.models.core import PendingInterpretation
            from app.services.domain_router_service import DomainRouterService

            legacy_interpretation = PendingInterpretation(
                project_id=self.project_id,
                raw_input_text=self.raw_input_text,
                canonical_event_type=self.canonical_event_type,
                semantic_action=self.semantic_action,
                suggested_entity_id=self.suggested_entity_id,
                matched_input_text=self.matched_input_text,
                extracted_entities=self.extracted_entities,
                extracted_amount=self.extracted_amount,
                extracted_quantity=self.extracted_quantity,
                payment_method=self.payment_method,
                financial_direction=self.financial_direction,
                due_date=self.due_date,
                description=self.description,
                semantic_explanation=self.semantic_explanation,
                confidence=self.confidence,
                structured_interpretation=self.structured_interpretation,
                status=self.status,
            )
            # Legacy migration compatibility: old rows may not have a stored route.
            self.domain_route = DomainRouteRead(
                **DomainRouterService().route(
                    self.raw_input_text,
                    pending_route_input(legacy_interpretation),
                )
            )
        return self


class PendingInterpretationUpdate(BaseModel):
    canonical_event_type: str | None = None
    semantic_action: str | None = None
    suggested_entity_id: int | None = None
    matched_input_text: str | None = None
    extracted_entities: list[dict] | None = None
    extracted_amount: Decimal | None = None
    extracted_quantity: Decimal | None = None
    payment_method: str | None = None
    financial_direction: FinancialDirection | None = None
    due_date: str | None = None
    description: str | None = None
    structured_interpretation: dict | None = None


class PendingInterpretationConfirm(BaseModel):
    entity_id: int | None = None
    person_id: int | None = None
    selected_person_id: int | None = None
    selected_entity_id: int | None = None
    confirmed: bool = False
    create_new: bool = False
    name: str | None = None
    role: str | None = None
    role_detail: str | None = None
    field_updates: dict[str, Any] | None = None
    amount: Decimal | None = None
    direction: FinancialDirection | None = None
    payment_method: PaymentType | None = None
    description: str | None = None
    due_date: str | None = None


class EntityResolutionResult(BaseModel):
    status: str
    entity_id: int
    is_new: bool = False
    name: str
    role: str
    requires_confirmation: bool = False


class NaturalInputInterpretationResult(BaseModel):
    interpretations: list[PendingInterpretationRead]


class NaturalInputResult(BaseModel):
    raw_entry_id: int
    intent: str
    workers: list[WorkerRead]
    states: list[WorkerStateRead]
    history_entries: list[HistoryEntryRead]
    work_logs: list[WorkLogRead]
    invoices: list[InvoiceRead]
    payments: list[PaymentRead]
