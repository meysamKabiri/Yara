import tempfile
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth import hash_password
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.models.core import LEGACY_OWNER_ID, User

_trace_counters: dict[str, int] = {}


def _inline_next_trace_event_index(trace_id: str) -> int:
    _trace_counters[trace_id] = _trace_counters.get(trace_id, 0) + 1
    return _trace_counters[trace_id]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[AsyncClient, None]:
    db_file = tempfile.NamedTemporaryFile(prefix="yara-e2e-", suffix=".sqlite", delete=False)
    db_path = Path(db_file.name)
    db_file.close()

    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _register_next_trace_event_index(dbapi_connection, connection_record):
        if hasattr(dbapi_connection, "create_function"):
            dbapi_connection.create_function(
                "next_trace_event_index",
                1,
                _inline_next_trace_event_index,
            )

    _trace_counters.clear()
    testing_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=engine)

    with testing_session_local() as db:
        default_user = User(
            id=LEGACY_OWNER_ID,
            email="e2e-owner@yara.local",
            password_hash=hash_password("password123"),
        )
        db.add(default_user)
        db.commit()

    def override_get_db_session() -> Generator[Session, None, None]:
        db = testing_session_local()
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
    monkeypatch.setattr("app.db.session.SessionLocal", testing_session_local)
    monkeypatch.setattr("app.api.projects.get_queue", lambda: ImmediateQueue())
    monkeypatch.setattr("app.core.queue.get_redis_connection", lambda: FakeRedis())
    monkeypatch.setattr("app.core.job_event_bus.get_redis_connection", lambda: FakeRedis())

    app.state.testing_session_factory = testing_session_local
    app.state.testing_enqueued_jobs = {}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        try:
            yield test_client
        finally:
            app.dependency_overrides.clear()
            del app.state.testing_enqueued_jobs
            del app.state.testing_session_factory
            Base.metadata.drop_all(bind=engine)
            engine.dispose()
            db_path.unlink(missing_ok=True)


@pytest.fixture
def auth_headers() -> Callable[[str], dict[str, str]]:
    def _auth_headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    return _auth_headers


@pytest.fixture
def user_payload() -> Callable[[str], dict[str, str]]:
    def _user_payload(email: str) -> dict[str, str]:
        return {"email": email, "password": "password123"}

    return _user_payload


@pytest.fixture
async def signup(
    client: AsyncClient,
    auth_headers: Callable[[str], dict[str, str]],
    user_payload: Callable[[str], dict[str, str]],
) -> Callable[[str], Awaitable[dict[str, str]]]:
    async def _signup(email: str) -> dict[str, str]:
        response = await client.post("/auth/signup", json=user_payload(email))
        assert response.status_code == 201
        token = response.json()["access_token"]
        return {"token": token, "headers": auth_headers(token)}

    return _signup


@pytest.fixture
async def create_project(
    client: AsyncClient,
) -> Callable[[dict[str, str], str], Awaitable[dict]]:
    async def _create_project(headers: dict[str, str], name: str) -> dict:
        response = await client.post("/projects", json={"name": name}, headers=headers)
        assert response.status_code == 201
        return response.json()

    return _create_project
