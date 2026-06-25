from collections.abc import Generator
from pathlib import Path
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core import llm_cache as llm_cache_module
from app.db.base import Base
from app.db.session import get_db_session
from app.jobs import natural_input_job
from app.main import app

# Module-level dict-backed counter for SQLite next_trace_event_index mock.
# SQLite UDFs cannot execute SQL on their own connection, so we use a plain dict.
_trace_counters: dict[str, int] = {}
_next_trace_event_index_inline_called = False


def _inline_next_trace_event_index(trace_id: str) -> int:
    """Increment and return the next event index for a trace_id.

    Mirrors the PostgreSQL function next_trace_event_index() using a plain dict.
    This function is called directly (not as a SQLite UDF) to avoid re-entrancy
    issues with SQLite connections.
    """
    _trace_counters[trace_id] = _trace_counters.get(trace_id, 0) + 1
    return _trace_counters[trace_id]


@pytest.fixture(autouse=True)
def _mock_llm_v2_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure LLM v2 interpreter falls back to legacy for all tests by default.

    Tests that want to test LLM v2 behavior should explicitly mock
    LLMv2Interpreter.interpret with their expected output.
    """
    llm_cache_module._LLM_CACHE.clear()
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, raw_text, project_id, db=None: {
            "intent": "NOTE",
            "action": "NOTE",
            "entities": [],
            "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": raw_text},
            "confidence": 0.0,
            "ambiguity": True,
            "missing_fields": [],
            "reasoning_summary": "LLM v2 mocked fallback for testing",
            "_llm_v2_failed": True,
        },
    )


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    db_file = tempfile.NamedTemporaryFile(prefix="yara-test-", suffix=".sqlite", delete=False)
    db_path = Path(db_file.name)
    db_file.close()
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _register_next_trace_event_index(dbapi_connection, connection_record):
        if not hasattr(dbapi_connection, "create_function"):
            return

        def _impl(trace_id: str) -> int:
            global _next_trace_event_index_inline_called
            _next_trace_event_index_inline_called = True
            return _inline_next_trace_event_index(trace_id)

        dbapi_connection.create_function("next_trace_event_index", 1, _impl)

    _trace_counters.clear()
    TestingSessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=engine)

    def override_get_db_session() -> Generator[Session, None, None]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    class ImmediateQueue:
        def enqueue(
            self,
            func: str,
            *,
            args: tuple | None = None,
            kwargs: dict | None = None,
            job_id: str | None = None,
            meta: dict | None = None,
            **extra,
        ) -> None:
            app.state.testing_enqueued_jobs[job_id or ""] = {
                "func": func,
                "args": args or (),
                "kwargs": kwargs or {},
                "meta": meta or {},
                "extra": extra,
            }

    class FakeRedis:
        def ping(self) -> bool:
            return True

        def publish(self, channel: str, payload: str) -> int:
            return 0

        def pubsub(self, ignore_subscribe_messages: bool = True):
            class FakePubSub:
                def subscribe(self, channel: str) -> None:
                    return None

                def get_message(self, timeout: float = 1.0):
                    return None

                def unsubscribe(self, channel: str) -> None:
                    return None

                def close(self) -> None:
                    return None

            return FakePubSub()

    app.dependency_overrides[get_db_session] = override_get_db_session
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("app.db.session.SessionLocal", TestingSessionLocal)
    monkeypatch.setattr("app.api.projects.get_queue", lambda: ImmediateQueue())
    monkeypatch.setattr("app.core.queue.get_redis_connection", lambda: FakeRedis())
    monkeypatch.setattr("app.core.job_event_bus.get_redis_connection", lambda: FakeRedis())
    monkeypatch.setattr("app.api.health._check_database", lambda: "ok")
    monkeypatch.setattr("app.api.health._check_redis", lambda: "unavailable")
    monkeypatch.setattr("app.api.health._check_ollama", lambda: "unavailable")
    test_client = TestClient(app)
    try:
        test_client.app.state.testing_session_factory = TestingSessionLocal
        test_client.app.state.testing_enqueued_jobs = {}
        yield test_client
        del test_client.app.state.testing_enqueued_jobs
        del test_client.app.state.testing_session_factory
    finally:
        test_client.close()
    monkeypatch.undo()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    db_path.unlink(missing_ok=True)


@pytest.fixture
def db_session(client: TestClient) -> Generator[Session, None, None]:
    """Provide an isolated helper session for tests that need direct DB access.

    The test database is already per-test. This fixture avoids fragile nested
    savepoint patterns by using one ordinary session and rolling back anything
    left open by the test helper.
    """
    db = client.app.state.testing_session_factory()
    try:
        yield db
    finally:
        if db.in_transaction():
            db.rollback()
        db.close()
