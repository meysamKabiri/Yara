from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


logger = logging.getLogger(__name__)


_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
_job_id: ContextVar[str | None] = ContextVar("job_id", default=None)


def new_trace_id() -> str:
    return str(uuid.uuid4())


def get_trace_id() -> str | None:
    return _trace_id.get()


def current_trace_id() -> str | None:
    return get_trace_id()


def set_trace_id(trace_id: str) -> Any:
    return _trace_id.set(trace_id)


def reset_trace_id(token: Any) -> None:
    _trace_id.reset(token)


def clear_trace_id() -> None:
    _trace_id.set(None)


def get_job_id() -> str | None:
    return _job_id.get()


def set_job_id(job_id: str | None) -> Any:
    return _job_id.set(job_id)


def reset_job_id(token: Any) -> None:
    _job_id.reset(token)


def set_trace_context(job_id: str | None, trace_id: str | None) -> tuple[Any | None, Any | None]:
    trace_token = set_trace_id(trace_id) if trace_id is not None else None
    job_token = set_job_id(job_id)
    return job_token, trace_token


class TraceContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        trace_id = request.headers.get("X-Trace-Id") or new_trace_id()
        token = set_trace_id(trace_id)
        request.state.trace_id = trace_id
        try:
            try:
                response = await call_next(request)
            except Exception as exc:
                logger.exception("Unhandled exception during request", extra={"path": str(request.url.path), "method": request.method})
                raise
            response.headers["X-Trace-Id"] = trace_id
            return response
        finally:
            reset_trace_id(token)
