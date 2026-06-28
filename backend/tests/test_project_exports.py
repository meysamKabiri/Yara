from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.core import (
    FinancialDirection,
    HistoryChangeType,
    HistoryEntry,
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


def _csv_text(response) -> str:
    return response.content.decode("utf-8-sig")


def _build_export_project(db: Session) -> tuple[Project, Project]:
    project = Project(name="پروژه خروجی", created_at=datetime(2026, 1, 1))
    other_project = Project(name="پروژه دیگر", created_at=datetime(2026, 1, 1))
    db.add_all([project, other_project])
    db.flush()

    client = Worker(project_id=project.id, name="میثم کبیری", type=WorkerType.CLIENT, phone="09123456789")
    worker = Worker(project_id=project.id, name="مش رحیم", type=WorkerType.DAILY_WORKER, daily_rate="1200000")
    vendor = Worker(project_id=project.id, name="هادی پور", type=WorkerType.VENDOR)
    unpaid_vendor = Worker(project_id=project.id, name="آهنچی", type=WorkerType.VENDOR)
    deferred_vendor = Worker(project_id=project.id, name="بتن آماده شرق", type=WorkerType.VENDOR)
    other_worker = Worker(project_id=other_project.id, name="نباید دیده شود", type=WorkerType.CLIENT)
    db.add_all([client, worker, vendor, unpaid_vendor, deferred_vendor, other_worker])
    db.flush()

    invoice = Invoice(
        project_id=project.id,
        vendor_id=unpaid_vendor.id,
        total_amount="50000000",
        description="آهن پرداخت‌نشده",
        created_at=datetime(2026, 2, 4, 9),
    )
    other_invoice = Invoice(
        project_id=other_project.id,
        vendor_id=other_worker.id,
        total_amount="999999",
        description="other invoice",
        created_at=datetime(2026, 2, 4, 9),
    )
    db.add_all([invoice, other_invoice])
    db.flush()

    db.add_all([
        Payment(project_id=project.id, entity_id=client.id, amount="100000000", type=PaymentType.BANK_TRANSFER, direction=FinancialDirection.INCOMING, created_at=datetime(2026, 2, 1, 10)),
        Payment(project_id=project.id, entity_id=vendor.id, amount="20000000", type=PaymentType.CASH, direction=FinancialDirection.OUTGOING, created_at=datetime(2026, 2, 2, 10)),
        Payment(project_id=project.id, entity_id=worker.id, amount="2000000", type=PaymentType.BANK_TRANSFER, direction=FinancialDirection.OUTGOING, created_at=datetime(2026, 2, 3, 10)),
        Payment(project_id=project.id, entity_id=deferred_vendor.id, amount="30000000", type=PaymentType.CHECK, direction=FinancialDirection.DEFERRED, due_date="یک ماهه", created_at=datetime(2026, 2, 5, 10)),
        Payment(project_id=other_project.id, entity_id=other_worker.id, amount="777777", type=PaymentType.CASH, direction=FinancialDirection.OUTGOING, created_at=datetime(2026, 2, 2, 10)),
        WorkLog(project_id=project.id, worker_id=worker.id, task_name="کار هفته قبل", unit=WorkUnit.DAY, quantity="4.5", rate_per_unit="1200000", total_amount="5400000", period_label="هفته قبل", description="۴ روز و نصفی", created_at=datetime(2026, 2, 6, 10)),
        WorkLog(project_id=other_project.id, worker_id=other_worker.id, task_name="other work", unit=WorkUnit.DAY, quantity="9", rate_per_unit="1", total_amount="9", created_at=datetime(2026, 2, 6, 10)),
        HistoryEntry(project_id=project.id, input_text="کارفرما گفت رنگ در تغییر کند", change_type=HistoryChangeType.NOTE, created_at=datetime(2026, 2, 7, 10)),
        HistoryEntry(project_id=other_project.id, input_text="other note", change_type=HistoryChangeType.NOTE, created_at=datetime(2026, 2, 7, 10)),
        PendingInterpretation(project_id=project.id, raw_input_text="در انتظار", canonical_event_type="FINANCIAL_EVENT", semantic_action="PAYMENT", status=PendingInterpretationStatus.PENDING, extracted_amount="888888", created_at=datetime(2026, 2, 8, 10)),
        PendingInterpretation(project_id=project.id, raw_input_text="حذف شده", canonical_event_type="FINANCIAL_EVENT", semantic_action="PAYMENT", status=PendingInterpretationStatus.DISCARDED, extracted_amount="999999", created_at=datetime(2026, 2, 8, 10)),
    ])
    db.commit()
    return project, other_project


def test_payments_csv_confirmed_scoped_and_headers(
    client: TestClient,
    db_session: Session,
) -> None:
    project, _ = _build_export_project(db_session)

    response = client.get(f"/projects/{project.id}/exports/payments.csv")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv; charset=utf-8")
    assert "project-1-payments.csv" in response.headers["content-disposition"]
    assert response.content.startswith(b"\xef\xbb\xbf")
    text = _csv_text(response)
    assert "تاریخ ثبت,شخص,نقش,جهت,روش پرداخت,مبلغ,توضیح" in text
    assert "میثم کبیری" in text
    assert "100000000.00" in text
    assert "20000000.00" in text
    assert "2000000.00" in text
    assert "888888" not in text
    assert "999999" not in text
    assert "777777" not in text


def test_people_csv_includes_persian_people_and_totals(
    client: TestClient,
    db_session: Session,
) -> None:
    project, _ = _build_export_project(db_session)

    response = client.get(f"/projects/{project.id}/exports/people.csv")

    assert response.status_code == 200, response.text
    text = _csv_text(response)
    assert "نام,نقش,جزئیات نقش,شماره تماس,شماره حساب,نرخ روزانه" in text
    assert "میثم کبیری,کارفرما" in text
    assert "مش رحیم,کارگر روزمزد" in text
    assert "4.50,5400000.00,2000000.00,3400000.00" in text
    assert "نباید دیده شود" not in text


def test_work_logs_csv_includes_labor_and_does_not_export_as_payment(
    client: TestClient,
    db_session: Session,
) -> None:
    project, _ = _build_export_project(db_session)

    work_response = client.get(f"/projects/{project.id}/exports/work-logs.csv")
    payment_response = client.get(f"/projects/{project.id}/exports/payments.csv")

    assert work_response.status_code == 200, work_response.text
    work_text = _csv_text(work_response)
    assert "مش رحیم" in work_text
    assert "4.50" in work_text
    assert "5400000.00" in work_text
    assert "۴ روز و نصفی" in work_text
    assert "5400000.00" not in _csv_text(payment_response)


def test_payables_csv_includes_unpaid_deferred_and_worker_labor(
    client: TestClient,
    db_session: Session,
) -> None:
    project, _ = _build_export_project(db_session)

    response = client.get(f"/projects/{project.id}/exports/payables.csv")

    assert response.status_code == 200, response.text
    text = _csv_text(response)
    assert "آهنچی,بدهی فروشنده,50000000.00" in text
    assert "بتن آماده شرق,چک / مدت‌دار,30000000.00,یک ماهه" in text
    assert "مش رحیم,مانده کارگر,3400000.00" in text
    assert "other invoice" not in text


def test_notes_csv_confirmed_notes_only(
    client: TestClient,
    db_session: Session,
) -> None:
    project, _ = _build_export_project(db_session)

    response = client.get(f"/projects/{project.id}/exports/notes.csv")

    assert response.status_code == 200, response.text
    text = _csv_text(response)
    assert "کارفرما گفت رنگ در تغییر کند" in text
    assert "در انتظار" not in text
    assert "other note" not in text


def test_summary_csv_and_date_filter(
    client: TestClient,
    db_session: Session,
) -> None:
    project, _ = _build_export_project(db_session)

    summary = client.get(f"/projects/{project.id}/exports/summary.csv?from_date=2026-02-01&to_date=2026-02-28")
    filtered = client.get(f"/projects/{project.id}/exports/payments.csv?from_date=2026-02-03&to_date=2026-02-03")

    assert summary.status_code == 200, summary.text
    summary_text = _csv_text(summary)
    assert "دریافتی,100000000.00" in summary_text
    assert "پرداخت‌شده واقعی,22000000.00" in summary_text
    assert "موارد در انتظار تایید,1" in summary_text
    filtered_text = _csv_text(filtered)
    assert "2000000.00" in filtered_text
    assert "100000000.00" not in filtered_text


def test_empty_export_returns_headers_only(client: TestClient, db_session: Session) -> None:
    project = Project(name="خالی")
    db_session.add(project)
    db_session.commit()

    response = client.get(f"/projects/{project.id}/exports/payments.csv")

    assert response.status_code == 200, response.text
    assert _csv_text(response).strip() == "تاریخ ثبت,شخص,نقش,جهت,روش پرداخت,مبلغ,توضیح"


def test_invalid_project_export_returns_404(client: TestClient) -> None:
    response = client.get("/projects/999/exports/payments.csv")

    assert response.status_code == 404
