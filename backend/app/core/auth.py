from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from sqlalchemy import select

from app.core.config import settings
from app.dependencies.database import DbSession
from app.models.core import LEGACY_OWNER_ID, User


current_user_id: ContextVar[UUID | None] = ContextVar("current_user_id", default=None)
current_user_email: ContextVar[str | None] = ContextVar("current_user_email", default=None)
auth_request_active: ContextVar[bool] = ContextVar("auth_request_active", default=False)

_bearer = HTTPBearer(auto_error=False)
_JWT_ALGORITHM = "HS256"
_TOKEN_TTL = timedelta(days=7)
_PBKDF2_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _PBKDF2_ITERATIONS,
    )
    return "pbkdf2_sha256${iterations}${salt}${digest}".format(
        iterations=_PBKDF2_ITERATIONS,
        salt=base64.urlsafe_b64encode(salt).decode("ascii"),
        digest=base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
    except Exception:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def create_access_token(user: User) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "iat": int(now.timestamp()),
        "exp": int((now + _TOKEN_TTL).timestamp()),
    }
    return _encode_jwt(payload)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        header_segment, payload_segment, signature_segment = token.split(".", 2)
    except ValueError as exc:
        raise ValueError("Invalid token") from exc
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    expected = _sign(signing_input)
    actual = _base64url_decode(signature_segment)
    if not hmac.compare_digest(actual, expected):
        raise ValueError("Invalid token signature")
    header = json.loads(_base64url_decode(header_segment))
    if header.get("alg") != _JWT_ALGORITHM:
        raise ValueError("Invalid token algorithm")
    payload = json.loads(_base64url_decode(payload_segment))
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(datetime.now(UTC).timestamp()):
        raise ValueError("Token expired")
    return payload


def get_current_user(
    db: DbSession,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = UUID(str(payload["sub"]))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    current_user_id.set(user.id)
    current_user_email.set(user.email)
    return user


def require_current_user(user: User = Depends(get_current_user)) -> User:
    return user


def authenticated_user_id() -> UUID:
    user_id = current_user_id.get()
    if user_id is None:
        if not auth_request_active.get():
            return LEGACY_OWNER_ID
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user_id


class AuthContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        user_token = current_user_id.set(None)
        email_token = current_user_email.set(None)
        active_token = auth_request_active.set(True)
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            token = authorization.split(" ", 1)[1].strip()
            try:
                payload = decode_access_token(token)
                user_id = UUID(str(payload["sub"]))
                from app.db.session import SessionLocal

                db = SessionLocal()
                try:
                    user = db.get(User, user_id)
                    if user is not None:
                        current_user_id.set(user.id)
                        current_user_email.set(user.email)
                finally:
                    db.close()
            except Exception:
                pass
        try:
            return await call_next(request)
        finally:
            current_user_id.reset(user_token)
            current_user_email.reset(email_token)
            auth_request_active.reset(active_token)


def _encode_jwt(payload: dict[str, Any]) -> str:
    header = {"typ": "JWT", "alg": _JWT_ALGORITHM}
    header_segment = _base64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_segment = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    signature_segment = _base64url_encode(_sign(signing_input))
    return f"{header_segment}.{payload_segment}.{signature_segment}"


def _sign(signing_input: bytes) -> bytes:
    return hmac.new(_jwt_secret(), signing_input, hashlib.sha256).digest()


def _jwt_secret() -> bytes:
    secret = getattr(settings, "jwt_secret", None) or os.getenv("JWT_SECRET") or "dev-only-yara-secret"
    return secret.encode("utf-8")


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))
