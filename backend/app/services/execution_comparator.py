import logging
from decimal import Decimal, InvalidOperation
from typing import Any


logger = logging.getLogger(__name__)


class ExecutionComparator:
    def compare(self, old_result: Any, new_engine_result: dict[str, Any]) -> dict[str, Any]:
        old = self._normalize_old_result(old_result)
        new = {
            "payments": list(new_engine_result.get("payments") or []),
            "invoices": list(new_engine_result.get("invoices") or []),
        }
        differences: list[dict[str, Any]] = []

        self._compare_collection_counts(differences, old, new, "payments")
        self._compare_collection_counts(differences, old, new, "invoices")
        self._compare_payment(differences, old["payments"], new["payments"])
        self._compare_invoice(differences, old["invoices"], new["invoices"])

        result = {"matches": not differences, "differences": differences}
        if differences:
            logger.info("execution_engine_shadow_mismatch", extra={"comparison": result})
        else:
            logger.debug("execution_engine_shadow_match", extra={"comparison": result})
        return result

    def _compare_collection_counts(
        self,
        differences: list[dict[str, Any]],
        old: dict[str, list[dict[str, Any]]],
        new: dict[str, list[dict[str, Any]]],
        key: str,
    ) -> None:
        if len(old[key]) != len(new[key]):
            differences.append(
                {
                    "type": f"{key}_count_mismatch",
                    "old": len(old[key]),
                    "new": len(new[key]),
                }
            )

    def _compare_payment(
        self,
        differences: list[dict[str, Any]],
        old_payments: list[dict[str, Any]],
        new_payments: list[dict[str, Any]],
    ) -> None:
        if not old_payments or not new_payments:
            if old_payments and not new_payments:
                differences.append({"type": "missing_payment", "old": old_payments[0], "new": None})
            return
        old = old_payments[0]
        new = new_payments[0]
        if self._decimal(old.get("amount")) != self._decimal(new.get("amount")):
            differences.append(
                {"type": "amount_mismatch", "old": old.get("amount"), "new": new.get("amount")}
            )
        if old.get("direction") != new.get("direction"):
            differences.append(
                {
                    "type": "direction_mismatch",
                    "old": old.get("direction"),
                    "new": new.get("direction"),
                }
            )
        if old.get("entity_id") != new.get("entity_id"):
            differences.append(
                {
                    "type": "entity_mismatch",
                    "old": old.get("entity_id"),
                    "new": new.get("entity_id"),
                }
            )

    def _compare_invoice(
        self,
        differences: list[dict[str, Any]],
        old_invoices: list[dict[str, Any]],
        new_invoices: list[dict[str, Any]],
    ) -> None:
        if not old_invoices or not new_invoices:
            if old_invoices and not new_invoices:
                differences.append({"type": "missing_invoice", "old": old_invoices[0], "new": None})
            return
        old = old_invoices[0]
        new = new_invoices[0]
        if self._decimal(old.get("total_amount")) != self._decimal(new.get("total_amount")):
            differences.append(
                {
                    "type": "amount_mismatch",
                    "old": old.get("total_amount"),
                    "new": new.get("total_amount"),
                }
            )
        if old.get("vendor_id") != new.get("vendor_id"):
            differences.append(
                {
                    "type": "entity_mismatch",
                    "old": old.get("vendor_id"),
                    "new": new.get("vendor_id"),
                }
            )

    def _normalize_old_result(self, old_result: Any) -> dict[str, list[dict[str, Any]]]:
        return {
            "payments": [self._old_payment(item) for item in getattr(old_result, "payments", [])],
            "invoices": [self._old_invoice(item) for item in getattr(old_result, "invoices", [])],
        }

    def _old_payment(self, payment: Any) -> dict[str, Any]:
        return {
            "entity_id": payment.entity_id,
            "amount": str(payment.amount),
            "type": payment.type.value if hasattr(payment.type, "value") else payment.type,
            "direction": (
                payment.direction.value if hasattr(payment.direction, "value") else payment.direction
            ),
            "due_date": payment.due_date,
            "related_invoice_id": payment.related_invoice_id,
        }

    def _old_invoice(self, invoice: Any) -> dict[str, Any]:
        return {
            "vendor_id": invoice.vendor_id,
            "total_amount": str(invoice.total_amount),
            "description": invoice.description,
            "status": invoice.status.value if hasattr(invoice.status, "value") else invoice.status,
        }

    def _decimal(self, value: Any) -> Decimal | None:
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
