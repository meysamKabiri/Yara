import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.event_tracker import track_event as _db_track_event, get_trace_events
from app.db.base import Base


pytestmark = [
    pytest.mark.skipif(
        True,
        reason="Concurrency tests require PostgreSQL with next_trace_event_index() function",
    ),
]


@pytest.fixture
def pg_session_factory() -> sessionmaker:
    from app.core.config import settings

    engine = create_engine(
        settings.database_url,
        poolclass=NullPool,
        pool_pre_ping=True,
    )
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_event_index_monotonic_under_concurrent_writes(pg_session_factory: sessionmaker) -> None:
    trace_id = "concurrent-monotonic"
    num_threads = 10
    events_per_thread = 20

    def _write_events(thread_id: int) -> list[dict]:
        session: Session = pg_session_factory()
        try:
            results = []
            for i in range(events_per_thread):
                event = _db_track_event(
                    db=session,
                    trace_id=trace_id,
                    event_name=f"CONCURRENT_TEST_{thread_id}_{i}",
                    payload={"thread": thread_id, "seq": i},
                )
                results.append(event)
            return results
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(_write_events, t) for t in range(num_threads)]
        all_events = []
        for f in as_completed(futures):
            all_events.extend(f.result())

    indices = sorted(e["event_index"] for e in all_events)
    expected_count = num_threads * events_per_thread

    assert len(indices) == expected_count, f"Expected {expected_count} events, got {len(indices)}"
    assert indices == list(range(1, expected_count + 1)), f"Indices not monotonic: {indices[:5]}...{indices[-5:]}"

    db_events = get_trace_events(trace_id)
    assert len(db_events) == expected_count
    db_indices = sorted(e["event_index"] for e in db_events)
    assert db_indices == indices


def test_multiple_trace_ids_no_crosstalk(pg_session_factory: sessionmaker) -> None:
    num_traces = 5
    events_per_trace = 10

    def _write_for_trace(trace_id: str) -> list[int]:
        session: Session = pg_session_factory()
        try:
            indices = []
            for i in range(events_per_trace):
                event = _db_track_event(
                    db=session,
                    trace_id=trace_id,
                    event_name=f"CROSSTALK_TEST_{i}",
                    payload={"seq": i},
                )
                indices.append(event["event_index"])
            return indices
        finally:
            session.close()

    trace_ids = [f"crosstalk-trace-{i}" for i in range(num_traces)]
    with ThreadPoolExecutor(max_workers=num_traces) as executor:
        futures = {executor.submit(_write_for_trace, tid): tid for tid in trace_ids}
        trace_results: dict[str, list[int]] = {}
        for f in as_completed(futures):
            trace_results[futures[f]] = f.result()

    for trace_id, indices in trace_results.items():
        assert indices == list(range(1, events_per_trace + 1)), (
            f"Trace {trace_id}: expected 1..{events_per_trace}, got {indices}"
        )
        db_events = get_trace_events(trace_id)
        assert len(db_events) == events_per_trace


def test_no_duplicate_indices_under_high_contention(pg_session_factory: sessionmaker) -> None:
    trace_id = "concurrent-high-contention"
    num_threads = 20
    calls_per_thread = 5
    barrier = threading.Barrier(num_threads)

    def _contend(thread_id: int) -> list[int]:
        session: Session = pg_session_factory()
        try:
            barrier.wait(timeout=10)
            indices = []
            for i in range(calls_per_thread):
                event = _db_track_event(
                    db=session,
                    trace_id=trace_id,
                    event_name=f"HIGH_CONTENTION_{thread_id}_{i}",
                    payload={},
                )
                indices.append(event["event_index"])
            return indices
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(_contend, t) for t in range(num_threads)]
        all_indices = []
        for f in as_completed(futures):
            all_indices.extend(f.result())

    expected_total = num_threads * calls_per_thread
    sorted_indices = sorted(all_indices)

    assert len(sorted_indices) == expected_total, (
        f"Expected {expected_total} indices, got {len(sorted_indices)}"
    )
    assert len(set(sorted_indices)) == expected_total, (
        f"Duplicate indices: total={len(sorted_indices)}, unique={len(set(sorted_indices))}"
    )
    assert sorted_indices == list(range(1, expected_total + 1))


def test_counter_table_consistency(pg_session_factory: sessionmaker) -> None:
    from app.models.core import TraceEventCounter

    trace_id = "counter-consistency-test"
    num_events = 25

    session: Session = pg_session_factory()
    try:
        for i in range(num_events):
            _db_track_event(
                db=session,
                trace_id=trace_id,
                event_name=f"COUNTER_TEST_{i}",
                payload={},
            )

        counter = session.get(TraceEventCounter, trace_id)
        assert counter is not None, "Counter row not found"
        assert counter.counter == num_events, (
            f"Counter value {counter.counter} != {num_events} events"
        )

        event_count = session.query(TraceEvent).filter(
            TraceEvent.trace_id == trace_id
        ).count()
        assert event_count == num_events
        assert counter.counter == event_count
    finally:
        session.close()
