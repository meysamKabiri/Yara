from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.core import (
    FinancialDirection,
    Invoice,
    Payment,
    PaymentType,
    Worker,
    WorkerType,
    WorkLog,
)


def invoice_paid_amount(db: Session, invoice_id: int) -> Decimal:
    return db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.related_invoice_id == invoice_id,
            Payment.is_voided == False,
        )
    )


def project_operating_summary(db: Session, project_id: int) -> dict[str, Any]:
    total_work_amount = db.scalar(
        select(func.coalesce(func.sum(WorkLog.total_amount), 0)).where(
            WorkLog.project_id == project_id,
            WorkLog.is_voided == False,
        )
    )
    total_invoice_amount = db.scalar(
        select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
            Invoice.project_id == project_id,
            Invoice.is_voided == False,
        )
    )
    total_payments = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.project_id == project_id,
            Payment.is_voided == False,
        )
    )
    total_paid_out = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.project_id == project_id,
            Payment.direction == FinancialDirection.OUTGOING,
            Payment.is_voided == False,
        )
    )
    total_received = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.project_id == project_id,
            Payment.direction == FinancialDirection.INCOMING,
            Payment.is_voided == False,
        )
    )
    deferred_amount = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.project_id == project_id,
            Payment.direction == FinancialDirection.DEFERRED,
            Payment.is_voided == False,
        )
    )
    check_amount = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.project_id == project_id,
            Payment.type == PaymentType.CHECK,
            Payment.is_voided == False,
        )
    )

    vendor_debts = _vendor_debts(db, project_id)
    worker_payables = _worker_payables(db, project_id)
    open_payables = (
        sum((Decimal(debt["debt"]) for debt in vendor_debts), Decimal("0"))
        + sum((Decimal(payable["debt"]) for payable in worker_payables), Decimal("0"))
    )
    project_balance = total_received - total_paid_out - open_payables
    client_receivable = max(Decimal("0"), total_paid_out + open_payables - total_received)
    available_balance = max(Decimal("0"), project_balance)

    return {
        "total_work_amount": str(total_work_amount),
        "total_invoice_amount": str(total_invoice_amount),
        "total_payments": str(total_payments),
        "total_paid_out": str(total_paid_out),
        "total_received": str(total_received),
        "total_received_from_client": str(total_received),
        "open_payables": str(open_payables),
        "project_balance": str(project_balance),
        "client_receivable": str(client_receivable),
        "available_balance": str(available_balance),
        "deferred_amount": str(deferred_amount),
        "check_amount": str(check_amount),
        "vendor_debts": vendor_debts,
        "worker_payables": worker_payables,
    }


def _worker_payables(db: Session, project_id: int) -> list[dict[str, str | int]]:
    workers = {
        worker.id: worker
        for worker in db.scalars(
            select(Worker).where(
                Worker.project_id == project_id,
                Worker.type.in_([WorkerType.DAILY_WORKER, WorkerType.SKILLED_WORKER]),
            )
        )
    }
    if not workers:
        return []

    work_totals: dict[int, Decimal] = {worker_id: Decimal("0") for worker_id in workers}
    paid_totals: dict[int, Decimal] = {worker_id: Decimal("0") for worker_id in workers}

    for log in db.scalars(
        select(WorkLog).where(
            WorkLog.project_id == project_id,
            WorkLog.is_voided == False,
        )
    ):
        if log.worker_id in work_totals:
            work_totals[log.worker_id] += Decimal(log.total_amount or 0)

    for payment in db.scalars(
        select(Payment).where(
            Payment.project_id == project_id,
            Payment.direction == FinancialDirection.OUTGOING,
            Payment.is_voided == False,
        )
    ):
        if payment.entity_id in paid_totals:
            paid_totals[payment.entity_id] += Decimal(payment.amount or 0)

    rows = []
    for worker_id, worker in workers.items():
        debt = work_totals[worker_id] - paid_totals[worker_id]
        if debt <= 0:
            continue
        rows.append(
            {
                "worker_id": worker_id,
                "worker_name": worker.name,
                "debt": str(debt),
            }
        )
    return rows


def _vendor_debts(db: Session, project_id: int) -> list[dict[str, str | int]]:
    invoices = list(
        db.scalars(
            select(Invoice).where(
                Invoice.project_id == project_id,
                Invoice.is_voided == False,
            )
        )
    )
    vendor_ids = {invoice.vendor_id for invoice in invoices}
    vendors_by_id = (
        {
            vendor.id: vendor
            for vendor in db.scalars(select(Worker).where(Worker.id.in_(vendor_ids)))
        }
        if vendor_ids
        else {}
    )
    grouped: dict[int, dict[str, Decimal]] = {}
    for invoice in invoices:
        paid_amount = invoice_paid_amount(db, invoice.id)
        entry = grouped.setdefault(
            invoice.vendor_id,
            {"invoice_total": Decimal("0"), "paid_total": Decimal("0"), "debt": Decimal("0")},
        )
        entry["invoice_total"] += invoice.total_amount
        entry["paid_total"] += paid_amount
        entry["debt"] += max(invoice.total_amount - paid_amount, Decimal("0"))

    return [
        {
            "vendor_id": vendor_id,
            "vendor_name": (
                vendors_by_id[vendor_id].name if vendor_id in vendors_by_id else "Unknown"
            ),
            "invoice_total": str(values["invoice_total"]),
            "paid_total": str(values["paid_total"]),
            "debt": str(values["debt"]),
        }
        for vendor_id, values in grouped.items()
    ]
