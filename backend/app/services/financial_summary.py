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
    WorkerState,
    WorkerStateRole,
    WorkLog,
)


def invoice_paid_amount(db: Session, invoice_id: int) -> Decimal:
    return db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.related_invoice_id == invoice_id
        )
    )


def project_operating_summary(db: Session, project_id: int) -> dict[str, Any]:
    total_work_amount = db.scalar(
        select(func.coalesce(func.sum(WorkLog.total_amount), 0)).where(
            WorkLog.project_id == project_id
        )
    )
    total_invoice_amount = db.scalar(
        select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
            Invoice.project_id == project_id
        )
    )
    total_payments = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.project_id == project_id)
    )
    total_paid_out = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.project_id == project_id,
            Payment.direction == FinancialDirection.OUTGOING,
        )
    )
    total_received = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.project_id == project_id,
            Payment.direction == FinancialDirection.INCOMING,
        )
    )
    deferred_amount = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.project_id == project_id,
            Payment.direction == FinancialDirection.DEFERRED,
        )
    )
    check_amount = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.project_id == project_id,
            Payment.type == PaymentType.CHECK,
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
    states = list(
        db.scalars(
            select(WorkerState).where(
                WorkerState.project_id == project_id,
                WorkerState.role == WorkerStateRole.DAILY,
                WorkerState.financial_balance > 0,
            )
        )
    )
    worker_ids = {state.worker_id for state in states}
    workers_by_id = (
        {
            worker.id: worker
            for worker in db.scalars(select(Worker).where(Worker.id.in_(worker_ids)))
        }
        if worker_ids
        else {}
    )
    return [
        {
            "worker_id": state.worker_id,
            "worker_name": workers_by_id[state.worker_id].name
            if state.worker_id in workers_by_id
            else state.name,
            "debt": str(state.financial_balance),
        }
        for state in states
    ]


def _vendor_debts(db: Session, project_id: int) -> list[dict[str, str | int]]:
    invoices = list(db.scalars(select(Invoice).where(Invoice.project_id == project_id)))
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
