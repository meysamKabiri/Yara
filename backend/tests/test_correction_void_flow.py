from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.core import HistoryChangeType, HistoryEntry


def _project(client: TestClient, name: str = "Correction flow") -> dict:
    response = client.post("/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _worker(client: TestClient, project_id: int, name: str, worker_type: str) -> dict:
    response = client.post(
        f"/projects/{project_id}/workers",
        json={"name": name, "type": worker_type},
    )
    assert response.status_code == 201
    return response.json()


def _payment(
    client: TestClient,
    project_id: int,
    entity_id: int,
    amount: str,
    direction: str = "OUTGOING",
    payment_type: str = "BANK_TRANSFER",
    related_invoice_id: int | None = None,
) -> dict:
    payload = {
        "entity_id": entity_id,
        "amount": amount,
        "direction": direction,
        "type": payment_type,
        "related_invoice_id": related_invoice_id,
    }
    response = client.post(f"/projects/{project_id}/payments", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _invoice(client: TestClient, project_id: int, vendor_id: int, amount: str) -> dict:
    response = client.post(
        f"/projects/{project_id}/invoices",
        json={"vendor_id": vendor_id, "total_amount": amount, "description": "مصالح"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _work_log(client: TestClient, project_id: int, worker_id: int) -> dict:
    response = client.post(
        f"/projects/{project_id}/work-logs",
        json={
            "worker_id": worker_id,
            "task_name": "کار روزانه",
            "unit": "day",
            "quantity": "2",
            "rate_per_unit": "1000000",
            "period_label": "هفته اول",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_payment_correction_and_void_affect_active_totals_and_exports(client: TestClient) -> None:
    project = _project(client)
    worker = _worker(client, project["id"], "میثم", "DAILY_WORKER")
    payment = _payment(client, project["id"], worker["id"], "100000000")

    response = client.patch(
        f"/projects/{project['id']}/payments/{payment['id']}",
        json={"amount": "120000000", "description": "اصلاح مبلغ", "correction_note": "اشتباه تایپی"},
    )
    assert response.status_code == 200, response.text
    corrected = response.json()
    assert corrected["amount"] == "120000000.00"
    assert corrected["description"] == "اصلاح مبلغ"
    assert corrected["corrected_at"] is not None

    summary = client.get(f"/projects/{project['id']}/operating-summary").json()
    assert summary["total_paid_out"] == "120000000.00"

    response = client.post(
        f"/projects/{project['id']}/payments/{payment['id']}/void",
        json={"reason": "ثبت تکراری"},
    )
    assert response.status_code == 200, response.text
    voided = response.json()
    assert voided["is_voided"] is True
    assert voided["void_reason"] == "ثبت تکراری"

    summary = client.get(f"/projects/{project['id']}/operating-summary").json()
    assert summary["total_paid_out"] == "0.00"
    assert client.get(f"/projects/{project['id']}/reports/summary").json()["summary"]["paid_out"] == "0"
    assert "120000000" not in client.get(f"/projects/{project['id']}/exports/payments.csv").text

    response = client.patch(
        f"/projects/{project['id']}/payments/{payment['id']}",
        json={"amount": "1"},
    )
    assert response.status_code == 409


def test_void_is_project_scoped(client: TestClient) -> None:
    project = _project(client, "A")
    other_project = _project(client, "B")
    worker = _worker(client, project["id"], "علی", "DAILY_WORKER")
    payment = _payment(client, project["id"], worker["id"], "1000")

    response = client.post(
        f"/projects/{other_project['id']}/payments/{payment['id']}/void",
        json={"reason": "wrong project"},
    )
    assert response.status_code == 404


def test_work_log_correction_and_void_update_labor_summary(client: TestClient) -> None:
    project = _project(client)
    worker = _worker(client, project["id"], "رضا", "DAILY_WORKER")
    log = _work_log(client, project["id"], worker["id"])

    response = client.patch(
        f"/projects/{project['id']}/work-logs/{log['id']}",
        json={"quantity": "3", "rate_per_unit": "1500000", "correction_note": "اصلاح روزها"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["total_amount"] == "4500000.00"

    summary = client.get(f"/projects/{project['id']}/operating-summary").json()
    assert summary["total_work_amount"] == "4500000.00"
    assert summary["worker_payables"][0]["debt"] == "4500000.00"

    response = client.post(
        f"/projects/{project['id']}/work-logs/{log['id']}/void",
        json={"reason": "کارکرد اشتباه"},
    )
    assert response.status_code == 200, response.text
    summary = client.get(f"/projects/{project['id']}/operating-summary").json()
    assert summary["total_work_amount"] == "0.00"
    assert summary["worker_payables"] == []


def test_invoice_correction_void_and_related_payment_status(client: TestClient) -> None:
    project = _project(client)
    vendor = _worker(client, project["id"], "فروشگاه", "VENDOR")
    invoice = _invoice(client, project["id"], vendor["id"], "50000000")

    response = client.patch(
        f"/projects/{project['id']}/payables/{invoice['id']}",
        json={"total_amount": "60000000", "description": "اصلاح فاکتور"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["total_amount"] == "60000000.00"
    assert client.get(f"/projects/{project['id']}/operating-summary").json()["open_payables"] == "60000000.00"

    payment = _payment(client, project["id"], vendor["id"], "20000000", related_invoice_id=invoice["id"])
    invoice_after_payment = client.get(f"/projects/{project['id']}/invoices").json()[0]
    assert invoice_after_payment["status"] == "PARTIAL"

    response = client.post(
        f"/projects/{project['id']}/payments/{payment['id']}/void",
        json={"reason": "پرداخت برگشت خورد"},
    )
    assert response.status_code == 200, response.text
    invoice_after_void_payment = client.get(f"/projects/{project['id']}/invoices").json()[0]
    assert invoice_after_void_payment["status"] == "OPEN"

    response = client.post(
        f"/projects/{project['id']}/payables/{invoice['id']}/void",
        json={"reason": "فاکتور اشتباه"},
    )
    assert response.status_code == 200, response.text
    assert client.get(f"/projects/{project['id']}/operating-summary").json()["open_payables"] == "0"


def test_note_correction_and_void_remain_visible_but_export_excludes_voided(
    client: TestClient,
    db_session: Session,
) -> None:
    project = _project(client)
    note = HistoryEntry(
        project_id=project["id"],
        input_text="یادداشت اولیه",
        change_type=HistoryChangeType.NOTE,
        delta={},
    )
    db_session.add(note)
    db_session.commit()
    db_session.refresh(note)

    response = client.patch(
        f"/projects/{project['id']}/notes/{note.id}",
        json={"text": "یادداشت اصلاح‌شده", "correction_note": "متن کامل‌تر"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["input_text"] == "یادداشت اصلاح‌شده"

    response = client.post(
        f"/projects/{project['id']}/notes/{note.id}/void",
        json={"reason": "دیگر لازم نیست"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_voided"] is True

    history = client.get(f"/projects/{project['id']}/history").json()
    assert history[0]["input_text"] == "یادداشت اصلاح‌شده"
    assert history[0]["is_voided"] is True
    assert "یادداشت اصلاح‌شده" not in client.get(f"/projects/{project['id']}/exports/notes.csv").text
