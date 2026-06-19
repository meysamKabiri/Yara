from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

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


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime
    updated_at: datetime


class ProjectTotals(BaseModel):
    money_in: Decimal
    money_out: Decimal
    net: Decimal


class ProjectDetail(ProjectRead):
    totals: ProjectTotals


class RawEntryCreate(BaseModel):
    text: str


class RawEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
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
    task_name: str | None = None
    unit: WorkUnit | None = None
    quantity: Decimal | None = None
    rate_per_unit: Decimal | None = None
    description: str | None = None


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
    description: str | None
    created_at: datetime
    updated_at: datetime


class InvoiceCreate(BaseModel):
    vendor_id: int
    total_amount: Decimal
    description: str | None = None


class InvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    vendor_id: int
    total_amount: Decimal
    description: str | None
    status: InvoiceStatus
    created_at: datetime
    updated_at: datetime


class PaymentCreate(BaseModel):
    entity_id: int
    amount: Decimal
    related_invoice_id: int | None = None
    type: PaymentType
    due_date: str | None = None
    direction: FinancialDirection = FinancialDirection.OUTGOING


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
    created_at: datetime
    updated_at: datetime


class NaturalInputCreate(BaseModel):
    text: str


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
    status: PendingInterpretationStatus
    created_at: datetime
    updated_at: datetime


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
