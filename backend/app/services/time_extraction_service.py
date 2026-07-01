from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any


def _normalize(text: str | None) -> str:
    value = (text or "").strip().replace("ي", "ی").replace("ك", "ک")
    return " ".join(value.split())


def _base_day(base_date: datetime | date) -> date:
    if isinstance(base_date, datetime):
        return base_date.date()
    return base_date


def _result(
    *,
    due_date: date | None,
    confidence: float,
    source: str,
    hint: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "due_date": due_date.isoformat() if due_date else None,
        "confidence": confidence,
        "source": source,
    }
    if hint:
        payload["hint"] = hint
    return payload


def extract_due_date(text: str, base_date: datetime) -> dict[str, Any]:
    normalized = _normalize(text)
    today = _base_day(base_date)
    if not normalized:
        return _result(due_date=None, confidence=0.0, source="deterministic_rule")

    if "دیروز" in normalized:
        return _result(
            due_date=None,
            hint="past_date_ignored",
            confidence=0.0,
            source="deterministic_rule",
        )
    if "پس فردا" in normalized or "پسفردا" in normalized:
        return _result(
            due_date=today + timedelta(days=2),
            confidence=0.95,
            source="deterministic_rule",
        )
    if "فردا" in normalized:
        return _result(
            due_date=today + timedelta(days=1),
            confidence=0.95,
            source="deterministic_rule",
        )
    if "امروز" in normalized:
        return _result(due_date=today, confidence=0.95, source="deterministic_rule")
    if "هفته بعد" in normalized or "هفته آینده" in normalized:
        return _result(
            due_date=today + timedelta(days=7),
            hint="next_week",
            confidence=0.75,
            source="deterministic_rule",
        )
    if "این هفته" in normalized:
        return _result(
            due_date=None,
            hint="this_week",
            confidence=0.55,
            source="deterministic_rule",
        )

    uncertain_hints = {
        "آخر هفته": "end_of_week",
        "اخر هفته": "end_of_week",
        "چند روز دیگه": "next_few_days",
        "چند روز دیگر": "next_few_days",
        "به زودی": "soon",
        "بزودی": "soon",
    }
    for phrase, hint in uncertain_hints.items():
        if phrase in normalized:
            return _result(
                due_date=None,
                hint=hint,
                confidence=0.4,
                source="uncertain_llm",
            )

    return _result(due_date=None, confidence=0.0, source="deterministic_rule")
