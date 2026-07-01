from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AuthCredentials(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserRead(BaseModel):
    id: UUID
    email: str
    created_at: datetime


class AuthResponse(TokenResponse):
    user: UserRead
