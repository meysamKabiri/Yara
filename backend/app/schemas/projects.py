from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.models.core import (
    CounterpartyType,
    ExtractedEventStatus,
    ExtractedEventType,
    RawEntryStatus,
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
    status: ExtractedEventStatus
    created_at: datetime
    updated_at: datetime
