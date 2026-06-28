from fastapi.testclient import TestClient

from app.core.event_tracker import get_trace_events
from tests.natural_input_helpers import (
    natural_input_interpretation,
    run_enqueued_natural_input_job,
    submit_natural_input,
)


def _get_events(client: TestClient, trace_id: str) -> list[dict]:
    """Fetch trace events using a test DB session.

    The /traces/{trace_id} endpoint does not accept a db parameter, so it
    opens its own SessionLocal (production database) which is invisible to
    the test's in-memory SQLite.  We query directly instead.
    """
    factory = client.app.state.testing_session_factory
    db = factory()
    try:
        return get_trace_events(trace_id, db=db)
    finally:
        db.close()


def test_every_response_includes_trace_id_header(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["X-Trace-Id"]


def test_domain_route_trace_event_is_recorded(client: TestClient) -> None:
    trace_id = "trace-domain-test"
    project = client.post("/projects", json={"name": "trace"}, headers={"X-Trace-Id": trace_id}).json()

    job = submit_natural_input(
        client,
        project["id"],
        "میثم کبیری کارفرمای پروژه است",
        headers={"X-Trace-Id": trace_id},
    )
    assert job["trace_id"] == trace_id
    run_enqueued_natural_input_job(client, job["job_id"])
    events = _get_events(client, trace_id)
    names = [e["event_name"] for e in events]
    assert "DOMAIN_ROUTER_START" in names, f"Got events: {names}"


def test_financial_confirmation_trace_records_resolution_execution_and_db_write(
    client: TestClient,
    monkeypatch,
) -> None:
    trace_id = "trace-financial-test"
    project = client.post("/projects", json={"name": "trace financial"}, headers={"X-Trace-Id": trace_id}).json()
    worker = client.post(
        f"/projects/{project['id']}/workers",
        json={"name": "علی", "type": "CLIENT"},
        headers={"X-Trace-Id": trace_id},
    ).json()
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {"intent": "PAYMENT", "entity": "علی", "confidence": 0.9},
    )
    pending = natural_input_interpretation(
        client,
        project["id"],
        "از علی 50 میلیون گرفتم بابت پروژه",
        headers={"X-Trace-Id": trace_id},
    )

    client.post(
        f"/pending-interpretations/{pending['id']}/confirm",
        json={"entity_id": worker["id"], "confirmed": True},
        headers={"X-Trace-Id": trace_id},
    )

    events = _get_events(client, trace_id)
    names = [event["event_name"] for event in events]
    assert "DOMAIN_ROUTED" in names
    assert "EXECUTION_STARTED" in names
    assert "EXECUTION_COMPLETED" in names
    assert "DB_WRITE_SUCCESS" in names
    completed = next(event for event in events if event["event_name"] == "EXECUTION_COMPLETED")
    assert completed["duration_ms"] is not None
