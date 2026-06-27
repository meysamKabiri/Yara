from datetime import datetime

from fastapi.testclient import TestClient
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
    WorkUnit,
)


def _build_report_project(db: Session) -> Project:
    project = Project(name="Report Project", created_at=datetime(2026, 1, 1))
    db.add(project)
    db.flush()

    client = Worker(
        project_id=project.id,
        name="میثم",
        type=WorkerType.CLIENT,
        created_at=datetime(2026, 1, 1),
    )
    worker = Worker(
        project_id=project.id,
        name="مش رحیم",
        type=WorkerType.DAILY_WORKER,
        daily_rate="1200000",
        created_at=datetime(2026, 1, 1),
    )
    vendor = Worker(
        project_id=project.id,
        name="آهنچی",
        type=WorkerType.VENDOR,
        created_at=datetime(2026, 1, 1),
    )
    other = Worker(
        project_id=project.id,
        name="متفرقه",
        type=WorkerType.OTHER,
        created_at=datetime(2026, 1, 1),
    )
    db.add_all([client, worker, vendor, other])
    db.flush()

    invoice = Invoice(
        project_id=project.id,
        vendor_id=vendor.id,
        total_amount="50000000",
        description="آهن پرداخت‌نشده",
        created_at=datetime(2026, 2, 4, 9),
    )
    db.add(invoice)
    db.flush()

    db.add_all(
        [
            Payment(
                project_id=project.id,
                entity_id=client.id,
                amount="100000000",
                type=PaymentType.BANK_TRANSFER,
                direction=FinancialDirection.INCOMING,
                created_at=datetime(2026, 2, 1, 10),
            ),
            Payment(
                project_id=project.id,
                entity_id=client.id,
                amount="7000000",
                type=PaymentType.BANK_TRANSFER,
                direction=FinancialDirection.INCOMING,
                created_at=datetime(2026, 3, 1, 10),
            ),
            Payment(
                project_id=project.id,
                entity_id=vendor.id,
                amount="20000000",
                type=PaymentType.CASH,
                direction=FinancialDirection.OUTGOING,
                created_at=datetime(2026, 2, 2, 10),
            ),
            Payment(
                project_id=project.id,
                entity_id=worker.id,
                amount="2000000",
                type=PaymentType.BANK_TRANSFER,
                direction=FinancialDirection.OUTGOING,
                created_at=datetime(2026, 2, 3, 10),
            ),
            Payment(
                project_id=project.id,
                entity_id=vendor.id,
                amount="30000000",
                type=PaymentType.CHECK,
                direction=FinancialDirection.DEFERRED,
                due_date="یک ماهه",
                created_at=datetime(2026, 2, 5, 10),
            ),
            Payment(
                project_id=project.id,
                entity_id=other.id,
                amount="999000",
                type=PaymentType.CASH,
                direction=FinancialDirection.OUTGOING,
                created_at=datetime(2026, 1, 1, 10),
            ),
            WorkLog(
                project_id=project.id,
                worker_id=worker.id,
                task_name="کار هفته قبل",
                unit=WorkUnit.DAY,
                quantity="4.5",
                rate_per_unit="1200000",
                total_amount="5400000",
                period_label="هفته قبل",
                created_at=datetime(2026, 2, 6, 10),
            ),
            WorkLog(
                project_id=project.id,
                worker_id=worker.id,
                task_name="خارج از بازه",
                unit=WorkUnit.DAY,
                quantity="2",
                rate_per_unit="1200000",
                total_amount="2400000",
                created_at=datetime(2026, 3, 2, 10),
            ),
            PendingInterpretation(
                project_id=project.id,
                raw_input_text="در انتظار",
                canonical_event_type="WORK_EVENT",
                semantic_action="WORK_LOG",
                status=PendingInterpretationStatus.PENDING,
                created_at=datetime(2026, 2, 7, 10),
            ),
            PendingInterpretation(
                project_id=project.id,
                raw_input_text="حذف شده",
                canonical_event_type="WORK_EVENT",
                semantic_action="WORK_LOG",
                status=PendingInterpretationStatus.DISCARDED,
                extracted_amount="900000000",
                created_at=datetime(2026, 2, 7, 11),
            ),
        ]
    )
    db.commit()
    return project


def test_project_report_uses_confirmed_records_and_excludes_pending_and_discarded(
    client: TestClient,
    db_session: Session,
) -> None:
    project = _build_report_project(db_session)

    response = client.get(
        f"/projects/{project.id}/reports/summary?from_date=2026-02-01&to_date=2026-02-28"
    )

    assert response.status_code == 200, response.text
    report = response.json()
    summary = report["summary"]
    assert summary["money_in"] == "100000000.00"
    assert summary["paid_out"] == "22000000.00"
    assert summary["deferred_checks"] == "30000000.00"
    assert summary["labor_cost"] == "5400000.00"
    assert summary["worker_payments"] == "2000000.00"
    assert summary["open_payables"] == "53400000.00"
    assert summary["approximate_balance"] == "24600000.00"
    assert summary["pending_count"] == 1

    assert report["expense_summary"] == {
        "vendor_paid_total": "20000000.00",
        "worker_paid_total": "2000000.00",
        "other_outgoing_total": "0",
        "open_vendor_payables": "50000000.00",
        "deferred_check_total": "30000000.00",
    }
    assert report["client_payments"] == [
        {
            "entity_id": 1,
            "name": "میثم",
            "total_paid": "100000000.00",
            "payment_count": 1,
            "last_payment_at": "2026-02-01T10:00:00",
        }
    ]
    worker_row = report["workers"][0]
    assert worker_row["name"] == "مش رحیم"
    assert worker_row["total_days"] == "4.50"
    assert worker_row["total_labor_cost"] == "5400000.00"
    assert worker_row["total_paid"] == "2000000.00"
    assert worker_row["remaining_balance"] == "3400000.00"
    assert {row["kind"] for row in report["payables"]} == {
        "vendor_payable",
        "deferred_check",
        "worker_labor",
    }


def test_project_report_date_range_excludes_outside_records(
    client: TestClient,
    db_session: Session,
) -> None:
    project = _build_report_project(db_session)

    response = client.get(
        f"/projects/{project.id}/reports/summary?from_date=2026-03-01&to_date=2026-03-31"
    )

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["summary"]["money_in"] == "7000000.00"
    assert report["summary"]["paid_out"] == "0"
    assert report["summary"]["labor_cost"] == "2400000.00"
    assert report["summary"]["open_payables"] == "2400000.00"
    assert report["summary"]["deferred_checks"] == "0"
    assert report["client_payments"][0]["total_paid"] == "7000000.00"
    assert report["workers"][0]["total_days"] == "2.00"


def test_project_report_rejects_invalid_date_range(
    client: TestClient,
    db_session: Session,
) -> None:
    project = _build_report_project(db_session)

    response = client.get(
        f"/projects/{project.id}/reports/summary?from_date=2026-03-01&to_date=2026-02-01"
    )

    assert response.status_code == 400
