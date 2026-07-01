from fastapi.testclient import TestClient

from app.core.event_tracker import track_event
from app.models.core import ReconciliationEvent, ReconciliationEventStatus


def test_trace_debug_endpoints_return_chain_and_recent_list(client: TestClient) -> None:
    project = client.post("/projects", json={"name": "trace api"}).json()
    trace_id = "trace-api-debug"

    with client.app.state.testing_session_factory() as db:
        track_event(
            db=db,
            trace_id=trace_id,
            event_name="DOMAIN_ROUTED",
            payload={
                "project_id": project["id"],
                "domain": "FINANCIAL",
                "stage": "ROUTER",
                "input_snapshot": "وحید 500 میلیون ریخت به حساب",
                "output_snapshot": {"domain": "FINANCIAL", "confidence": 0.95},
            },
        )

    chain = client.get(f"/traces/{trace_id}")
    recent = client.get(f"/traces?project_id={project['id']}")

    assert chain.status_code == 200
    event = chain.json()["events"][0]
    assert event["event_type"] == "DOMAIN_ROUTED"
    assert event["domain"] == "FINANCIAL"
    assert event["stage"] == "ROUTER"
    assert recent.status_code == 200
    assert trace_id in {trace["trace_id"] for trace in recent.json()["traces"]}


def test_trace_anomalies_include_reconciliation_drift(client: TestClient) -> None:
    project = client.post("/projects", json={"name": "trace anomalies"}).json()
    with client.app.state.testing_session_factory() as db:
        db.add(
            ReconciliationEvent(
                project_id=project["id"],
                status=ReconciliationEventStatus.NEEDS_REVIEW,
                drift_detected=True,
                snapshot={"drift": {"project_totals": [{"field": "project_balance"}]}},
            )
        )
        db.commit()

    response = client.get("/traces/anomalies")

    assert response.status_code == 200
    drift = response.json()["reconciliation_drift_flags"]
    assert drift[0]["project_id"] == project["id"]
