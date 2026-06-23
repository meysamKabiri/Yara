from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


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


class TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id() or "-"
        return True


def configure_trace_logging() -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=logging.INFO)
    if not any(isinstance(item, TraceIdFilter) for item in root.filters):
        root.addFilter(TraceIdFilter())
    formatter = logging.Formatter("[%(trace_id)s] %(levelname)s %(name)s: %(message)s")
    for handler in root.handlers:
        if not any(isinstance(item, TraceIdFilter) for item in handler.filters):
            handler.addFilter(TraceIdFilter())
        handler.setFormatter(formatter)


class TraceContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        trace_id = request.headers.get("X-Trace-Id") or new_trace_id()
        token = set_trace_id(trace_id)
        request.state.trace_id = trace_id
        try:
            try:
                response = await call_next(request)
            except Exception as exc:
                from app.core.trace_events import trace_error

                trace_error(exc, {"path": str(request.url.path), "method": request.method})
                raise
            response.headers["X-Trace-Id"] = trace_id
            return response
        finally:
            reset_trace_id(token)
