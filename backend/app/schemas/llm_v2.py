from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator


class LLMv2Intent(StrEnum):
    SETUP = "SETUP"
    WORK = "WORK"
    FINANCIAL = "FINANCIAL"
    NOTE = "NOTE"
    DOCUMENT = "DOCUMENT"


class LLMv2Action(StrEnum):
    ADD_ENTITY = "ADD_ENTITY"
    UPDATE_ENTITY = "UPDATE_ENTITY"
    WORK_LOG = "WORK_LOG"
    PAYMENT_IN = "PAYMENT_IN"
    PAYMENT_OUT = "PAYMENT_OUT"
    PURCHASE_PAID = "PURCHASE_PAID"
    DEBT_CREATED = "DEBT_CREATED"
    CHECK_PAYMENT = "CHECK_PAYMENT"
    NOTE = "NOTE"


class LLMv2EntityKind(StrEnum):
    PERSON = "PERSON"
    COMPANY = "COMPANY"
    UNKNOWN = "UNKNOWN"


class LLMv2ProjectRole(StrEnum):
    CLIENT = "CLIENT"
    DAILY_WORKER = "DAILY_WORKER"
    SKILLED_WORKER = "SKILLED_WORKER"
    VENDOR = "VENDOR"
    OTHER = "OTHER"


class LLMv2FinancialDirection(StrEnum):
    IN = "IN"
    OUT = "OUT"
    NONE = "NONE"


class LLMv2PaymentMethod(StrEnum):
    CASH = "CASH"
    BANK_TRANSFER = "BANK_TRANSFER"
    CHECK = "CHECK"
    OTHER = "OTHER"


class LLMv2WorkUnit(StrEnum):
    DAY = "day"
    METER = "meter"
    ITEM = "item"
    PROJECT = "project"
    CUSTOM = "custom"


class LLMv2Entity(BaseModel):
    name: str
    kind: LLMv2EntityKind = LLMv2EntityKind.UNKNOWN
    project_role: LLMv2ProjectRole = LLMv2ProjectRole.OTHER
    role_detail: str | None = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("entity name must not be empty")
        return stripped


class LLMv2Financial(BaseModel):
    amount: Decimal | None = None
    direction: LLMv2FinancialDirection = LLMv2FinancialDirection.NONE
    payment_method: LLMv2PaymentMethod | None = None
    due_date_text: str | None = None


class LLMv2Work(BaseModel):
    quantity: Decimal | None = None
    unit: LLMv2WorkUnit | None = None
    description: str | None = None


class LLMv2Note(BaseModel):
    text: str | None = None


class LLMv2Interpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: LLMv2Intent
    action: LLMv2Action
    entities: list[LLMv2Entity] = []
    financial: LLMv2Financial = LLMv2Financial()
    work: LLMv2Work = LLMv2Work()
    note: LLMv2Note = LLMv2Note()
    confidence: float = 0.0
    ambiguity: bool = False
    missing_fields: list[str] = []
    reasoning_summary: str = ""

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        return max(0.0, min(v, 1.0))

    @field_validator("reasoning_summary", mode="before")
    @classmethod
    def reasoning_fallback(cls, v: str | None) -> str:
        return v or ""
