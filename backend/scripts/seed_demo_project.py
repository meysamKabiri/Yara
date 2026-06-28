#!/usr/bin/env python
"""Seed a confirmed Yara demo project in the development database.

Dev-only helper. This script does not run automatically and creates a new
timestamped project on each run so existing data is left untouched.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.db.session import SessionLocal
from app.models.core import (
    FinancialDirection,
    HistoryChangeType,
    HistoryEntry,
    Invoice,
    Payment,
    PaymentType,
    Project,
    Worker,
    WorkerType,
    WorkLog,
    WorkUnit,
)


BASE_PROJECT_NAME = "ویلا دماوند - نسخه دمو"


def seed_demo_project() -> tuple[int, str]:
    now = datetime.now()
    project_name = f"{BASE_PROJECT_NAME} - {now:%Y%m%d-%H%M%S}"

    db = SessionLocal()
    try:
        project = Project(name=project_name)
        db.add(project)
        db.flush()

        client = Worker(
            project_id=project.id,
            name="میثم کبیری",
            type=WorkerType.CLIENT,
        )
        paid_vendor = Worker(
            project_id=project.id,
            name="هادی پور",
            type=WorkerType.VENDOR,
        )
        unpaid_vendor = Worker(
            project_id=project.id,
            name="آهنچی",
            type=WorkerType.VENDOR,
        )
        worker = Worker(
            project_id=project.id,
            name="مش رحیم",
            type=WorkerType.DAILY_WORKER,
            daily_rate=Decimal("1200000"),
        )
        db.add_all([client, paid_vendor, unpaid_vendor, worker])
        db.flush()

        db.add_all(
            [
                Payment(
                    project_id=project.id,
                    entity_id=client.id,
                    amount=Decimal("100000000"),
                    type=PaymentType.BANK_TRANSFER,
                    direction=FinancialDirection.INCOMING,
                    description="پرداخت کارفرما",
                ),
                Payment(
                    project_id=project.id,
                    entity_id=paid_vendor.id,
                    amount=Decimal("20000000"),
                    type=PaymentType.CASH,
                    direction=FinancialDirection.OUTGOING,
                    description="خرید و پرداخت سیم",
                ),
                Payment(
                    project_id=project.id,
                    entity_id=worker.id,
                    amount=Decimal("2000000"),
                    type=PaymentType.BANK_TRANSFER,
                    direction=FinancialDirection.OUTGOING,
                    description="پرداخت به کارگر",
                ),
                Invoice(
                    project_id=project.id,
                    vendor_id=unpaid_vendor.id,
                    total_amount=Decimal("50000000"),
                    description="خرید آهن پرداخت نشده",
                ),
                WorkLog(
                    project_id=project.id,
                    worker_id=worker.id,
                    task_name="کار هفته قبل",
                    unit=WorkUnit.DAY,
                    quantity=Decimal("4.5"),
                    rate_per_unit=Decimal("1200000"),
                    total_amount=Decimal("5400000"),
                    period_label="هفته قبل",
                    description="۴ روز و نصفی",
                ),
                HistoryEntry(
                    project_id=project.id,
                    input_text="کارفرما گفت رنگ در تغییر کند",
                    change_type=HistoryChangeType.NOTE,
                    delta={},
                ),
            ]
        )
        db.commit()
        return project.id, project.name
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    project_id, project_name = seed_demo_project()
    print(f"Created demo project {project_id}: {project_name}")
