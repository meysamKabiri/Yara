from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.jobs import natural_input_job
from app.models.core import (
    DeadLetterJob,
    FinancialDirection,
    HistoryChangeType,
    HistoryEntry,
    NaturalInputJob,
    NaturalInputJobStatus,
    Payment,
    PaymentType,
    PendingInterpretation,
    PendingInterpretationStatus,
    Project,
    ReconciliationEvent,
    ReconciliationEventStatus,
    ReconciliationStatus,
    Worker,
    WorkerState,
    WorkerStateRole,
    WorkerType,
)
from app.services.financial_reconciliation_service import (
    build_reconciliation_snapshot,
    reconcile_project,
    recover_stuck_confirming_interpretations,
)


def _project(client: TestClient, name: str = "reconciliation") -> dict:
    response = client.post("/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _seed_financial_state(client: TestClient, *, stored_balance: str = "100000000") -> tuple[int, int]:
    project = _project(client)
    with client.app.state.testing_session_factory() as db:
        worker = Worker(project_id=project["id"], name="میثم", type=WorkerType.CLIENT)
        db.add(worker)
        db.flush()
        state = WorkerState(
            project_id=project["id"],
            worker_id=worker.id,
            name=worker.name,
            role=WorkerStateRole.CLIENT,
            financial_balance=Decimal(stored_balance),
        )
        db.add(state)
        payment = Payment(
            project_id=project["id"],
            entity_id=worker.id,
            amount=Decimal("100000000"),
            type=PaymentType.BANK_TRANSFER,
            direction=FinancialDirection.INCOMING,
        )
        db.add(payment)
        db.flush()
        db.add(
            HistoryEntry(
                project_id=project["id"],
                worker_state_id=state.id,
                input_text="میثم ۱۰۰ میلیون واریز کرد",
                change_type=HistoryChangeType.PAYMENT,
                delta={"amount": "100000000", "balance": stored_balance},
            )
        )
        db.commit()
        return project["id"], worker.id


def test_reconciliation_accuracy_matches_source_tables(client: TestClient) -> None:
    project_id, worker_id = _seed_financial_state(client)

    with client.app.state.testing_session_factory() as db:
        snapshot = build_reconciliation_snapshot(db, project_id)

    assert snapshot["drift"] == {}
    assert snapshot["recomputed_balances"]["worker_balances"][str(worker_id)] == "100000000.00"
    assert snapshot["stored_balances"]["worker_balances"][str(worker_id)] == "100000000.00"


def test_reconciliation_detects_drift_and_marks_needs_review(client: TestClient) -> None:
    project_id, worker_id = _seed_financial_state(client, stored_balance="90000000")

    with client.app.state.testing_session_factory() as db:
        report = reconcile_project(db, project_id)
        project = db.get(Project, project_id)
        event = db.scalar(select(ReconciliationEvent).where(ReconciliationEvent.project_id == project_id))

    assert report["reconciliation_status"] == ReconciliationStatus.DRIFT_DETECTED.value
    assert report["drift"]["worker_balances"][0]["worker_id"] == worker_id
    assert project is not None and project.reconciliation_status == ReconciliationStatus.DRIFT_DETECTED
    assert event is not None and event.status == ReconciliationEventStatus.NEEDS_REVIEW
    assert event.snapshot["drift"]["worker_balances"][0]["difference"] == "10000000.00"


def test_dlq_records_failed_natural_input_job(client: TestClient, monkeypatch) -> None:
    session_factory = client.app.state.testing_session_factory
    monkeypatch.setattr(natural_input_job, "SessionLocal", session_factory)
    project = _project(client, "dlq")
    with session_factory() as db:
        db.add(
            NaturalInputJob(
                job_id="job-dlq",
                project_id=project["id"],
                status=NaturalInputJobStatus.PENDING,
            )
        )
        db.commit()

    def fail_process_input(db, project_id: int, text: str, request_cache=None):
        raise RuntimeError("pipeline failed hard")

    monkeypatch.setattr(natural_input_job.unified_pipeline, "process_input", fail_process_input)

    result = natural_input_job.process_natural_input_job("job-dlq", project["id"], "bad")

    assert result["status"] == "FAILED"
    with session_factory() as db:
        dlq = db.scalar(select(DeadLetterJob).where(DeadLetterJob.job_id == "job-dlq"))
    assert dlq is not None
    assert "pipeline failed hard" in dlq.error_trace
    response = client.get("/admin/dlq-jobs")
    assert response.status_code == 200
    assert response.json()[0]["job_id"] == "job-dlq"


def test_recover_stuck_confirming_interpretations(client: TestClient) -> None:
    project = _project(client, "confirming recovery")
    old_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=30)
    with client.app.state.testing_session_factory() as db:
        pending = PendingInterpretation(
            project_id=project["id"],
            raw_input_text="stuck",
            canonical_event_type="FINANCIAL_EVENT",
            semantic_action="PAYMENT",
            status=PendingInterpretationStatus.CONFIRMING,
        )
        db.add(pending)
        db.commit()
        pending.updated_at = old_time
        db.commit()
        pending_id = pending.id

        recovered = recover_stuck_confirming_interpretations(db, max_age_minutes=15)
        db.refresh(pending)

    assert recovered == 1
    assert pending.status == PendingInterpretationStatus.PENDING
    response = client.post("/admin/recover-confirming?max_age_minutes=15")
    assert response.status_code == 200
    assert response.json()["recovered"] == 0


def test_reconciliation_report_endpoint(client: TestClient) -> None:
    project_id, worker_id = _seed_financial_state(client)

    run_response = client.post(f"/admin/reconciliation-report/{project_id}/run")
    report_response = client.get(f"/admin/reconciliation-report/{project_id}")

    assert run_response.status_code == 200
    assert report_response.status_code == 200
    body = report_response.json()
    assert body["recomputed_balances"]["worker_balances"][str(worker_id)] == "100000000.00"
    assert body["last_reconciliation_timestamp"] is not None
