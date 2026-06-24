from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

from app.core.trace_context import get_trace_id, new_trace_id, set_trace_id

_SERVICE_NAME: str | None = None

_STD_LOG_RECORD_ATTRS = frozenset({
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "message", "module",
    "msecs", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName", "taskName",
})


def get_service_name() -> str:
    global _SERVICE_NAME
    if _SERVICE_NAME is None:
        _SERVICE_NAME = os.getenv("SERVICE_NAME", "api")
    return _SERVICE_NAME


def _ensure_trace_id() -> str:
    trace_id = get_trace_id()
    if trace_id is None:
        trace_id = new_trace_id()
        set_trace_id(trace_id)
    return trace_id


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": get_service_name(),
            "trace_id": _ensure_trace_id(),
            "message": record.getMessage(),
        }

        event = getattr(record, "event", None)
        if event:
            entry["event"] = event

        payload = getattr(record, "payload", None)
        if payload is not None:
            entry["payload"] = payload
        else:
            extras: dict[str, Any] = {}
            for key, value in record.__dict__.items():
                if (
                    key not in _STD_LOG_RECORD_ATTRS
                    and not key.startswith("_")
                    and key not in ("event", "payload", "msg", "args")
                ):
                    extras[key] = _json_safe(value)
            if extras:
                entry["payload"] = extras

        if record.exc_info and record.exc_info[1]:
            entry.setdefault("payload", {})["error"] = _json_safe(record.exc_info[1])
            if record.exc_text:
                entry["payload"]["traceback"] = record.exc_text

        return json.dumps(entry, default=str, ensure_ascii=False)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, Exception):
        return {"type": type(value).__name__, "message": str(value)}
    return value


def log_event(
    trace_id: str | None = None,
    event: str | None = None,
    message: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    if trace_id is not None:
        set_trace_id(trace_id)
    _trace = _ensure_trace_id()
    logger = logging.getLogger("yara.event")
    extra: dict[str, Any] = {"event": event or message or "event"}
    if payload:
        extra["payload"] = payload
    logger.info(message or event or "event", extra=extra)


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    if root.handlers:
        root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)
