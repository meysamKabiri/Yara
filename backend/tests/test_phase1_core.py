from fastapi.testclient import TestClient


def create_project(client: TestClient) -> dict:
    response = client.post("/projects", json={"name": "Kitchen remodel"})
    assert response.status_code == 201
    return response.json()


def create_raw_entry(client: TestClient, project_id: int) -> dict:
    response = client.post(
        f"/projects/{project_id}/raw-entries",
        json={"text": "Paid Dana 250 for tile work"},
    )
    assert response.status_code == 201
    return response.json()


def create_pending_event(
    client: TestClient,
    project_id: int,
    raw_entry_id: int,
    event_type: str = "MONEY_OUT",
    amount: str | None = "250.00",
) -> dict:
    response = client.post(
        f"/projects/{project_id}/raw-entries/{raw_entry_id}/extracted-events",
        json=[
            {
                "type": event_type,
                "counterparty_name": "Dana",
                "counterparty_type": "PERSON",
                "amount": amount,
                "description": "Tile work",
                "confidence": "0.9000",
            }
        ],
    )
    assert response.status_code == 201
    return response.json()[0]


def test_project_creation(client: TestClient) -> None:
    project = create_project(client)

    assert project["name"] == "Kitchen remodel"
    assert project["id"] is not None
    assert project["created_at"] is not None
    assert project["updated_at"] is not None


def test_raw_entry_creation(client: TestClient) -> None:
    project = create_project(client)

    raw_entry = create_raw_entry(client, project["id"])

    assert raw_entry["project_id"] == project["id"]
    assert raw_entry["text"] == "Paid Dana 250 for tile work"
    assert raw_entry["status"] == "PENDING"


def test_pending_event_creation(client: TestClient) -> None:
    project = create_project(client)
    raw_entry = create_raw_entry(client, project["id"])

    event = create_pending_event(client, project["id"], raw_entry["id"])

    assert event["project_id"] == project["id"]
    assert event["raw_entry_id"] == raw_entry["id"]
    assert event["status"] == "PENDING"
    assert event["type"] == "MONEY_OUT"


def test_confirmed_events_affect_totals(client: TestClient) -> None:
    project = create_project(client)
    raw_entry = create_raw_entry(client, project["id"])
    money_in = create_pending_event(client, project["id"], raw_entry["id"], "MONEY_IN", "1000.00")
    purchase = create_pending_event(client, project["id"], raw_entry["id"], "PURCHASE", "250.00")
    note = create_pending_event(client, project["id"], raw_entry["id"], "NOTE", "999.00")

    assert client.post(f"/extracted-events/{money_in['id']}/confirm").status_code == 200
    assert client.post(f"/extracted-events/{purchase['id']}/confirm").status_code == 200
    assert client.post(f"/extracted-events/{note['id']}/confirm").status_code == 200
    response = client.get(f"/projects/{project['id']}")

    assert response.status_code == 200
    assert response.json()["totals"] == {
        "money_in": "1000.00",
        "money_out": "250.00",
        "net": "750.00",
    }


def test_pending_and_discarded_events_do_not_affect_totals(client: TestClient) -> None:
    project = create_project(client)
    raw_entry = create_raw_entry(client, project["id"])
    pending = create_pending_event(client, project["id"], raw_entry["id"], "MONEY_IN", "1000.00")
    discarded = create_pending_event(client, project["id"], raw_entry["id"], "MONEY_OUT", "400.00")

    assert client.post(f"/extracted-events/{discarded['id']}/discard").status_code == 200
    response = client.get(f"/projects/{project['id']}")

    assert response.status_code == 200
    assert response.json()["totals"] == {
        "money_in": "0",
        "money_out": "0",
        "net": "0",
    }
    pending_response = client.get(f"/projects/{project['id']}/extracted-events/pending")
    assert pending_response.json()[0]["id"] == pending["id"]


def test_editing_before_confirmation(client: TestClient) -> None:
    project = create_project(client)
    raw_entry = create_raw_entry(client, project["id"])
    event = create_pending_event(client, project["id"], raw_entry["id"])

    response = client.patch(
        f"/extracted-events/{event['id']}",
        json={"amount": "300.00", "description": "Updated tile work"},
    )

    assert response.status_code == 200
    assert response.json()["amount"] == "300.00"
    assert response.json()["description"] == "Updated tile work"


def test_blocking_edit_after_confirmation(client: TestClient) -> None:
    project = create_project(client)
    raw_entry = create_raw_entry(client, project["id"])
    event = create_pending_event(client, project["id"], raw_entry["id"])
    assert client.post(f"/extracted-events/{event['id']}/confirm").status_code == 200

    response = client.patch(f"/extracted-events/{event['id']}", json={"amount": "300.00"})

    assert response.status_code == 409


def test_blocking_confirm_or_discard_when_event_is_not_pending(client: TestClient) -> None:
    project = create_project(client)
    raw_entry = create_raw_entry(client, project["id"])
    confirmed = create_pending_event(client, project["id"], raw_entry["id"], "MONEY_IN", "100.00")
    discarded = create_pending_event(client, project["id"], raw_entry["id"], "MONEY_OUT", "50.00")

    assert client.post(f"/extracted-events/{confirmed['id']}/confirm").status_code == 200
    assert client.post(f"/extracted-events/{discarded['id']}/discard").status_code == 200

    assert client.post(f"/extracted-events/{confirmed['id']}/confirm").status_code == 409
    assert client.post(f"/extracted-events/{confirmed['id']}/discard").status_code == 409
    assert client.post(f"/extracted-events/{discarded['id']}/confirm").status_code == 409
    assert client.post(f"/extracted-events/{discarded['id']}/discard").status_code == 409
