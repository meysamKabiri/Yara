from fastapi.testclient import TestClient
from tests.natural_input_helpers import natural_input_interpretation, natural_input_interpretations, submit_natural_input


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
    trace = client.get(f"/traces/{trace_id}").json()
    assert any(event["event"] == "DOMAIN_ROUTED" for event in trace["events"])


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

    events = client.get(f"/traces/{trace_id}").json()["events"]
    names = [event["event"] for event in events]
    assert "DOMAIN_ROUTED" in names
    assert "EXECUTION_STARTED" in names
    assert "EXECUTION_COMPLETED" in names
    assert "DB_WRITE_SUCCESS" in names
    completed = next(event for event in events if event["event"] == "EXECUTION_COMPLETED")
    assert completed["duration_ms"] is not None
