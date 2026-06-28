from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Lock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import projects as projects_api
from app.jobs import natural_input_job
from app.models.core import (
    FinancialDirection,
    HistoryEntry,
    NaturalInputJob,
    NaturalInputJobStatus,
    Payment,
    PaymentType,
    PendingInterpretation,
    PendingInterpretationStatus,
    RawEntry,
    Worker,
    WorkerState,
    WorkerStateRole,
    WorkerType,
)


def _project(client: TestClient, name: str = "concurrency") -> dict:
    response = client.post("/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _worker(client: TestClient, project_id: int, name: str = "میثم") -> dict:
    response = client.post(
        f"/projects/{project_id}/workers",
        json={"name": name, "type": "CLIENT"},
    )
    assert response.status_code == 201
    return response.json()


def _financial_structured(text: str, amount: int = 100000000) -> dict:
    return {
        "intent": "FINANCIAL",
        "action": "PAYMENT_IN",
        "entities": [{"name": "میثم", "kind": "PERSON", "project_role": "CLIENT"}],
        "financial": {
            "amount": amount,
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
        "reasoning_summary": "Incoming payment",
    }


def _pending_payment(
    client: TestClient,
    project_id: int,
    worker_id: int,
    *,
    text: str = "میثم ۱۰۰ میلیون واریز کرد",
    amount: int = 100000000,
) -> int:
    with client.app.state.testing_session_factory() as db:
        pending = PendingInterpretation(
            project_id=project_id,
            raw_input_text=text,
            canonical_event_type="FINANCIAL_EVENT",
            semantic_action="PAYMENT",
            suggested_entity_id=worker_id,
            matched_input_text=text,
            extracted_entities=[{"name": "میثم", "project_role": "CLIENT"}],
            extracted_amount=Decimal(str(amount)),
            payment_method=PaymentType.BANK_TRANSFER,
            financial_direction=FinancialDirection.INCOMING,
            description=text,
            confidence=0.9,
            structured_interpretation=_financial_structured(text, amount),
            status=PendingInterpretationStatus.PENDING,
        )
        db.add(pending)
        db.commit()
        return pending.id


def test_parallel_confirmation_only_one_succeeds(client: TestClient, monkeypatch) -> None:
    project = _project(client, "parallel confirm")
    worker = _worker(client, project["id"])
    pending_id = _pending_payment(client, project["id"], worker["id"])

    original_confirm = projects_api.ExecutionEngine.execute_confirmed_interpretation

    def slow_execute(self, confirmed, db, state):
        time.sleep(0.15)
        return original_confirm(self, confirmed, db, state)

    monkeypatch.setattr(
        "app.api.projects.ExecutionEngine.execute_confirmed_interpretation",
        slow_execute,
    )

    def confirm() -> int:
        response = client.post(
            f"/pending-interpretations/{pending_id}/confirm",
            json={"entity_id": worker["id"], "confirmed": True},
        )
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted([future.result() for future in [pool.submit(confirm), pool.submit(confirm)]])

    assert statuses == [200, 409]
    with client.app.state.testing_session_factory() as db:
        payments = list(db.scalars(select(Payment).where(Payment.project_id == project["id"])))
        histories = list(db.scalars(select(HistoryEntry).where(HistoryEntry.project_id == project["id"])))
        pending = db.get(PendingInterpretation, pending_id)
    assert len(payments) == 1
    assert len(histories) == 1
    assert pending is not None and pending.status == PendingInterpretationStatus.CONFIRMED


def test_parallel_financial_updates_keep_worker_state_balance_correct(client: TestClient) -> None:
    project = _project(client, "parallel balance")
    worker = _worker(client, project["id"])
    pending_ids = [
        _pending_payment(client, project["id"], worker["id"], text="پرداخت اول", amount=100000000),
        _pending_payment(client, project["id"], worker["id"], text="پرداخت دوم", amount=100000000),
    ]

    def confirm(pending_id: int) -> int:
        response = client.post(
            f"/pending-interpretations/{pending_id}/confirm",
            json={"entity_id": worker["id"], "confirmed": True},
        )
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted([future.result() for future in [pool.submit(confirm, pending_id) for pending_id in pending_ids]])

    assert statuses == [200, 200]
    with client.app.state.testing_session_factory() as db:
        payments = list(db.scalars(select(Payment).where(Payment.project_id == project["id"])))
        histories = list(db.scalars(select(HistoryEntry).where(HistoryEntry.project_id == project["id"])))
        state = db.scalar(
            select(WorkerState).where(
                WorkerState.project_id == project["id"],
                WorkerState.worker_id == worker["id"],
            )
        )
    assert len(payments) == 2
    assert len(histories) == 2
    assert state is not None
    assert state.financial_balance == Decimal("200000000.00")


def test_same_job_processed_in_parallel_executes_pipeline_once(client: TestClient, monkeypatch) -> None:
    session_factory = client.app.state.testing_session_factory
    monkeypatch.setattr(natural_input_job, "SessionLocal", session_factory)
    project = _project(client, "parallel worker")
    job_id = "same-job-parallel"
    with session_factory() as db:
        db.add(
            NaturalInputJob(
                job_id=job_id,
                project_id=project["id"],
                status=NaturalInputJobStatus.PENDING,
            )
        )
        db.add(RawEntry(project_id=project["id"], job_id=job_id, idempotency_key="parallel", text="job text"))
        db.commit()

    calls = 0
    calls_lock = Lock()

    def fake_process_input(db, project_id: int, text: str, request_cache=None):
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.15)
        interpretation = PendingInterpretation(
            project_id=project_id,
            raw_input_text=text,
            canonical_event_type="FINANCIAL_EVENT",
            semantic_action="PAYMENT",
            extracted_amount=Decimal("100000000"),
            payment_method=PaymentType.BANK_TRANSFER,
            financial_direction=FinancialDirection.INCOMING,
            confidence=0.9,
            structured_interpretation=_financial_structured(text),
            status=PendingInterpretationStatus.PENDING,
        )
        db.add(interpretation)
        db.commit()
        db.refresh(interpretation)
        return [interpretation]

    monkeypatch.setattr(natural_input_job.unified_pipeline, "process_input", fake_process_input)

    def run_job() -> str:
        result = natural_input_job.process_natural_input_job(job_id, project["id"], "job text")
        return result["status"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted([future.result() for future in [pool.submit(run_job), pool.submit(run_job)]])

    assert statuses in (["DONE", "RUNNING"], ["DONE", "DONE"])
    assert calls == 1
    with session_factory() as db:
        interpretations = list(db.scalars(select(PendingInterpretation).where(PendingInterpretation.project_id == project["id"])))
    assert len(interpretations) == 1


def test_financial_confirmation_rollback_leaves_no_partial_state(client: TestClient, monkeypatch) -> None:
    project = _project(client, "rollback")
    worker = _worker(client, project["id"])
    pending_id = _pending_payment(client, project["id"], worker["id"])

    def fail_history(*args, **kwargs):
        raise RuntimeError("forced history failure")

    monkeypatch.setattr("app.api.projects._add_history", fail_history)

    with pytest.raises(RuntimeError):
        client.post(
            f"/pending-interpretations/{pending_id}/confirm",
            json={"entity_id": worker["id"], "confirmed": True},
        )

    with client.app.state.testing_session_factory() as db:
        payments = list(db.scalars(select(Payment).where(Payment.project_id == project["id"])))
        histories = list(db.scalars(select(HistoryEntry).where(HistoryEntry.project_id == project["id"])))
        states = list(db.scalars(select(WorkerState).where(WorkerState.project_id == project["id"])))
        pending = db.get(PendingInterpretation, pending_id)
    assert payments == []
    assert histories == []
    assert states == []
    assert pending is not None and pending.status == PendingInterpretationStatus.PENDING
