import logging
from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.observability_service import track_event, track_timed_event
from app.models.core import (
    FinancialDirection,
    Invoice,
    InvoiceStatus,
    Payment,
    PaymentType,
    Worker,
    WorkerState,
    WorkerStateRole,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfirmedFinancialInterpretation:
    project_id: int
    semantic_action: str
    amount: Decimal | int | str | None
    entity_id: int | None
    financial_direction: FinancialDirection | str | None = None
    payment_method: PaymentType | str | None = None
    due_date: str | None = None
    description: str | None = None
    related_invoice_id: int | None = None


class ExecutionEngine:
    def execute_confirmed_interpretation(
        self,
        confirmed_interpretation: ConfirmedFinancialInterpretation,
        db: Session,
        state: WorkerState | None,
    ) -> dict[str, Any]:
        """
        SINGLE SOURCE OF TRUTH for financial writes.

        Input is ALREADY CONFIRMED AND EDITED by user.

        This function must:
        - NOT re-interpret text
        - NOT use LLM
        - NOT use semantic rules
        - ONLY execute confirmed structured data
        """
        return track_timed_event(
            db=db,
            event_name="execution_engine.execute",
            fn=lambda: self._execute_impl(confirmed_interpretation, db, state),
        )

    def _execute_impl(
        self,
        confirmed_interpretation: ConfirmedFinancialInterpretation,
        db: Session,
        state: WorkerState | None,
    ) -> dict[str, Any]:
        start = perf_counter()
        action = confirmed_interpretation.semantic_action
        direction = self._direction(confirmed_interpretation.financial_direction)
        payment_method = self._payment_method(confirmed_interpretation.payment_method, action)
        amount = self._amount(confirmed_interpretation.amount)
        entity_id = confirmed_interpretation.entity_id
        track_event(
            db=db,
            event_name="EXECUTION_STARTED",
            payload={
                "project_id": confirmed_interpretation.project_id,
                "entity_id": entity_id,
                "action": action,
                "amount": str(amount) if amount is not None else None,
                "direction": direction.value if direction is not None else None,
            },
        )
        logger.info(
            "execution_engine_input",
            extra={
                "project_id": confirmed_interpretation.project_id,
                "action": action,
                "direction": direction.value if direction is not None else None,
                "payment_method": payment_method.value if payment_method is not None else None,
                "amount": str(amount) if amount is not None else None,
                "entity_id": entity_id,
            },
        )
        payments: list[Payment] = []
        invoices: list[Invoice] = []
        try:
            if amount is None:
                raise ValueError("Amount missing in confirmed interpretation")
            if entity_id is None:
                raise ValueError("Entity must be resolved before execution")

            worker = db.get(Worker, entity_id)
            if worker is None or worker.project_id != confirmed_interpretation.project_id:
                raise ValueError("Resolved entity not found in project")

            state = state or self._get_or_create_state(db, worker)

            if action == "PURCHASE_PAID":
                payment = self._create_payment(
                    confirmed_interpretation,
                    db,
                    state,
                    amount,
                    payment_method or PaymentType.CASH,
                    FinancialDirection.OUTGOING,
                )
                payments.append(payment)

            elif action in {"DEBT_CREATED", "INVOICE"}:
                state.role = WorkerStateRole.VENDOR
                state.financial_balance += amount
                invoice = Invoice(
                    project_id=confirmed_interpretation.project_id,
                    vendor_id=entity_id,
                    total_amount=amount,
                    description=confirmed_interpretation.description,
                    status=InvoiceStatus.OPEN,
                )
                db.add(invoice)
                db.flush()
                invoices.append(invoice)

            elif action == "PAYMENT":
                if direction is None:
                    raise ValueError("Direction missing in confirmed interpretation")
                payment = self._create_payment(
                    confirmed_interpretation,
                    db,
                    state,
                    amount,
                    payment_method or PaymentType.BANK_TRANSFER,
                    direction,
                )
                payments.append(payment)

            elif action in {"CHECK_PAYMENT", "DEFERRED_PAYMENT"}:
                payment = self._create_payment(
                    confirmed_interpretation,
                    db,
                    state,
                    amount,
                    PaymentType.CHECK,
                    direction or FinancialDirection.DEFERRED,
                )
                payments.append(payment)

            db.flush()
            for item in [*payments, *invoices]:
                db.refresh(item)

            result = self._result(payments, invoices)
            duration_ms = round((perf_counter() - start) * 1000, 3)
            track_event(
                db=db,
                event_name="DB_WRITE_SUCCESS",
                duration_ms=duration_ms,
                payload={
                    "project_id": confirmed_interpretation.project_id,
                    "payment_ids": [payment.id for payment in payments],
                    "invoice_ids": [invoice.id for invoice in invoices],
                },
            )
            track_event(
                db=db,
                event_name="EXECUTION_COMPLETED",
                duration_ms=duration_ms,
                payload={
                    "project_id": confirmed_interpretation.project_id,
                    "payment_ids": [payment.id for payment in payments],
                    "invoice_ids": [invoice.id for invoice in invoices],
                    "payment_id": payments[0].id if payments else None,
                    "invoice_id": invoices[0].id if invoices else None,
                    "status": "SUCCESS",
                    "duration_ms": duration_ms,
                },
            )
            logger.info(
                "execution_engine_result",
                extra={
                    "project_id": confirmed_interpretation.project_id,
                    "payments": len(payments),
                    "invoices": len(invoices),
                    "payment_ids": [payment.id for payment in payments],
                    "invoice_ids": [invoice.id for invoice in invoices],
                    "duration_ms": duration_ms,
                },
            )
            return result
        except Exception as exc:
            track_event(
                db=db,
                event_name="ERROR_OCCURRED",
                payload={
                    "project_id": confirmed_interpretation.project_id,
                    "action": action,
                    "entity_id": entity_id,
                    "error_message": str(exc),
                    "duration_ms": round((perf_counter() - start) * 1000, 3),
                },
            )
            logger.exception(
                "execution_engine_failed",
                extra={
                    "project_id": confirmed_interpretation.project_id,
                    "action": action,
                    "duration_ms": round((perf_counter() - start) * 1000, 3),
                },
            )
            raise

    def _create_payment(
        self,
        confirmed_interpretation: ConfirmedFinancialInterpretation,
        db: Session,
        state: WorkerState,
        amount: Decimal,
        payment_method: PaymentType,
        direction: FinancialDirection,
    ) -> Payment:
        if direction == FinancialDirection.INCOMING:
            state.role = WorkerStateRole.CLIENT
            state.financial_balance += amount
        elif state.role not in {WorkerStateRole.VENDOR, WorkerStateRole.CLIENT}:
            state.financial_balance -= amount

        payment = Payment(
            project_id=confirmed_interpretation.project_id,
            entity_id=state.worker_id,
            amount=amount,
            related_invoice_id=confirmed_interpretation.related_invoice_id,
            type=payment_method,
            due_date=confirmed_interpretation.due_date,
            direction=direction,
        )
        db.add(payment)
        db.flush()
        if confirmed_interpretation.related_invoice_id is not None and direction != FinancialDirection.INCOMING:
            state.financial_balance -= amount
        return payment

    def _get_or_create_state(self, db: Session, worker: Worker) -> WorkerState:
        state = db.scalar(
            select(WorkerState).where(
                WorkerState.project_id == worker.project_id,
                WorkerState.worker_id == worker.id,
            )
        )
        if state is not None:
            return state
        state = WorkerState(
            project_id=worker.project_id,
            worker_id=worker.id,
            name=worker.name,
            role=self._state_role(worker),
        )
        db.add(state)
        db.flush()
        return state

    def _state_role(self, worker: Worker) -> WorkerStateRole:
        if worker.type.value == "CLIENT":
            return WorkerStateRole.CLIENT
        if worker.type.value == "VENDOR":
            return WorkerStateRole.VENDOR
        if worker.type.value == "SKILLED_WORKER":
            return WorkerStateRole.SKILLED
        return WorkerStateRole.DAILY

    def _amount(self, value: Decimal | int | str | None) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))

    def _direction(self, value: FinancialDirection | str | None) -> FinancialDirection | None:
        if value is None:
            return None
        if isinstance(value, FinancialDirection):
            return value
        return FinancialDirection(value)

    def _payment_method(self, value: PaymentType | str | None, action: str) -> PaymentType | None:
        if value is None:
            if action == "PURCHASE_PAID":
                return PaymentType.CASH
            if action in {"CHECK_PAYMENT", "DEFERRED_PAYMENT"}:
                return PaymentType.CHECK
            return None
        if isinstance(value, PaymentType):
            return value
        return PaymentType(value)

    def _result(self, payments: list[Payment], invoices: list[Invoice]) -> dict[str, Any]:
        return {
            "payments": [self._payment_result(payment) for payment in payments],
            "invoices": [self._invoice_result(invoice) for invoice in invoices],
        }

    def _payment_result(self, payment: Payment) -> dict[str, Any]:
        return {
            "id": payment.id,
            "project_id": payment.project_id,
            "entity_id": payment.entity_id,
            "amount": str(payment.amount),
            "type": payment.type.value,
            "direction": payment.direction.value,
            "due_date": payment.due_date,
            "related_invoice_id": payment.related_invoice_id,
        }

    def _invoice_result(self, invoice: Invoice) -> dict[str, Any]:
        return {
            "id": invoice.id,
            "project_id": invoice.project_id,
            "vendor_id": invoice.vendor_id,
            "total_amount": str(invoice.total_amount),
            "description": invoice.description,
            "status": invoice.status.value,
        }
