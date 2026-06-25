import pytest
from fastapi.testclient import TestClient

from app.core.observability_validator import validate_trace
from tests.natural_input_helpers import natural_input_result


pytestmark = [
    pytest.mark.skipif(
        True,
        reason="E2E tests require PostgreSQL with next_trace_event_index() function",
    ),
]


def _make_result(client: TestClient, project_id: int, text: str, trace_id: str) -> dict:
    return natural_input_result(
        client,
        project_id,
        text,
        headers={"X-Trace-Id": trace_id},
    )


def test_single_job_produces_valid_trace(client: TestClient) -> None:
    project = client.post("/projects", json={"name": "e2e-single"}).json()
    _make_result(client, project["id"], "یک کارگر جدید به پروژه اضافه کن", trace_id="e2e-single-trace")

    report = validate_trace("e2e-single-trace")
    assert report["valid"], f"Trace validation failed: {report['errors']}"
    assert report["event_count"] >= 3, f"Expected >=3 events, got {report['event_count']}"
    assert report["groups"].get("JOB", 0) >= 1
    assert report["groups"].get("DB", 0) >= 1


def test_financial_job_trace(client: TestClient) -> None:
    project = client.post("/projects", json={"name": "e2e-financial"}).json()
    _make_result(client, project["id"], "۲۰۰ میلیون تومان پرداخت کردم", trace_id="e2e-fin-trace")

    report = validate_trace("e2e-fin-trace")
    assert report["valid"], f"Trace validation failed: {report['errors']}"
    assert report["event_count"] >= 3
    event_names = set(report["event_name_counts"])
    assert "JOB_CREATED" in event_names
    assert "JOB_STARTED" in event_names


def test_trace_has_required_pipeline_stages(client: TestClient) -> None:
    project = client.post("/projects", json={"name": "e2e-stages"}).json()
    _make_result(client, project["id"], "علی به عنوان فروشنده اضافه شد", trace_id="e2e-stage-trace")

    report = validate_trace("e2e-stage-trace")
    assert report["valid"], f"Trace validation failed: {report['errors']}"
    event_names = set(report["event_name_counts"])
    assert any(
        stage in event_names
        for stage in ("JOB_CREATED",)
    )
    assert any(
        stage in event_names
        for stage in ("JOB_COMPLETED", "JOB_FAILED")
    ), "Expected terminal JOB event"
    assert report["duplicates"] == [], f"Duplicate event indices: {report['duplicates']}"
    assert report["gaps"] == [], f"Event index gaps: {report['gaps']}"


def test_multi_event_split_trace(client: TestClient) -> None:
    project = client.post("/projects", json={"name": "e2e-split"}).json()
    _make_result(
        client,
        project["id"],
        "میثم کبیری کارفرما\nعلی احمدی کارگر\n۲۰۰ میلیون پرداخت کردم",
        trace_id="e2e-split-trace",
    )

    report = validate_trace("e2e-split-trace")
    assert report["valid"], f"Trace validation failed: {report['errors']}"
    assert report["groups"].get("PIPELINE", 0) >= 1
    assert report["groups"].get("JOB", 0) >= 1


def test_ten_concurrent_jobs_produce_valid_traces(client: TestClient) -> None:
    project = client.post("/projects", json={"name": "e2e-concurrent"}).json()
    texts = [
        "یک کارگر جدید به پروژه اضافه کن",
        "۲۰۰ میلیون پرداخت کردم",
        "علی فروشنده است",
        "شماره تماس ۰۹۱۲۳۴۵۶۷۸۹",
        "۵۰ متر کار انجام شد",
    ] * 2

    trace_ids = []
    for i, text in enumerate(texts):
        trace_id = f"e2e-concurrent-{i:03d}"
        trace_ids.append(trace_id)
        _make_result(client, project["id"], text, trace_id=trace_id)

    for trace_id in trace_ids:
        report = validate_trace(trace_id)
        assert report["valid"], f"Trace {trace_id} failed: {report['errors']}"
        assert report["event_count"] > 0, f"Trace {trace_id}: no events"
