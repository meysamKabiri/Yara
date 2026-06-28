from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.core import (
    DeadLetterJob,
    FinancialDirection,
    HistoryChangeType,
    HistoryEntry,
    Invoice,
    InvoiceStatus,
    NaturalInputJob,
    NaturalInputJobStatus,
    Payment,
    PendingInterpretation,
    PendingInterpretationStatus,
    Project,
    ReconciliationEvent,
    ReconciliationEventStatus,
    ReconciliationStatus,
    WorkerState,
    WorkerStateRole,
    WorkLog,
)


def reconcile_project(db: Session, project_id: int) -> dict[str, Any]:
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("Project not found")

    snapshot = build_reconciliation_snapshot(db, project_id)
    drift_detected = bool(snapshot["drift"])
    project.reconciliation_status = (
        ReconciliationStatus.DRIFT_DETECTED if drift_detected else ReconciliationStatus.OK
    )
    project.last_reconciled_at = datetime.now(UTC).replace(tzinfo=None)
    event = ReconciliationEvent(
        project_id=project_id,
        status=(
            ReconciliationEventStatus.NEEDS_REVIEW
            if drift_detected
            else ReconciliationEventStatus.OK
        ),
        drift_detected=drift_detected,
        snapshot=snapshot,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return {
        **snapshot,
        "reconciliation_event_id": event.id,
        "reconciliation_status": project.reconciliation_status.value,
        "last_reconciliation_timestamp": project.last_reconciled_at.isoformat()
        if project.last_reconciled_at
        else None,
    }


def build_reconciliation_snapshot(db: Session, project_id: int) -> dict[str, Any]:
    expected_worker_balances = _expected_worker_balances(db, project_id)
    stored_worker_balances = _stored_worker_balances(db, project_id)
    worker_ids = sorted(set(expected_worker_balances) | set(stored_worker_balances))

    worker_drift = []
    for worker_id in worker_ids:
        expected = expected_worker_balances.get(worker_id, Decimal("0"))
        stored = stored_worker_balances.get(worker_id, Decimal("0"))
        if expected != stored:
            worker_drift.append(
                {
                    "worker_id": worker_id,
                    "stored_balance": str(stored),
                    "expected_balance": str(expected),
                    "difference": str(expected - stored),
                }
            )

    expected_project_balance = _sum_payments(db, project_id, FinancialDirection.INCOMING) - _sum_real_outgoing_payments(db, project_id)
    expected_payables = _open_invoice_total(db, project_id) + _unpaid_worker_remaining(db, project_id)
    stored_project_balance = _stored_project_balance(db, project_id)

    project_drift = []
    if expected_project_balance != stored_project_balance:
        project_drift.append(
            {
                "field": "project_balance",
                "stored": str(stored_project_balance),
                "expected": str(expected_project_balance),
                "difference": str(expected_project_balance - stored_project_balance),
            }
        )

    payment_history_drift = _payment_history_drift(db, project_id)
    drift = {
        "worker_balances": worker_drift,
        "project_totals": project_drift,
        "payment_history": payment_history_drift,
    }
    drift = {key: value for key, value in drift.items() if value}

    return {
        "project_id": project_id,
        "stored_balances": {
            "project_balance": str(stored_project_balance),
            "worker_balances": {str(key): str(value) for key, value in stored_worker_balances.items()},
        },
        "recomputed_balances": {
            "project_balance": str(expected_project_balance),
            "worker_balances": {str(key): str(value) for key, value in expected_worker_balances.items()},
            "payables": str(expected_payables),
        },
        "drift": drift,
        "checked_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
    }


def latest_reconciliation_report(db: Session, project_id: int) -> dict[str, Any]:
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("Project not found")
    snapshot = build_reconciliation_snapshot(db, project_id)
    latest_event = db.scalar(
        select(ReconciliationEvent)
        .where(ReconciliationEvent.project_id == project_id)
        .order_by(ReconciliationEvent.created_at.desc(), ReconciliationEvent.id.desc())
    )
    return {
        **snapshot,
        "reconciliation_status": project.reconciliation_status.value,
        "last_reconciliation_timestamp": project.last_reconciled_at.isoformat()
        if project.last_reconciled_at
        else None,
        "last_event_id": latest_event.id if latest_event else None,
    }


def record_dead_letter_job(
    db: Session,
    *,
    job_id: str,
    project_id: int | None,
    payload: dict[str, Any] | None,
    error_trace: str,
    retry_count: int = 0,
    source: str = "natural_input",
) -> DeadLetterJob:
    existing = db.scalar(
        select(DeadLetterJob).where(
            DeadLetterJob.job_id == job_id,
            DeadLetterJob.source == source,
        )
    )
    if existing is not None:
        return existing
    dead = DeadLetterJob(
        job_id=job_id,
        project_id=project_id,
        payload=payload,
        error_trace=error_trace,
        retry_count=retry_count,
        source=source,
    )
    db.add(dead)
    db.commit()
    db.refresh(dead)
    return dead


def recover_stuck_confirming_interpretations(
    db: Session,
    *,
    max_age_minutes: int = 15,
    project_ids: set[int] | None = None,
) -> int:
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=max_age_minutes)
    statement = select(PendingInterpretation).where(
        PendingInterpretation.status == PendingInterpretationStatus.CONFIRMING,
        PendingInterpretation.updated_at < cutoff,
    )
    if project_ids is not None:
        if not project_ids:
            return 0
        statement = statement.where(PendingInterpretation.project_id.in_(project_ids))
    stuck = list(
        db.scalars(
            statement
        )
    )
    recovered = 0
    for interpretation in stuck:
        has_financial_record = db.scalar(
            select(Payment.id).where(Payment.source_pending_interpretation_id == interpretation.id)
        ) or db.scalar(
            select(Invoice.id).where(Invoice.source_pending_interpretation_id == interpretation.id)
        ) or db.scalar(
            select(WorkLog.id).where(WorkLog.source_pending_interpretation_id == interpretation.id)
        )
        interpretation.status = (
            PendingInterpretationStatus.CONFIRMED
            if has_financial_record
            else PendingInterpretationStatus.PENDING
        )
        recovered += 1
    if recovered:
        db.commit()
    return recovered


def safety_metrics(db: Session, project_ids: set[int] | None = None) -> dict[str, int]:
    if project_ids is not None and not project_ids:
        return {
            "total_processed_financial_events": 0,
            "reconciliation_drift_count": 0,
            "dlq_job_count": 0,
            "confirming_recovery_count": 0,
            "duplicate_prevention_count": 0,
        }
    payment_count = select(func.count(Payment.id)).where(Payment.is_voided == False)
    drift_count = select(func.count(ReconciliationEvent.id)).where(ReconciliationEvent.drift_detected == True)
    dlq_count = select(func.count(DeadLetterJob.id))
    confirming_count = select(func.count(PendingInterpretation.id)).where(
        PendingInterpretation.status == PendingInterpretationStatus.CONFIRMING
    )
    if project_ids is not None:
        payment_count = payment_count.where(Payment.project_id.in_(project_ids))
        drift_count = drift_count.where(ReconciliationEvent.project_id.in_(project_ids))
        dlq_count = dlq_count.where(DeadLetterJob.project_id.in_(project_ids))
        confirming_count = confirming_count.where(PendingInterpretation.project_id.in_(project_ids))
    return {
        "total_processed_financial_events": int(
            db.scalar(payment_count) or 0
        ),
        "reconciliation_drift_count": int(
            db.scalar(drift_count) or 0
        ),
        "dlq_job_count": int(db.scalar(dlq_count) or 0),
        "confirming_recovery_count": int(
            db.scalar(confirming_count)
            or 0
        ),
        "duplicate_prevention_count": 0,
    }


def _expected_worker_balances(db: Session, project_id: int) -> dict[int, Decimal]:
    balances: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    roles = {
        state.worker_id: state.role
        for state in db.scalars(select(WorkerState).where(WorkerState.project_id == project_id))
    }

    for invoice in db.scalars(select(Invoice).where(Invoice.project_id == project_id, Invoice.is_voided == False)):
        balances[invoice.vendor_id] += Decimal(invoice.total_amount or 0)

    for payment in db.scalars(select(Payment).where(Payment.project_id == project_id, Payment.is_voided == False)):
        amount = Decimal(payment.amount or 0)
        if payment.direction == FinancialDirection.INCOMING:
            balances[payment.entity_id] += amount
        elif payment.related_invoice_id is not None:
            balances[payment.entity_id] -= amount
        elif roles.get(payment.entity_id) not in {WorkerStateRole.VENDOR, WorkerStateRole.CLIENT}:
            balances[payment.entity_id] -= amount

    for work_log in db.scalars(select(WorkLog).where(WorkLog.project_id == project_id, WorkLog.is_voided == False)):
        if work_log.total_amount is not None and roles.get(work_log.worker_id) in {
            WorkerStateRole.DAILY,
            WorkerStateRole.SKILLED,
        }:
            balances[work_log.worker_id] += Decimal(work_log.total_amount)
    return dict(balances)


def _stored_worker_balances(db: Session, project_id: int) -> dict[int, Decimal]:
    return {
        state.worker_id: Decimal(state.financial_balance or 0)
        for state in db.scalars(select(WorkerState).where(WorkerState.project_id == project_id))
    }


def _sum_payments(db: Session, project_id: int, direction: FinancialDirection) -> Decimal:
    total = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.project_id == project_id,
            Payment.direction == direction,
            Payment.is_voided == False,
        )
    )
    return Decimal(total or 0)


def _sum_real_outgoing_payments(db: Session, project_id: int) -> Decimal:
    total = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.project_id == project_id,
            Payment.direction.in_([FinancialDirection.OUTGOING, FinancialDirection.DEFERRED]),
            Payment.is_voided == False,
        )
    )
    return Decimal(total or 0)


def _stored_project_balance(db: Session, project_id: int) -> Decimal:
    return _sum_payments(db, project_id, FinancialDirection.INCOMING) - _sum_real_outgoing_payments(db, project_id)


def _open_invoice_total(db: Session, project_id: int) -> Decimal:
    total = db.scalar(
        select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
            Invoice.project_id == project_id,
            Invoice.status != InvoiceStatus.PAID,
            Invoice.is_voided == False,
        )
    )
    return Decimal(total or 0)


def _unpaid_worker_remaining(db: Session, project_id: int) -> Decimal:
    roles = {
        state.worker_id: state.role
        for state in db.scalars(select(WorkerState).where(WorkerState.project_id == project_id))
    }
    return sum(
        balance
        for worker_id, balance in _stored_worker_balances(db, project_id).items()
        if balance > 0 and roles.get(worker_id) in {WorkerStateRole.DAILY, WorkerStateRole.SKILLED}
    )


def _payment_history_drift(db: Session, project_id: int) -> list[dict[str, Any]]:
    payment_count = int(
        db.scalar(select(func.count(Payment.id)).where(Payment.project_id == project_id, Payment.is_voided == False)) or 0
    )
    history_count = int(
        db.scalar(
            select(func.count(HistoryEntry.id)).where(
                HistoryEntry.project_id == project_id,
                HistoryEntry.change_type == HistoryChangeType.PAYMENT,
                HistoryEntry.is_voided == False,
            )
        )
        or 0
    )
    if payment_count == history_count:
        return []
    return [
        {
            "field": "payment_history_count",
            "payments": payment_count,
            "history_entries": history_count,
            "difference": payment_count - history_count,
        }
    ]
