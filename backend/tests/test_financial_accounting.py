from fastapi.testclient import TestClient


def _project(client: TestClient) -> dict:
    response = client.post("/projects", json={"name": "Accounting"})
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
    *,
    direction: str = "OUTGOING",
    related_invoice_id: int | None = None,
    payment_type: str = "BANK_TRANSFER",
) -> dict:
    payload = {
        "entity_id": entity_id,
        "amount": amount,
        "type": payment_type,
        "direction": direction,
    }
    if related_invoice_id is not None:
        payload["related_invoice_id"] = related_invoice_id
    response = client.post(f"/projects/{project_id}/payments", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _invoice(client: TestClient, project_id: int, vendor_id: int, amount: str) -> dict:
    response = client.post(
        f"/projects/{project_id}/invoices",
        json={"vendor_id": vendor_id, "total_amount": amount, "description": "debt"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _summary(client: TestClient, project_id: int) -> dict:
    response = client.get(f"/projects/{project_id}/operating-summary")
    assert response.status_code == 200
    return response.json()


def _states(client: TestClient, project_id: int) -> dict[str, dict]:
    response = client.get(f"/projects/{project_id}/worker-states")
    assert response.status_code == 200
    return {state["name"]: state for state in response.json()}


def test_core_accounting_equations_for_client_worker_vendor_and_paid_purchase(client: TestClient) -> None:
    project = _project(client)
    client_worker = _worker(client, project["id"], "میثم", "CLIENT")
    worker = _worker(client, project["id"], "نادری", "SKILLED_WORKER")
    vendor = _worker(client, project["id"], "هادی‌پور", "VENDOR")

    _payment(client, project["id"], client_worker["id"], "200000000", direction="INCOMING")
    _payment(client, project["id"], worker["id"], "100000000", direction="OUTGOING")
    _payment(client, project["id"], vendor["id"], "5000000", direction="OUTGOING")

    summary = _summary(client, project["id"])

    assert summary["total_received_from_client"] == "200000000.00"
    assert summary["total_paid_out"] == "105000000.00"
    assert summary["open_payables"] == "0"
    assert summary["project_balance"] == "95000000.00"
    assert summary["client_receivable"] == "0"
    assert summary["available_balance"] == "95000000.00"
    assert summary["vendor_debts"] == []

    states = _states(client, project["id"])
    assert states["میثم"]["financial_balance"] == "200000000.00"
    assert states["نادری"]["financial_balance"] == "-100000000.00"
    assert states["هادی‌پور"]["financial_balance"] == "0.00"


def test_unpaid_purchase_creates_payable_without_cash_out(client: TestClient) -> None:
    project = _project(client)
    vendor = _worker(client, project["id"], "فروشنده", "VENDOR")

    invoice = _invoice(client, project["id"], vendor["id"], "30000000")
    summary = _summary(client, project["id"])

    assert invoice["status"] == "OPEN"
    assert summary["total_paid_out"] == "0.00"
    assert summary["open_payables"] == "30000000.00"
    assert summary["project_balance"] == "-30000000.00"
    assert summary["client_receivable"] == "30000000.00"
    assert summary["available_balance"] == "0"
    assert summary["vendor_debts"][0]["debt"] == "30000000.00"


def test_partial_payment_against_invoice_reduces_payable_and_updates_balance(client: TestClient) -> None:
    project = _project(client)
    client_worker = _worker(client, project["id"], "کارفرما", "CLIENT")
    vendor = _worker(client, project["id"], "فروشنده", "VENDOR")
    invoice = _invoice(client, project["id"], vendor["id"], "10000000")

    _payment(client, project["id"], client_worker["id"], "12000000", direction="INCOMING")
    _payment(
        client,
        project["id"],
        vendor["id"],
        "4000000",
        related_invoice_id=invoice["id"],
    )

    invoices = client.get(f"/projects/{project['id']}/invoices").json()
    summary = _summary(client, project["id"])
    states = _states(client, project["id"])

    assert invoices[0]["status"] == "PARTIAL"
    assert summary["total_received_from_client"] == "12000000.00"
    assert summary["total_paid_out"] == "4000000.00"
    assert summary["open_payables"] == "6000000.00"
    assert summary["project_balance"] == "2000000.00"
    assert summary["client_receivable"] == "0"
    assert summary["available_balance"] == "2000000.00"
    assert states["فروشنده"]["financial_balance"] == "6000000.00"


def test_full_payment_and_overpayment_never_create_negative_payable(client: TestClient) -> None:
    project = _project(client)
    vendor = _worker(client, project["id"], "فروشنده", "VENDOR")
    invoice = _invoice(client, project["id"], vendor["id"], "10000000")

    _payment(
        client,
        project["id"],
        vendor["id"],
        "15000000",
        related_invoice_id=invoice["id"],
    )

    invoices = client.get(f"/projects/{project['id']}/invoices").json()
    summary = _summary(client, project["id"])
    states = _states(client, project["id"])

    assert invoices[0]["status"] == "PAID"
    assert summary["total_paid_out"] == "15000000.00"
    assert summary["open_payables"] == "0"
    assert summary["vendor_debts"][0]["debt"] == "0"
    assert summary["project_balance"] == "-15000000.00"
    assert summary["client_receivable"] == "15000000.00"
    assert states["فروشنده"]["financial_balance"] == "-5000000.00"


def test_deferred_check_counts_as_paid_out_and_preserves_due_date(client: TestClient) -> None:
    project = _project(client)
    vendor = _worker(client, project["id"], "سرامیک", "VENDOR")

    response = client.post(
        f"/projects/{project['id']}/payments",
        json={
            "entity_id": vendor["id"],
            "amount": "50000000",
            "type": "CHECK",
            "direction": "DEFERRED",
            "due_date": "۱۴ مهر ۱۴۰۵",
        },
    )
    assert response.status_code == 201
    payment = response.json()
    summary = _summary(client, project["id"])

    assert payment["type"] == "CHECK"
    assert payment["direction"] == "DEFERRED"
    assert payment["due_date"] == "۱۴ مهر ۱۴۰۵"
    assert summary["total_paid_out"] == "0.00"
    assert summary["open_payables"] == "0"
    assert summary["deferred_amount"] == "50000000.00"
    assert summary["check_amount"] == "50000000.00"
    assert summary["client_receivable"] == "0"


def test_negative_worker_payment_balance_is_not_project_payable(client: TestClient) -> None:
    project = _project(client)
    worker = _worker(client, project["id"], "کارگر", "DAILY_WORKER")

    _payment(client, project["id"], worker["id"], "2000000", direction="OUTGOING")
    summary = _summary(client, project["id"])
    states = _states(client, project["id"])

    assert states["کارگر"]["financial_balance"] == "-2000000.00"
    assert summary["open_payables"] == "0"
    assert summary["vendor_debts"] == []
    assert summary["client_receivable"] == "2000000.00"
