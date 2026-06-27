from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.core import (
    FinancialDirection,
    Invoice,
    Payment,
    PaymentType,
    PendingInterpretation,
    PendingInterpretationStatus,
    Project,
    Worker,
    WorkerType,
    WorkLog,
)


def project_report_summary(
    db: Session,
    project_id: int,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> dict[str, Any]:
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError("Project not found")

    start_at = datetime.combine(from_date, time.min) if from_date else None
    end_at = datetime.combine(to_date, time.max) if to_date else None

    workers = {
        worker.id: worker
        for worker in db.scalars(select(Worker).where(Worker.project_id == project_id))
    }
    payments = list(
        db.scalars(
            _period_filter(
                select(Payment).where(Payment.project_id == project_id),
                Payment.created_at,
                start_at,
                end_at,
            ).order_by(Payment.created_at.desc(), Payment.id.desc())
        )
    )
    work_logs = list(
        db.scalars(
            _period_filter(
                select(WorkLog).where(WorkLog.project_id == project_id),
                WorkLog.created_at,
                start_at,
                end_at,
            ).order_by(WorkLog.created_at.desc(), WorkLog.id.desc())
        )
    )
    invoices = list(
        db.scalars(
            _period_filter(
                select(Invoice).where(Invoice.project_id == project_id),
                Invoice.created_at,
                start_at,
                end_at,
            ).order_by(Invoice.created_at.desc(), Invoice.id.desc())
        )
    )

    money_in = _sum(payment.amount for payment in payments if payment.direction == FinancialDirection.INCOMING)
    paid_out = _sum(payment.amount for payment in payments if payment.direction == FinancialDirection.OUTGOING)
    deferred_checks = _sum(
        payment.amount
        for payment in payments
        if payment.direction == FinancialDirection.DEFERRED or payment.type == PaymentType.CHECK
    )
    labor_cost = _sum(log.total_amount for log in work_logs)
    worker_payments = _sum(
        payment.amount
        for payment in payments
        if payment.direction == FinancialDirection.OUTGOING
        and workers.get(payment.entity_id)
        and workers[payment.entity_id].type in {WorkerType.DAILY_WORKER, WorkerType.SKILLED_WORKER}
    )

    client_rows = _client_payment_rows(payments, workers)
    worker_rows = _worker_rows(work_logs, payments, workers)
    expense_summary = _expense_summary(payments, invoices, workers)
    payable_rows, open_vendor_payables = _payable_rows(invoices, payments, workers)
    worker_labor_payables = _worker_labor_payable_rows(worker_rows)
    open_payables = open_vendor_payables + _sum(Decimal(row["amount"]) for row in worker_labor_payables)

    pending_count = db.scalar(
        select(func.count(PendingInterpretation.id)).where(
            PendingInterpretation.project_id == project_id,
            PendingInterpretation.status.in_(
                [PendingInterpretationStatus.PENDING, PendingInterpretationStatus.EDITED]
            ),
        )
    )

    return {
        "project_id": project.id,
        "project_name": project.name,
        "from_date": from_date.isoformat() if from_date else None,
        "to_date": to_date.isoformat() if to_date else None,
        "summary": {
            "money_in": str(money_in),
            "paid_out": str(paid_out),
            "open_payables": str(open_payables),
            "deferred_checks": str(deferred_checks),
            "labor_cost": str(labor_cost),
            "worker_payments": str(worker_payments),
            "approximate_balance": str(money_in - paid_out - open_payables),
            "pending_count": int(pending_count or 0),
        },
        "client_payments": client_rows,
        "workers": worker_rows,
        "expense_summary": {
            **expense_summary,
            "open_vendor_payables": str(open_vendor_payables),
            "deferred_check_total": str(deferred_checks),
        },
        "payables": [*payable_rows, *worker_labor_payables],
    }


def _period_filter(statement, column, start_at: datetime | None, end_at: datetime | None):
    if start_at is not None:
        statement = statement.where(column >= start_at)
    if end_at is not None:
        statement = statement.where(column <= end_at)
    return statement


def _sum(values) -> Decimal:
    total = Decimal("0")
    for value in values:
        if value is not None:
            total += Decimal(value)
    return total


def _client_payment_rows(payments: list[Payment], workers: dict[int, Worker]) -> list[dict[str, Any]]:
    grouped: dict[int, dict[str, Any]] = {}
    for payment in payments:
        if payment.direction != FinancialDirection.INCOMING:
            continue
        worker = workers.get(payment.entity_id)
        row = grouped.setdefault(
            payment.entity_id,
            {
                "entity_id": payment.entity_id,
                "name": worker.name if worker else "نامشخص",
                "total_paid": Decimal("0"),
                "payment_count": 0,
                "last_payment_at": None,
            },
        )
        row["total_paid"] += payment.amount
        row["payment_count"] += 1
        if row["last_payment_at"] is None or payment.created_at > row["last_payment_at"]:
            row["last_payment_at"] = payment.created_at

    return [
        {
            **row,
            "total_paid": str(row["total_paid"]),
            "last_payment_at": row["last_payment_at"].isoformat() if row["last_payment_at"] else None,
        }
        for row in sorted(grouped.values(), key=lambda item: item["total_paid"], reverse=True)
    ]


def _worker_rows(
    work_logs: list[WorkLog],
    payments: list[Payment],
    workers: dict[int, Worker],
) -> list[dict[str, Any]]:
    grouped: dict[int, dict[str, Any]] = {}

    for log in work_logs:
        worker = workers.get(log.worker_id)
        row = grouped.setdefault(log.worker_id, _worker_row(log.worker_id, worker))
        if log.unit.value == "day":
            row["total_days"] += log.quantity
        row["total_labor_cost"] += log.total_amount or Decimal("0")

    for payment in payments:
        if payment.direction != FinancialDirection.OUTGOING:
            continue
        worker = workers.get(payment.entity_id)
        if not worker or worker.type not in {WorkerType.DAILY_WORKER, WorkerType.SKILLED_WORKER}:
            continue
        row = grouped.setdefault(payment.entity_id, _worker_row(payment.entity_id, worker))
        row["total_paid"] += payment.amount

    rows = []
    for row in grouped.values():
        remaining = row["total_labor_cost"] - row["total_paid"]
        rows.append(
            {
                **row,
                "total_days": str(row["total_days"]),
                "total_labor_cost": str(row["total_labor_cost"]),
                "total_paid": str(row["total_paid"]),
                "remaining_balance": str(remaining),
                "daily_rate": str(row["daily_rate"]) if row["daily_rate"] is not None else None,
            }
        )
    return sorted(rows, key=lambda item: Decimal(item["total_labor_cost"]), reverse=True)


def _worker_row(worker_id: int, worker: Worker | None) -> dict[str, Any]:
    return {
        "worker_id": worker_id,
        "entity_id": worker_id,
        "name": worker.name if worker else "نامشخص",
        "total_days": Decimal("0"),
        "total_labor_cost": Decimal("0"),
        "total_paid": Decimal("0"),
        "remaining_balance": Decimal("0"),
        "daily_rate": worker.daily_rate if worker else None,
    }


def _expense_summary(
    payments: list[Payment],
    invoices: list[Invoice],
    workers: dict[int, Worker],
) -> dict[str, str]:
    related_invoice_ids = {invoice.id for invoice in invoices}
    vendor_paid = Decimal("0")
    worker_paid = Decimal("0")
    other_paid = Decimal("0")

    for payment in payments:
        if payment.direction != FinancialDirection.OUTGOING:
            continue
        worker = workers.get(payment.entity_id)
        if worker and worker.type in {WorkerType.DAILY_WORKER, WorkerType.SKILLED_WORKER}:
            worker_paid += payment.amount
        elif (worker and worker.type == WorkerType.VENDOR) or payment.related_invoice_id in related_invoice_ids:
            vendor_paid += payment.amount
        else:
            other_paid += payment.amount

    return {
        "vendor_paid_total": str(vendor_paid),
        "worker_paid_total": str(worker_paid),
        "other_outgoing_total": str(other_paid),
    }


def _payable_rows(
    invoices: list[Invoice],
    payments: list[Payment],
    workers: dict[int, Worker],
) -> tuple[list[dict[str, Any]], Decimal]:
    paid_by_invoice: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    for payment in payments:
        if payment.related_invoice_id is not None and payment.direction == FinancialDirection.OUTGOING:
            paid_by_invoice[payment.related_invoice_id] += payment.amount

    rows: list[dict[str, Any]] = []
    open_vendor_payables = Decimal("0")
    for invoice in invoices:
        debt = max(invoice.total_amount - paid_by_invoice[invoice.id], Decimal("0"))
        if debt <= 0:
            continue
        vendor = workers.get(invoice.vendor_id)
        open_vendor_payables += debt
        rows.append(
            {
                "id": f"invoice-{invoice.id}",
                "entity_id": invoice.vendor_id,
                "name": vendor.name if vendor else "نامشخص",
                "kind": "vendor_payable",
                "amount": str(debt),
                "due_date": None,
                "description": invoice.description,
            }
        )

    for payment in payments:
        if payment.direction != FinancialDirection.DEFERRED and payment.type != PaymentType.CHECK:
            continue
        worker = workers.get(payment.entity_id)
        rows.append(
            {
                "id": f"payment-{payment.id}",
                "entity_id": payment.entity_id,
                "name": worker.name if worker else "نامشخص",
                "kind": "deferred_check",
                "amount": str(payment.amount),
                "due_date": payment.due_date,
                "description": None,
            }
        )

    return rows, open_vendor_payables


def _worker_labor_payable_rows(worker_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in worker_rows:
        remaining = Decimal(row["remaining_balance"])
        if remaining <= 0:
            continue
        rows.append(
            {
                "id": f"worker-{row['worker_id']}",
                "entity_id": row["entity_id"],
                "name": row["name"],
                "kind": "worker_labor",
                "amount": str(remaining),
                "due_date": None,
                "description": "مانده کارکرد پرداخت‌نشده",
            }
        )
    return rows
