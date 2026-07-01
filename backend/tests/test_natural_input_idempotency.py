from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.jobs.natural_input_job import process_natural_input_job
from app.models.core import (
    FinancialDirection,
    NaturalInputJob,
    NaturalInputJobStatus,
    Payment,
    PaymentType,
    PendingInterpretation,
    PendingInterpretationStatus,
    RawEntry,
    Worker,
    WorkerState,
    WorkerType,
)
from tests.natural_input_helpers import run_enqueued_natural_input_job, submit_natural_input


def _project(client: TestClient, name: str = "idempotency") -> dict:
    response = client.post("/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _submit_with_key(client: TestClient, project_id: int, text: str, key: str) -> dict:
    response = client.post(
        f"/projects/{project_id}/natural-input",
        json={"text": text, "idempotency_key": key},
    )
    assert response.status_code == 202
    return response.json()


def _fake_payment_pipeline(db, project_id: int, text: str, request_cache=None):
    interpretation = PendingInterpretation(
        project_id=project_id,
        raw_input_text=text,
        canonical_event_type="FINANCIAL_EVENT",
        semantic_action="PAYMENT",
        suggested_entity_id=None,
        matched_input_text=text,
        extracted_entities=[{"name": "میثم", "project_role": "CLIENT"}],
        extracted_amount="100000000",
        extracted_quantity=None,
        payment_method=PaymentType.BANK_TRANSFER,
        financial_direction=FinancialDirection.INCOMING,
        due_date=None,
        description=text,
        confidence=0.9,
        structured_interpretation={
            "intent": "FINANCIAL",
            "action": "PAYMENT_IN",
            "entities": [{"name": "میثم", "kind": "PERSON", "project_role": "CLIENT"}],
            "financial": {
                "amount": 100000000,
                "direction": "IN",
                "payment_method": "BANK_TRANSFER",
                "due_date_text": None,
            },
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "matched_text": text,
            "confidence": 0.9,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "Incoming client payment",
        },
        status=PendingInterpretationStatus.PENDING,
    )
    db.add(interpretation)
    db.commit()
    db.refresh(interpretation)
    return [interpretation]


def test_duplicate_natural_input_submission_reuses_existing_job_and_raw_entry(
    client: TestClient,
) -> None:
    project = _project(client, "duplicate submit")

    first = _submit_with_key(client, project["id"], "میثم ۱۰۰ میلیون واریز کرد", "same-submit-key")
    second = _submit_with_key(client, project["id"], "میثم ۱۰۰ میلیون واریز کرد", "same-submit-key")

    assert second["job_id"] == first["job_id"]
    with client.app.state.testing_session_factory() as db:
        raw_entries = list(db.scalars(select(RawEntry).where(RawEntry.project_id == project["id"])))
        jobs = list(db.scalars(select(NaturalInputJob).where(NaturalInputJob.project_id == project["id"])))
    assert len(raw_entries) == 1
    assert raw_entries[0].idempotency_key == "same-submit-key"
    assert raw_entries[0].job_id == first["job_id"]
    assert len(jobs) == 1


def test_same_text_with_different_idempotency_key_is_allowed(client: TestClient) -> None:
    project = _project(client, "different keys")

    first = _submit_with_key(client, project["id"], "میثم ۱۰۰ میلیون واریز کرد", "key-a")
    second = _submit_with_key(client, project["id"], "میثم ۱۰۰ میلیون واریز کرد", "key-b")

    assert second["job_id"] != first["job_id"]
    with client.app.state.testing_session_factory() as db:
        raw_entries = list(db.scalars(select(RawEntry).where(RawEntry.project_id == project["id"])))
    assert len(raw_entries) == 2
    assert {entry.idempotency_key for entry in raw_entries} == {"key-a", "key-b"}


def test_worker_retry_does_not_duplicate_interpretations(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("app.jobs.natural_input_job.unified_pipeline.process_input", _fake_payment_pipeline)
    monkeypatch.setattr("app.jobs.natural_input_job.SessionLocal", client.app.state.testing_session_factory)
    project = _project(client, "worker retry")
    text = "میثم ۱۰۰ میلیون واریز کرد"
    submitted = submit_natural_input(
        client,
        project["id"],
        text,
        headers={"X-Trace-Id": "retry-idempotency"},
    )
    run_enqueued_natural_input_job(client, submitted["job_id"])
    with client.app.state.testing_session_factory() as db:
        job = db.scalars(
            select(NaturalInputJob).where(NaturalInputJob.job_id == submitted["job_id"])
        ).one()
        job.status = NaturalInputJobStatus.RUNNING
        job.updated_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=30)
        job.error = None
        db.commit()

    retry = process_natural_input_job(submitted["job_id"], project["id"], text)

    assert retry["status"] == "DONE"
    with client.app.state.testing_session_factory() as db:
        interpretations = list(
            db.scalars(select(PendingInterpretation).where(PendingInterpretation.project_id == project["id"]))
        )
        raw_entries = list(db.scalars(select(RawEntry).where(RawEntry.project_id == project["id"])))
    assert len(interpretations) == 1
    assert len(raw_entries) == 1


def test_duplicate_confirmation_returns_conflict_without_duplicate_financial_writes(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.jobs.natural_input_job.unified_pipeline.process_input", _fake_payment_pipeline)
    project = _project(client, "duplicate confirm")
    worker = client.post(
        f"/projects/{project['id']}/workers",
        json={"name": "میثم", "type": "CLIENT"},
    ).json()
    submitted = submit_natural_input(client, project["id"], "میثم ۱۰۰ میلیون واریز کرد")
    run_enqueued_natural_input_job(client, submitted["job_id"])
    job = client.get(f"/natural-input-jobs/{submitted['job_id']}").json()
    pending = job["result"]["interpretations"][0]

    first = client.post(
        f"/pending-interpretations/{pending['id']}/confirm",
        json={"entity_id": worker["id"], "confirmed": True},
    )
    second = client.post(
        f"/pending-interpretations/{pending['id']}/confirm",
        json={"entity_id": worker["id"], "confirmed": True},
    )

    assert first.status_code == 200
    assert second.status_code == 409
    with client.app.state.testing_session_factory() as db:
        payments = list(db.scalars(select(Payment).where(Payment.project_id == project["id"])))
        states = list(db.scalars(select(WorkerState).where(WorkerState.project_id == project["id"])))
        client_worker = db.get(Worker, worker["id"])
    assert len(payments) == 1
    assert payments[0].direction == FinancialDirection.INCOMING
    assert len(states) == 1
    assert str(states[0].financial_balance) == "100000000.00"
    assert client_worker is not None and client_worker.type == WorkerType.CLIENT
