from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.core import InterpretationFeedbackSource


class InterpretationFeedbackCreate(BaseModel):
    trace_id: str | None = None
    project_id: int
    raw_input: str
    system_output: dict[str, Any]
    user_final_state: dict[str, Any]
    correction_source: InterpretationFeedbackSource = InterpretationFeedbackSource.USER_EDIT


class InterpretationFeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: int
    trace_id: str | None
    raw_input: str
    system_output: dict[str, Any]
    user_final_state: dict[str, Any]
    error_types: list[str]
    correction_source: InterpretationFeedbackSource
    created_at: datetime
    updated_at: datetime
