from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Numeric, String, Text
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class RawEntryStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class ExtractedEventType(StrEnum):
    MONEY_IN = "MONEY_IN"
    MONEY_OUT = "MONEY_OUT"
    PURCHASE = "PURCHASE"
    NOTE = "NOTE"


class CounterpartyType(StrEnum):
    PERSON = "PERSON"
    VENDOR = "VENDOR"
    CLIENT = "CLIENT"
    UNKNOWN = "UNKNOWN"


class ExtractedEventStatus(StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    DISCARDED = "DISCARDED"


class PendingInterpretationStatus(StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    EDITED = "EDITED"
    DISCARDED = "DISCARDED"


class WorkerType(StrEnum):
    DAILY_WORKER = "DAILY_WORKER"
    SKILLED_WORKER = "SKILLED_WORKER"
    VENDOR = "VENDOR"
    CLIENT = "CLIENT"


class WorkUnit(StrEnum):
    METER = "meter"
    DAY = "day"
    ITEM = "item"
    PROJECT = "project"
    CUSTOM = "custom"


class InvoiceStatus(StrEnum):
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    PAID = "PAID"


class PaymentType(StrEnum):
    CASH = "CASH"
    BANK_TRANSFER = "BANK_TRANSFER"
    CHECK = "CHECK"
    OTHER = "OTHER"


class FinancialDirection(StrEnum):
    INCOMING = "INCOMING"
    OUTGOING = "OUTGOING"
    DEBT = "DEBT"
    DEFERRED = "DEFERRED"


class WorkerStateRole(StrEnum):
    DAILY = "DAILY"
    SKILLED = "SKILLED"
    VENDOR = "VENDOR"
    CLIENT = "CLIENT"


class HistoryChangeType(StrEnum):
    WORK = "WORK"
    PAYMENT = "PAYMENT"
    INVOICE = "INVOICE"
    SETUP = "SETUP"
    ENTITY_UPDATE = "ENTITY_UPDATE"
    NOTE = "NOTE"


class Project(TimestampMixin, Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    raw_entries: Mapped[list["RawEntry"]] = relationship(back_populates="project")
    extracted_events: Mapped[list["ExtractedEvent"]] = relationship(back_populates="project")
    workers: Mapped[list["Worker"]] = relationship(back_populates="project")
    work_logs: Mapped[list["WorkLog"]] = relationship(back_populates="project")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="project")
    payments: Mapped[list["Payment"]] = relationship(back_populates="project")
    worker_states: Mapped[list["WorkerState"]] = relationship(back_populates="project")
    history_entries: Mapped[list["HistoryEntry"]] = relationship(back_populates="project")
    pending_interpretations: Mapped[list["PendingInterpretation"]] = relationship(
        back_populates="project"
    )


class RawEntry(TimestampMixin, Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[RawEntryStatus] = mapped_column(
        SqlEnum(RawEntryStatus, native_enum=False, length=20),
        default=RawEntryStatus.PENDING,
        nullable=False,
    )

    project: Mapped[Project] = relationship(back_populates="raw_entries")
    extracted_events: Mapped[list["ExtractedEvent"]] = relationship(back_populates="raw_entry")


class ExtractedEvent(TimestampMixin, Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False, index=True)
    raw_entry_id: Mapped[int] = mapped_column(ForeignKey("rawentry.id"), nullable=False, index=True)
    type: Mapped[ExtractedEventType] = mapped_column(
        SqlEnum(ExtractedEventType, native_enum=False, length=20),
        nullable=False,
    )
    counterparty_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    counterparty_type: Mapped[CounterpartyType] = mapped_column(
        SqlEnum(CounterpartyType, native_enum=False, length=20),
        default=CounterpartyType.UNKNOWN,
        nullable=False,
    )
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_date: Mapped[date | None] = mapped_column(nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    user_edited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_by_user_at: Mapped[datetime | None] = mapped_column(nullable=True)
    status: Mapped[ExtractedEventStatus] = mapped_column(
        SqlEnum(ExtractedEventStatus, native_enum=False, length=20),
        default=ExtractedEventStatus.PENDING,
        nullable=False,
    )

    project: Mapped[Project] = relationship(back_populates="extracted_events")
    raw_entry: Mapped[RawEntry] = relationship(back_populates="extracted_events")
    corrections: Mapped[list["EventCorrection"]] = relationship(back_populates="event")


class EventCorrection(TimestampMixin, Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("extractedevent.id"),
        nullable=False,
        index=True,
    )
    field_name: Mapped[str] = mapped_column(String(100), nullable=False)
    old_value: Mapped[dict | str | int | float | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict | str | int | float | None] = mapped_column(JSON, nullable=True)

    event: Mapped[ExtractedEvent] = relationship(back_populates="corrections")


class Worker(TimestampMixin, Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[WorkerType] = mapped_column(
        SqlEnum(WorkerType, native_enum=False, length=30),
        nullable=False,
    )
    role_detail: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    account_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    project: Mapped[Project] = relationship(back_populates="workers")
    work_logs: Mapped[list["WorkLog"]] = relationship(back_populates="worker")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="vendor")
    payments: Mapped[list["Payment"]] = relationship(back_populates="entity")


class WorkLog(TimestampMixin, Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False, index=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("worker.id"), nullable=False, index=True)
    task_name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[WorkUnit] = mapped_column(
        SqlEnum(WorkUnit, native_enum=False, length=20),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    rate_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped[Project] = relationship(back_populates="work_logs")
    worker: Mapped[Worker] = relationship(back_populates="work_logs")


class Invoice(TimestampMixin, Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False, index=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("worker.id"), nullable=False, index=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[InvoiceStatus] = mapped_column(
        SqlEnum(InvoiceStatus, native_enum=False, length=20),
        default=InvoiceStatus.OPEN,
        nullable=False,
    )

    project: Mapped[Project] = relationship(back_populates="invoices")
    vendor: Mapped[Worker] = relationship(back_populates="invoices")
    payments: Mapped[list["Payment"]] = relationship(back_populates="related_invoice")


class Payment(TimestampMixin, Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False, index=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("worker.id"), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    related_invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoice.id"),
        nullable=True,
        index=True,
    )
    type: Mapped[PaymentType] = mapped_column(
        SqlEnum(PaymentType, native_enum=False, length=30),
        nullable=False,
    )
    due_date: Mapped[str | None] = mapped_column(String(100), nullable=True)
    direction: Mapped[FinancialDirection] = mapped_column(
        SqlEnum(FinancialDirection, native_enum=False, length=20),
        default=FinancialDirection.OUTGOING,
        nullable=False,
    )

    project: Mapped[Project] = relationship(back_populates="payments")
    entity: Mapped[Worker] = relationship(back_populates="payments")
    related_invoice: Mapped[Invoice | None] = relationship(back_populates="payments")


class WorkerState(TimestampMixin, Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False, index=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("worker.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[WorkerStateRole] = mapped_column(
        SqlEnum(WorkerStateRole, native_enum=False, length=20),
        nullable=False,
    )
    total_days_worked: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    total_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    financial_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)

    project: Mapped[Project] = relationship(back_populates="worker_states")
    worker: Mapped[Worker] = relationship()
    history_entries: Mapped[list["HistoryEntry"]] = relationship(back_populates="worker_state")


class HistoryEntry(TimestampMixin, Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False, index=True)
    worker_state_id: Mapped[int | None] = mapped_column(
        ForeignKey("workerstate.id"),
        nullable=True,
        index=True,
    )
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    change_type: Mapped[HistoryChangeType] = mapped_column(
        SqlEnum(HistoryChangeType, native_enum=False, length=20),
        nullable=False,
    )
    delta: Mapped[dict | str | int | float | None] = mapped_column(JSON, nullable=True)
    rule_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    explanation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    conflict_warnings: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)

    project: Mapped[Project] = relationship(back_populates="history_entries")
    worker_state: Mapped[WorkerState | None] = relationship(back_populates="history_entries")


class PendingInterpretation(TimestampMixin, Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), nullable=False, index=True)
    raw_input_text: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    semantic_action: Mapped[str] = mapped_column(String(100), nullable=False)
    suggested_entity_id: Mapped[int | None] = mapped_column(ForeignKey("worker.id"), nullable=True)
    matched_input_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extracted_entities: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    extracted_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    extracted_quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    financial_direction: Mapped[FinancialDirection | None] = mapped_column(
        SqlEnum(FinancialDirection, native_enum=False, length=20),
        nullable=True,
    )
    due_date: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    semantic_explanation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[PendingInterpretationStatus] = mapped_column(
        SqlEnum(PendingInterpretationStatus, native_enum=False, length=20),
        default=PendingInterpretationStatus.PENDING,
        nullable=False,
    )

    project: Mapped[Project] = relationship(back_populates="pending_interpretations")
