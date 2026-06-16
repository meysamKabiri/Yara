from datetime import date
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey, Numeric, String, Text
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


class Project(TimestampMixin, Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    raw_entries: Mapped[list["RawEntry"]] = relationship(back_populates="project")
    extracted_events: Mapped[list["ExtractedEvent"]] = relationship(back_populates="project")


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
    status: Mapped[ExtractedEventStatus] = mapped_column(
        SqlEnum(ExtractedEventStatus, native_enum=False, length=20),
        default=ExtractedEventStatus.PENDING,
        nullable=False,
    )

    project: Mapped[Project] = relationship(back_populates="extracted_events")
    raw_entry: Mapped[RawEntry] = relationship(back_populates="extracted_events")
