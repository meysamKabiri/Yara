from fastapi.testclient import TestClient


def test_update_project_name_and_description_succeeds(client: TestClient) -> None:
    created = client.post("/projects", json={"name": " پروژه قدیمی "}).json()

    response = client.patch(
        f"/projects/{created['id']}",
        json={
            "name": " ویلا دماوند - بازسازی کامل طبقه دوم ",
            "description": " توضیح تست ",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "ویلا دماوند - بازسازی کامل طبقه دوم"
    assert body["description"] == "توضیح تست"

    detail = client.get(f"/projects/{created['id']}").json()
    assert detail["name"] == "ویلا دماوند - بازسازی کامل طبقه دوم"
    assert detail["description"] == "توضیح تست"


def test_update_project_empty_name_rejected(client: TestClient) -> None:
    created = client.post("/projects", json={"name": "پروژه"}).json()

    response = client.patch(
        f"/projects/{created['id']}",
        json={"name": "   ", "description": "x"},
    )

    assert response.status_code == 422


def test_update_project_does_not_affect_financial_totals(client: TestClient) -> None:
    project = client.post("/projects", json={"name": "پروژه"}).json()
    worker = client.post(
        f"/projects/{project['id']}/workers",
        json={"name": "میثم", "type": "CLIENT"},
    ).json()
    response = client.post(
        f"/projects/{project['id']}/payments",
        json={
            "entity_id": worker["id"],
            "amount": "100000000",
            "type": "BANK_TRANSFER",
            "direction": "INCOMING",
        },
    )
    assert response.status_code == 201, response.text
    before = client.get(f"/projects/{project['id']}/operating-summary").json()

    response = client.patch(
        f"/projects/{project['id']}",
        json={"name": "پروژه جدید", "description": "فقط توضیح"},
    )

    assert response.status_code == 200, response.text
    after = client.get(f"/projects/{project['id']}/operating-summary").json()
    assert after["total_received"] == before["total_received"] == "100000000.00"
    assert after["total_paid_out"] == before["total_paid_out"] == "0.00"
    assert after["open_payables"] == before["open_payables"] == "0"


def test_update_missing_project_returns_404(client: TestClient) -> None:
    response = client.patch(
        "/projects/999999",
        json={"name": "پروژه جدید", "description": None},
    )

    assert response.status_code == 404
