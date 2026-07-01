from datetime import UTC, datetime, timedelta

from app.services.time_extraction_service import extract_due_date


BASE_DATE = datetime(2026, 6, 30, 9, 0, tzinfo=UTC)


def test_extracts_today() -> None:
    result = extract_due_date("امروز بیاد کار کنه", BASE_DATE)

    assert result["due_date"] == "2026-06-30"
    assert result["confidence"] == 0.95
    assert result["source"] == "deterministic_rule"


def test_extracts_tomorrow() -> None:
    result = extract_due_date("فردا جوشکار بیاد", BASE_DATE)

    assert result["due_date"] == "2026-07-01"
    assert result["confidence"] == 0.95


def test_extracts_day_after_tomorrow_before_tomorrow_match() -> None:
    result = extract_due_date("پس فردا مش رحیم بیاد", BASE_DATE)

    assert result["due_date"] == "2026-07-02"


def test_no_date_is_non_blocking_null_result() -> None:
    result = extract_due_date("بیاد کار کنه", BASE_DATE)

    assert result["due_date"] is None
    assert result["confidence"] == 0.0


def test_next_week_extracts_approximate_date() -> None:
    result = extract_due_date("هفته بعد پروژه شروع بشه", BASE_DATE)

    assert result["due_date"] == (BASE_DATE.date() + timedelta(days=7)).isoformat()
    assert result["hint"] == "next_week"
    assert result["confidence"] == 0.75


def test_uncertain_time_phrase_returns_hint_without_due_date() -> None:
    result = extract_due_date("چند روز دیگه رنگ کار بیاد", BASE_DATE)

    assert result["due_date"] is None
    assert result["hint"] == "next_few_days"
    assert result["confidence"] == 0.4
    assert result["source"] == "uncertain_llm"
