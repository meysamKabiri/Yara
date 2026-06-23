from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import llm_cache as llm_cache_module
from app.db.base import Base
from app.db.session import get_db_session
from app.jobs import natural_input_job
from app.main import app


@pytest.fixture(autouse=True)
def _mock_llm_v2_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure LLM v2 interpreter falls back to legacy for all tests by default.

    Tests that want to test LLM v2 behavior should explicitly mock
    LLMv2Interpreter.interpret with their expected output.
    """
    llm_cache_module._LLM_CACHE.clear()
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, raw_text, project_id: {
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
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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
        def enqueue(self, func: str, *, args: tuple, job_id: str) -> None:
            previous_session_local = natural_input_job.SessionLocal
            natural_input_job.SessionLocal = TestingSessionLocal
            try:
                natural_input_job.process_natural_input_job(*args)
            finally:
                natural_input_job.SessionLocal = previous_session_local

    app.dependency_overrides[get_db_session] = override_get_db_session
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("app.api.projects.get_queue", lambda: ImmediateQueue())
    with TestClient(app) as test_client:
        test_client.app.state.testing_session_factory = TestingSessionLocal
        yield test_client
        del test_client.app.state.testing_session_factory
    monkeypatch.undo()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
