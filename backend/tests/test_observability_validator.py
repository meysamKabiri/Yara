import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.observability_validator import validate_trace, validate_all_traces, observability_health_summary
from app.models.core import TraceEvent


def _insert_trace_event(
    db: Session,
    trace_id: str,
    event_index: int,
    event_name: str = "JOB_CREATED",
    event_group: str = "JOB",
) -> TraceEvent:
    event = TraceEvent(
        id=uuid.uuid4(),
        trace_id=trace_id,
        event_name=event_name,
        event_group=event_group,
        event_index=event_index,
        duration_ms=None,
        payload={},
    )
    db.add(event)
    db.flush()
    return event


def test_valid_trace(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    db: Session = session_factory()
    try:
        trace_id = "validator-valid-trace"
        for i in range(1, 6):
            _insert_trace_event(db, trace_id, i, event_name=f"TEST_EVENT_{i}", event_group="PIPELINE")
        db.commit()

        report = validate_trace(trace_id, db=db)
        assert report["valid"], f"Expected valid trace: {report['errors']}"
        assert report["event_count"] == 5
        assert report["first_index"] == 1
        assert report["last_index"] == 5
        assert report["gaps"] == []
        assert report["duplicates"] == []
    finally:
        db.close()


def test_trace_with_gaps(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    db: Session = session_factory()
    try:
        trace_id = "validator-gap-trace"
        _insert_trace_event(db, trace_id, 1)
        _insert_trace_event(db, trace_id, 3)
        _insert_trace_event(db, trace_id, 7)
        db.commit()

        report = validate_trace(trace_id, db=db)
        assert not report["valid"]
        assert report["gaps"] == [2, 4, 5, 6]
        assert report["event_count"] == 3
    finally:
        db.close()


def test_trace_with_duplicate_indices(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    db: Session = session_factory()
    try:
        trace_id = "validator-dup-trace"
        _insert_trace_event(db, trace_id, 1)
        _insert_trace_event(db, trace_id, 1)
        _insert_trace_event(db, trace_id, 2)
        db.commit()

        report = validate_trace(trace_id, db=db)
        assert not report["valid"]
        assert report["duplicates"] == [1]
    finally:
        db.close()


def test_out_of_order_events(client: TestClient) -> None:
    """get_trace_events returns events ordered by event_index, so
    out-of-order detection is based on index gaps, not insert order."""
    session_factory = client.app.state.testing_session_factory
    db: Session = session_factory()
    try:
        trace_id = "validator-ooo-trace"
        _insert_trace_event(db, trace_id, 3)
        _insert_trace_event(db, trace_id, 1)
        _insert_trace_event(db, trace_id, 4)
        db.commit()

        report = validate_trace(trace_id, db=db)
        assert not report["valid"]
        assert 2 in report["gaps"]
    finally:
        db.close()


def test_empty_trace(client: TestClient) -> None:
    report = validate_trace("nonexistent-trace")
    assert report["valid"]
    assert report["event_count"] == 0
    assert report["first_index"] is None


def test_group_tracking(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    db: Session = session_factory()
    try:
        trace_id = "validator-group-trace"
        _insert_trace_event(db, trace_id, 1, event_name="JOB_CREATED", event_group="JOB")
        _insert_trace_event(db, trace_id, 2, event_name="JOB_STARTED", event_group="JOB")
        _insert_trace_event(db, trace_id, 3, event_name="LLM_STARTED", event_group="LLM")
        _insert_trace_event(db, trace_id, 4, event_name="LLM_COMPLETED", event_group="LLM")
        _insert_trace_event(db, trace_id, 5, event_name="EXECUTION_STARTED", event_group="PIPELINE")
        _insert_trace_event(db, trace_id, 6, event_name="DB_WRITE_SUCCESS", event_group="DB")
        _insert_trace_event(db, trace_id, 7, event_name="JOB_COMPLETED", event_group="JOB")
        db.commit()

        report = validate_trace(trace_id, db=db)
        assert report["valid"]
        assert report["groups"] == {"JOB": 3, "LLM": 2, "PIPELINE": 1, "DB": 1}
    finally:
        db.close()


def test_validate_all_traces(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    db: Session = session_factory()
    try:
        _insert_trace_event(db, "all-trace-1", 1)
        _insert_trace_event(db, "all-trace-1", 2)
        _insert_trace_event(db, "all-trace-2", 1)
        db.commit()

        results = validate_all_traces(db=db)
        assert len(results) == 2
        trace_ids = {r["trace_id"] for r in results}
        assert trace_ids == {"all-trace-1", "all-trace-2"}
    finally:
        db.close()


def test_health_summary(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    db: Session = session_factory()
    try:
        _insert_trace_event(db, "health-trace-1", 1)
        _insert_trace_event(db, "health-trace-1", 2)
        _insert_trace_event(db, "health-trace-2", 1)
        db.commit()

        summary = observability_health_summary(db=db)
        assert summary["status"] == "ok"
        assert summary["total_traces"] == 2
        assert summary["total_events"] == 3
        assert summary["broken_traces"] == 0
    finally:
        db.close()
