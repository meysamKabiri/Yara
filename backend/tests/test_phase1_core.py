import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.semantic_rules import EVENT_RULES, ConflictDetectorService, SemanticRuleEngine
from app.dev_tools.semantic_firewall.firewall import (
    SemanticFirewallError,
    SemanticFirewallService,
)
from app.models.core import EventCorrection, HistoryEntry, Worker, WorkerType
from app.services.llm_extraction import extract
from app.services.persian_money_engine import normalize_text, parse_persian_money
from app.services.semantic_normalizer import (
    CanonicalEvent,
    CanonicalEventType,
    SemanticNormalizerService,
)


def create_project(client: TestClient) -> dict:
    response = client.post("/projects", json={"name": "Kitchen remodel"})
    assert response.status_code == 201
    return response.json()


def create_interpretation(client: TestClient, project_id: int, text: str) -> dict:
    response = client.post(f"/projects/{project_id}/natural-input", json={"text": text})
    assert response.status_code == 201
    interpretations = response.json()["interpretations"]
    assert interpretations
    return interpretations[0]


def confirm_interpretation(client: TestClient, interpretation: dict) -> dict:
    response = client.post(f"/pending-interpretations/{interpretation['id']}/confirm")
    assert response.status_code == 200
    return response.json()


def submit_and_confirm(client: TestClient, project_id: int, text: str) -> dict:
    return confirm_interpretation(client, create_interpretation(client, project_id, text))


def create_raw_entry(
    client: TestClient,
    project_id: int,
    text: str = "Paid Dana 250 for tile work",
) -> dict:
    response = client.post(
        f"/projects/{project_id}/raw-entries",
        json={"text": text},
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


def create_worker(
    client: TestClient,
    project_id: int,
    name: str,
    worker_type: str,
    role_detail: str | None = None,
) -> dict:
    payload = {"name": name, "type": worker_type}
    if role_detail is not None:
        payload["role_detail"] = role_detail
    response = client.post(
        f"/projects/{project_id}/workers",
        json=payload,
    )
    assert response.status_code == 201
    return response.json()


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


def test_valid_llm_json_creates_multiple_pending_events(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    raw_entry = create_raw_entry(
        client,
        project["id"],
        "Client paid 1200 and I bought paint for 75",
    )

    monkeypatch.setattr(
        "app.api.projects.extract",
        lambda text: [
            {
                "type": "MONEY_IN",
                "amount_text": "1200",
                "counterparty_name": "Client",
                "counterparty_type": "CLIENT",
                "description": "Client paid 1200",
                "confidence": 0.9,
            },
            {
                "type": "PURCHASE",
                "amount_text": "75",
                "counterparty_name": None,
                "counterparty_type": "UNKNOWN",
                "description": "Bought paint for 75",
                "confidence": 0.8,
            },
        ],
    )

    response = client.post(f"/projects/{project['id']}/raw-entries/{raw_entry['id']}/extract")

    assert response.status_code == 201
    events = response.json()
    assert [event["type"] for event in events] == ["MONEY_IN", "PURCHASE"]
    assert [event["status"] for event in events] == ["PENDING", "PENDING"]
    assert events[0]["amount"] == "1200.00"
    assert events[1]["amount"] == "75.00"


def test_invalid_llm_json_falls_back_to_note(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"response": "not json"}'

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: FakeResponse())

    events = extract("Talked about tomorrow")

    assert events == [
        {
            "raw_type": None,
            "entity_name": None,
            "amount_text": None,
            "unit": None,
            "quantity_text": None,
            "description": "Talked about tomorrow",
            "confidence": 0.3,
        }
    ]


def test_malformed_llm_event_falls_back_to_pending_note(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    raw_entry = create_raw_entry(client, project["id"], "Bad model output")
    monkeypatch.setattr(
        "app.api.projects.extract",
        lambda text: [{"type": "BAD", "amount": "1200"}],
    )

    response = client.post(f"/projects/{project['id']}/raw-entries/{raw_entry['id']}/extract")

    assert response.status_code == 201
    event = response.json()[0]
    assert event["type"] == "NOTE"
    assert event["amount"] is None
    assert event["description"] == "Bad model output"
    assert event["status"] == "PENDING"


def test_llm_numeric_amount_is_ignored_without_amount_text(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    raw_entry = create_raw_entry(client, project["id"], "Client paid 100 million")
    monkeypatch.setattr(
        "app.api.projects.extract",
        lambda text: [
            {
                "type": "MONEY_IN",
                "amount": 100000000,
                "amount_text": None,
                "counterparty_name": "Client",
                "counterparty_type": "CLIENT",
                "description": "Client paid 100 million",
                "confidence": 0.9,
            }
        ],
    )

    response = client.post(f"/projects/{project['id']}/raw-entries/{raw_entry['id']}/extract")

    assert response.status_code == 201
    assert response.json()[0]["amount"] is None


@pytest.mark.parametrize(
    ("amount_text", "expected"),
    [
        ("۱۰۰ میلیون", 100000000),
        ("100 million", 100000000),
        ("۱۰۰ ملیون", 100000000),
        ("100 ملیون", 100000000),
        ("۱۰۰ ملین", 100000000),
        ("۱۰۰ملیون", 100000000),
        ("۱۰۰ ملیونشا", 100000000),
        ("۱۰۰,۰۰۰,۰۰۰", 100000000),
        ("صد میلیون", 100000000),
        ("۲ میلیارد", 2000000000),
        ("2 billion", 2000000000),
        ("۲ میلیاردش", 2000000000),
        ("۱/۵ میلیارد", 1500000000),
        ("1.5 میلیارد", 1500000000),
        ("دو و نیم میلیارد", 2500000000),
        ("۲ و نیم میلیارد", 2500000000),
        ("۵۰۰ هزار", 500000),
        ("500 thousand", 500000),
        ("۵۰۰هزار", 500000),
        ("۱ هزار", 1000),
        ("1000000", 1000000),
        ("امروز ۱۰۰ میلیون از کارفرما گرفتم", 100000000),
        ("invalid text", None),
    ],
)
def test_parse_persian_money(amount_text: str, expected: int | None) -> None:
    assert parse_persian_money(amount_text) == expected


def test_normalize_text_handles_suffix_and_spelling_noise() -> None:
    assert normalize_text("۱۰۰ ملیونشا") == "100 میلیونش را"


def test_extracted_events_do_not_affect_totals_until_confirmation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    raw_entry = create_raw_entry(client, project["id"], "Client paid 1200")
    monkeypatch.setattr(
        "app.api.projects.extract",
        lambda text: [
            {
                "type": "MONEY_IN",
                "amount_text": "1200",
                "counterparty_name": "Client",
                "counterparty_type": "CLIENT",
                "description": "Client paid 1200",
                "confidence": 0.9,
            }
        ],
    )

    extract_response = client.post(
        f"/projects/{project['id']}/raw-entries/{raw_entry['id']}/extract"
    )
    assert extract_response.status_code == 201
    event = extract_response.json()[0]

    response = client.get(f"/projects/{project['id']}")
    assert response.json()["totals"] == {
        "money_in": "0",
        "money_out": "0",
        "net": "0",
    }

    assert client.post(f"/extracted-events/{event['id']}/confirm").status_code == 200
    confirmed_response = client.get(f"/projects/{project['id']}")
    assert confirmed_response.json()["totals"] == {
        "money_in": "1200.00",
        "money_out": "0",
        "net": "1200.00",
    }


def test_confirmed_llm_purchase_updates_totals(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    raw_entry = create_raw_entry(client, project["id"], "Bought supplies for 75")
    monkeypatch.setattr(
        "app.api.projects.extract",
        lambda text: [
            {
                "type": "PURCHASE",
                "amount_text": "75",
                "counterparty_name": None,
                "counterparty_type": "UNKNOWN",
                "description": "Bought supplies for 75",
                "confidence": 0.8,
            }
        ],
    )
    extract_response = client.post(
        f"/projects/{project['id']}/raw-entries/{raw_entry['id']}/extract"
    )
    event = extract_response.json()[0]

    assert client.post(f"/extracted-events/{event['id']}/confirm").status_code == 200
    response = client.get(f"/projects/{project['id']}")

    assert response.json()["totals"] == {
        "money_in": "0",
        "money_out": "75.00",
        "net": "-75.00",
    }


def test_extraction_updates_raw_entry_status_to_processed(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    raw_entry = create_raw_entry(client, project["id"], "Talked to Dana")
    monkeypatch.setattr(
        "app.api.projects.extract",
        lambda text: [
            {
                "type": "NOTE",
                "amount_text": None,
                "counterparty_name": None,
                "counterparty_type": "UNKNOWN",
                "description": text,
                "confidence": 0.3,
            }
        ],
    )

    extract_response = client.post(
        f"/projects/{project['id']}/raw-entries/{raw_entry['id']}/extract"
    )
    assert extract_response.status_code == 201
    response = client.get(f"/projects/{project['id']}/raw-entries")

    assert response.status_code == 200
    assert response.json()[0]["status"] == "PROCESSED"


def test_extraction_failure_marks_raw_entry_failed(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    raw_entry = create_raw_entry(client, project["id"], "Paid 220 for paint")

    def fail_extraction(text: str) -> list:
        raise RuntimeError("extractor failed")

    monkeypatch.setattr("app.api.projects.extract", fail_extraction)
    response = client.post(f"/projects/{project['id']}/raw-entries/{raw_entry['id']}/extract")

    assert response.status_code == 500
    raw_entries_response = client.get(f"/projects/{project['id']}/raw-entries")
    assert raw_entries_response.json()[0]["status"] == "FAILED"


def list_event_corrections(client: TestClient, event_id: int) -> list[EventCorrection]:
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        return list(
            db.scalars(
                select(EventCorrection)
                .where(EventCorrection.event_id == event_id)
                .order_by(EventCorrection.id)
            )
        )


def test_editing_event_creates_event_correction(client: TestClient) -> None:
    project = create_project(client)
    raw_entry = create_raw_entry(client, project["id"])
    event = create_pending_event(client, project["id"], raw_entry["id"], "MONEY_OUT", "250.00")

    response = client.patch(f"/extracted-events/{event['id']}", json={"amount": "300.00"})

    assert response.status_code == 200
    assert response.json()["user_edited"] is True
    corrections = list_event_corrections(client, event["id"])
    assert len(corrections) == 1
    assert corrections[0].field_name == "amount"
    assert corrections[0].old_value == "250.00"
    assert corrections[0].new_value == "300.00"


def test_multiple_field_edits_create_multiple_corrections(client: TestClient) -> None:
    project = create_project(client)
    raw_entry = create_raw_entry(client, project["id"])
    event = create_pending_event(client, project["id"], raw_entry["id"], "MONEY_OUT", "250.00")

    response = client.patch(
        f"/extracted-events/{event['id']}",
        json={
            "type": "PURCHASE",
            "amount": "300.00",
            "counterparty_name": "Paint Store",
        },
    )

    assert response.status_code == 200
    corrections = list_event_corrections(client, event["id"])
    assert [correction.field_name for correction in corrections] == [
        "type",
        "counterparty_name",
        "amount",
    ]


def test_confirming_event_does_not_create_corrections(client: TestClient) -> None:
    project = create_project(client)
    raw_entry = create_raw_entry(client, project["id"])
    event = create_pending_event(client, project["id"], raw_entry["id"], "MONEY_IN", "100.00")

    response = client.post(f"/extracted-events/{event['id']}/confirm")

    assert response.status_code == 200
    assert list_event_corrections(client, event["id"]) == []


def test_totals_remain_unaffected_by_pending_edits(client: TestClient) -> None:
    project = create_project(client)
    raw_entry = create_raw_entry(client, project["id"])
    event = create_pending_event(client, project["id"], raw_entry["id"], "MONEY_IN", "100.00")

    edit_response = client.patch(f"/extracted-events/{event['id']}", json={"amount": "999.00"})
    assert edit_response.status_code == 200
    response = client.get(f"/projects/{project['id']}")

    assert response.json()["totals"] == {
        "money_in": "0",
        "money_out": "0",
        "net": "0",
    }


def test_project_analytics_returns_validation_counts(client: TestClient) -> None:
    project = create_project(client)
    raw_entry = create_raw_entry(client, project["id"])
    edited = create_pending_event(client, project["id"], raw_entry["id"], "MONEY_IN", "100.00")
    confirmed = create_pending_event(client, project["id"], raw_entry["id"], "MONEY_OUT", "25.00")
    discarded = create_pending_event(client, project["id"], raw_entry["id"], "PURCHASE", "10.00")

    edit_response = client.patch(f"/extracted-events/{edited['id']}", json={"amount": "150.00"})
    assert edit_response.status_code == 200
    assert client.post(f"/extracted-events/{confirmed['id']}/confirm").status_code == 200
    assert client.post(f"/extracted-events/{discarded['id']}/discard").status_code == 200

    response = client.get(f"/analytics/projects/{project['id']}")

    assert response.status_code == 200
    assert response.json() == {
        "total_raw_entries": 1,
        "total_extracted_events": 3,
        "confirmed_events": 1,
        "discarded_events": 1,
        "edited_events_count": 1,
        "edit_rate": 1 / 3,
    }


def test_daily_worker_calculation(client: TestClient) -> None:
    project = create_project(client)
    worker = create_worker(client, project["id"], "Ali", "DAILY_WORKER")

    response = client.post(
        f"/projects/{project['id']}/work-logs",
        json={
            "worker_id": worker["id"],
            "task_name": "Daily labor",
            "unit": "day",
            "quantity": "10",
            "rate_per_unit": "500000",
            "description": "10 days work",
        },
    )

    assert response.status_code == 201
    assert response.json()["total_amount"] == "5000000.00"


def test_skilled_worker_progress_updates_accumulate_over_time(client: TestClient) -> None:
    project = create_project(client)
    worker = create_worker(client, project["id"], "Reza", "SKILLED_WORKER")

    first = client.post(
        f"/projects/{project['id']}/work-logs",
        json={
            "worker_id": worker["id"],
            "task_name": "Wiring",
            "unit": "meter",
            "quantity": "40",
            "rate_per_unit": "200000",
        },
    )
    second = client.post(
        f"/projects/{project['id']}/work-logs",
        json={
            "worker_id": worker["id"],
            "task_name": "Wiring",
            "unit": "meter",
            "quantity": "10",
            "rate_per_unit": "200000",
        },
    )
    logs = client.get(f"/projects/{project['id']}/work-logs").json()

    assert first.status_code == 201
    assert second.status_code == 201
    assert sum(float(log["quantity"]) for log in logs) == 50
    assert sum(float(log["total_amount"] or 0) for log in logs) == 10000000


def test_skilled_worker_type_and_state_are_preserved(client: TestClient) -> None:
    project = create_project(client)
    worker = create_worker(
        client,
        project["id"],
        "نادری جوشکار",
        "SKILLED_WORKER",
        role_detail="جوشکار",
    )

    response = client.post(
        f"/projects/{project['id']}/payments",
        json={"entity_id": worker["id"], "amount": "1000000", "type": "CASH"},
    )
    workers = client.get(f"/projects/{project['id']}/workers").json()
    states = client.get(f"/projects/{project['id']}/worker-states").json()

    assert response.status_code == 201
    assert workers[0]["type"] == "SKILLED_WORKER"
    assert states[0]["role"] == "SKILLED"


def test_legacy_daily_worker_with_skilled_detail_displays_as_skilled(client: TestClient) -> None:
    project = create_project(client)
    worker = create_worker(
        client,
        project["id"],
        "برقکار کیانی",
        "DAILY_WORKER",
        role_detail="برقکار",
    )
    response = client.post(
        f"/projects/{project['id']}/payments",
        json={"entity_id": worker["id"], "amount": "1000000", "type": "CASH"},
    )

    assert response.status_code == 201
    workers = client.get(f"/projects/{project['id']}/workers").json()
    states = client.get(f"/projects/{project['id']}/worker-states").json()

    assert workers[0]["type"] == "SKILLED_WORKER"
    assert states[0]["role"] == "SKILLED"


def test_invoice_partial_payment_updates_invoice_status(client: TestClient) -> None:
    project = create_project(client)
    vendor = create_worker(client, project["id"], "Paint Store", "VENDOR")
    invoice = client.post(
        f"/projects/{project['id']}/invoices",
        json={"vendor_id": vendor["id"], "total_amount": "1000000", "description": "Paint"},
    ).json()

    response = client.post(
        f"/projects/{project['id']}/payments",
        json={
            "entity_id": vendor["id"],
            "amount": "400000",
            "related_invoice_id": invoice["id"],
            "type": "BANK_TRANSFER",
        },
    )
    invoices = client.get(f"/projects/{project['id']}/invoices").json()

    assert response.status_code == 201
    assert invoices[0]["status"] == "PARTIAL"


def test_vendor_debt_calculation(client: TestClient) -> None:
    project = create_project(client)
    vendor = create_worker(client, project["id"], "Steel Vendor", "VENDOR")
    invoice = client.post(
        f"/projects/{project['id']}/invoices",
        json={"vendor_id": vendor["id"], "total_amount": "5000000"},
    ).json()
    assert client.post(
        f"/projects/{project['id']}/payments",
        json={
            "entity_id": vendor["id"],
            "amount": "1500000",
            "related_invoice_id": invoice["id"],
            "type": "CASH",
        },
    ).status_code == 201

    response = client.get(f"/projects/{project['id']}/operating-summary")

    assert response.status_code == 200
    assert response.json()["vendor_debts"] == [
        {
            "vendor_id": vendor["id"],
            "vendor_name": "Steel Vendor",
            "invoice_total": "5000000.00",
            "paid_total": "1500000.00",
            "debt": "3500000.00",
        }
    ]


def test_work_log_edit_recalculates_total(client: TestClient) -> None:
    project = create_project(client)
    worker = create_worker(client, project["id"], "Sara", "SKILLED_WORKER")
    work_log = client.post(
        f"/projects/{project['id']}/work-logs",
        json={
            "worker_id": worker["id"],
            "task_name": "Tile",
            "unit": "meter",
            "quantity": "10",
            "rate_per_unit": "100000",
        },
    ).json()

    response = client.patch(f"/work-logs/{work_log['id']}", json={"quantity": "12"})

    assert response.status_code == 200
    assert response.json()["total_amount"] == "1200000.00"


def test_natural_input_setup_creates_client_entity(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {
            "intent": "SETUP",
            "entities": [{"name": "میثم کبیری", "role_guess": "CLIENT"}],
            "events": [],
        },
    )

    interpretation = create_interpretation(client, project["id"], "کارفرمای پروژه میثم کبیری است")
    assert client.get(f"/projects/{project['id']}/workers").json() == []
    response = confirm_interpretation(client, interpretation)

    assert response["workers"][0]["name"] == "میثم کبیری"
    assert response["workers"][0]["type"] == "CLIENT"
    assert response["states"] == []
    assert response["history_entries"][0]["change_type"] == "SETUP"


def test_natural_input_setup_updates_existing_entity_phone(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    responses = [
        {
            "intent": "SETUP",
            "entities": [
                {
                    "type": "CLIENT",
                    "name": "میثم کبیری",
                    "phone": None,
                    "account_number": None,
                    "role_detail": None,
                }
            ],
            "confidence": 0.9,
        },
        {
            "intent": "SETUP",
            "entities": [
                {
                    "type": "CLIENT",
                    "name": "میثم کبیری",
                    "phone": "09130000000",
                    "account_number": None,
                    "role_detail": None,
                }
            ],
            "confidence": 0.9,
        },
    ]
    monkeypatch.setattr("app.api.projects.extract_graph", lambda text: responses.pop(0))

    submit_and_confirm(client, project["id"], "کارفرمای پروژه میثم کبیری است")
    submit_and_confirm(client, project["id"], "شماره تماس میثم کبیری 09130000000")
    workers = client.get(f"/projects/{project['id']}/workers").json()

    assert len(workers) == 1
    assert workers[0]["phone"] == "09130000000"


def test_natural_input_entity_update_updates_existing_entity(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    responses = [
        {
            "intent": "SETUP",
            "entities": [
                {
                    "type": "CLIENT",
                    "name": "میثم کبیری",
                    "phone": None,
                    "account_number": None,
                    "role_detail": None,
                }
            ],
            "confidence": 0.9,
        },
        {
            "intent": "ENTITY_UPDATE",
            "entities": [
                {
                    "type": "CLIENT",
                    "name": "میثم کبیری",
                    "field_updates": {
                        "phone": "09130000000",
                        "account_number": None,
                        "role_detail": None,
                    },
                }
            ],
            "confidence": 0.9,
        },
    ]
    monkeypatch.setattr("app.api.projects.extract_graph", lambda text: responses.pop(0))

    submit_and_confirm(client, project["id"], "کارفرمای پروژه میثم کبیری است")
    response = submit_and_confirm(client, project["id"], "شماره تماس میثم کبیری 09130000000")

    assert response["intent"] == "SETUP_EVENT"
    assert response["workers"][0]["phone"] == "09130000000"
    assert response["history_entries"][0]["change_type"] == "ENTITY_UPDATE"


def test_note_with_existing_entity_context_becomes_entity_update(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    responses = [
        {
            "intent": "SETUP",
            "entities": [
                {
                    "type": "WORKER",
                    "name": "مش رحیم",
                    "phone": None,
                    "account_number": None,
                    "role_detail": None,
                }
            ],
            "confidence": 0.9,
        },
        {"intent": "NOTE", "entity": None, "entities": [], "confidence": 0.3},
    ]
    monkeypatch.setattr("app.api.projects.extract_graph", lambda text: responses.pop(0))

    submit_and_confirm(client, project["id"], "مش رحیم کارگر پروژه است")
    response = submit_and_confirm(client, project["id"], "شماره تماس رحیم 09131111111")
    workers = client.get(f"/projects/{project['id']}/workers").json()

    assert response["intent"] == "SETUP_EVENT"
    assert len(workers) == 1
    assert workers[0]["phone"] == "09131111111"


def test_natural_input_setup_creates_multiple_workers(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {
            "intent": "SETUP",
            "entities": [
                {
                    "type": "WORKER",
                    "name": "مش رحیم",
                    "phone": None,
                    "account_number": None,
                    "role_detail": None,
                },
                {
                    "type": "WORKER",
                    "name": "مش سهراب",
                    "phone": None,
                    "account_number": None,
                    "role_detail": None,
                },
            ],
            "confidence": 0.9,
        },
    )

    response = submit_and_confirm(client, project["id"], "کارگرها مش رحیم و مش سهراب هستند")

    assert {worker["name"] for worker in response["workers"]} == {"مش رحیم", "مش سهراب"}


def test_setup_sentence_with_multiple_daily_workers_creates_one_pending_draft(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {"intent": "NOTE", "entities": [], "confidence": 0.4},
    )

    interpretation = create_interpretation(
        client,
        project["id"],
        "مش رحیم و آقای صابری به عنوان کارگر ساده در پروژه کار می‌کنند",
    )

    assert interpretation["canonical_event_type"] == "SETUP_EVENT"
    assert interpretation["semantic_action"] == "SETUP"
    assert [entity["name"] for entity in interpretation["extracted_entities"]] == [
        "مش رحیم",
        "آقای صابری",
    ]
    assert all(entity["type"] == "DAILY_WORKER" for entity in interpretation["extracted_entities"])
    assert client.get(f"/projects/{project['id']}/workers").json() == []


def test_confirming_multi_entity_setup_creates_workers_without_states(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {"intent": "NOTE", "entities": [], "confidence": 0.4},
    )

    response = submit_and_confirm(
        client,
        project["id"],
        "مش رحیم و آقای صابری به عنوان کارگر ساده در پروژه کار می‌کنند",
    )
    workers = client.get(f"/projects/{project['id']}/workers").json()

    assert {worker["name"] for worker in response["workers"]} == {"مش رحیم", "آقای صابری"}
    assert {worker["type"] for worker in response["workers"]} == {"DAILY_WORKER"}
    assert {worker["name"] for worker in workers} == {"مش رحیم", "آقای صابری"}
    assert client.get(f"/projects/{project['id']}/worker-states").json() == []


def test_multi_entity_setup_does_not_recreate_existing_worker(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    existing = create_worker(client, project["id"], "مش رحیم", "DAILY_WORKER")
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {"intent": "NOTE", "entities": [], "confidence": 0.4},
    )

    submit_and_confirm(
        client,
        project["id"],
        "مش رحیم و آقای صابری به عنوان کارگر ساده در پروژه کار می‌کنند",
    )
    workers = client.get(f"/projects/{project['id']}/workers").json()

    assert len(workers) == 2
    assert [worker for worker in workers if worker["name"] == "مش رحیم"][0]["id"] == existing["id"]


def test_editing_multi_entity_setup_can_remove_one_before_confirm(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {"intent": "NOTE", "entities": [], "confidence": 0.4},
    )
    interpretation = create_interpretation(
        client,
        project["id"],
        "مش رحیم و آقای صابری به عنوان کارگر ساده در پروژه کار می‌کنند",
    )

    edit = client.patch(
        f"/pending-interpretations/{interpretation['id']}",
        json={"extracted_entities": [interpretation["extracted_entities"][1]]},
    )
    response = confirm_interpretation(client, edit.json())

    assert edit.status_code == 200
    assert [worker["name"] for worker in response["workers"]] == ["آقای صابری"]
    assert client.get(f"/projects/{project['id']}/worker-states").json() == []


def test_natural_input_work_creates_daily_work_log(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {
            "intent": "WORK",
            "entities": [{"name": "مش رحیم", "role_guess": "WORKER"}],
            "events": [
                {
                    "type": "WORK_LOG",
                    "quantity_text": "۳",
                    "unit": "روز",
                    "amount_text": None,
                    "description": "مش رحیم امروز ۳ روز کار کرد",
                }
            ],
        },
    )

    interpretation = create_interpretation(client, project["id"], "مش رحیم امروز ۳ روز کار کرد")
    assert client.get(f"/projects/{project['id']}/worker-states").json() == []
    response = confirm_interpretation(client, interpretation)

    assert response["work_logs"][0]["quantity"] == "3.00"
    assert response["work_logs"][0]["unit"] == "day"
    assert response["states"][0]["total_days_worked"] == "3.00"


def test_natural_input_daily_work_defaults_to_one_day(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {
            "intent": "WORK",
            "entity": "مش رحیم",
            "action": "INCREMENT",
            "confidence": 0.8,
        },
    )

    first = submit_and_confirm(client, project["id"], "مش رحیم امروز کار کرد")
    second = submit_and_confirm(client, project["id"], "مش رحیم امروز کار کرد")
    states = client.get(f"/projects/{project['id']}/worker-states")
    history = client.get(f"/projects/{project['id']}/history")

    assert first["intent"] == "WORK_EVENT"
    assert second["intent"] == "WORK_EVENT"
    assert states.json()[0]["total_days_worked"] == "2.00"
    assert len(history.json()) == 2


def test_natural_input_payment_creates_payment(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    create_worker(client, project["id"], "جوشکار", "SKILLED_WORKER")
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {
            "intent": "PAYMENT",
            "entities": [{"name": "جوشکار", "role_guess": "WORKER"}],
            "events": [
                {
                    "type": "PAYMENT",
                    "amount_text": "۱۰۰ میلیون",
                    "quantity_text": None,
                    "unit": None,
                    "description": "۱۰۰ میلیون دادم به جوشکار",
                }
            ],
        },
    )

    interpretation = create_interpretation(client, project["id"], "۱۰۰ میلیون دادم به جوشکار")
    assert client.get(f"/projects/{project['id']}/payments").json() == []
    response = confirm_interpretation(client, interpretation)

    assert response["payments"][0]["amount"] == "100000000.00"
    assert response["payments"][0]["direction"] == "OUTGOING"
    assert response["states"][0]["financial_balance"] == "-100000000.00"


def test_existing_client_partial_match_creates_incoming_payment_draft(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    client_worker = create_worker(client, project["id"], "میثم کبیری", "CLIENT")
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {"intent": "PAYMENT", "entity": "میثم", "confidence": 0.9},
    )

    interpretation = create_interpretation(
        client,
        project["id"],
        "میثم ۲۰۰ ملیون پول داد برای شروع پروژه",
    )
    workers = client.get(f"/projects/{project['id']}/workers").json()

    assert interpretation["suggested_entity_id"] == client_worker["id"]
    assert interpretation["matched_input_text"] == "میثم"
    assert interpretation["extracted_entities"][0]["name"] == "میثم کبیری"
    assert interpretation["financial_direction"] == "INCOMING"
    assert [worker["name"] for worker in workers] == ["میثم کبیری"]


def test_confirming_client_payment_is_incoming_without_duplicate_entity(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    client_worker = create_worker(client, project["id"], "میثم کبیری", "CLIENT")
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {"intent": "PAYMENT", "entity": "میثم", "confidence": 0.9},
    )

    interpretation = create_interpretation(
        client,
        project["id"],
        "میثم ۲۰۰ ملیون پول داد برای شروع پروژه",
    )
    response = confirm_interpretation(client, interpretation)
    workers = client.get(f"/projects/{project['id']}/workers").json()
    summary = client.get(f"/projects/{project['id']}/operating-summary").json()

    assert response["payments"][0]["entity_id"] == client_worker["id"]
    assert response["payments"][0]["amount"] == "200000000.00"
    assert response["payments"][0]["direction"] == "INCOMING"
    assert response["states"][0]["role"] == "CLIENT"
    assert response["states"][0]["financial_balance"] == "200000000.00"
    assert [worker["name"] for worker in workers] == ["میثم کبیری"]
    assert summary["total_received"] == "200000000.00"
    assert summary["total_paid_out"] == "0.00"


def test_multiple_partial_entity_matches_require_selection(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    create_worker(client, project["id"], "میثم کبیری", "CLIENT")
    create_worker(client, project["id"], "میثم رضایی", "DAILY_WORKER")
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {"intent": "PAYMENT", "entity": "میثم", "confidence": 0.9},
    )

    interpretation = create_interpretation(client, project["id"], "میثم ۲۰۰ ملیون پول داد")
    response = client.post(f"/pending-interpretations/{interpretation['id']}/confirm")

    assert interpretation["suggested_entity_id"] is None
    assert response.status_code == 409
    assert client.get(f"/projects/{project['id']}/payments").json() == []


def test_unknown_financial_entity_cannot_confirm_without_resolution(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {"intent": "PAYMENT", "entity": "ناشناس", "confidence": 0.9},
    )

    interpretation = create_interpretation(client, project["id"], "ناشناس ۲۰۰ ملیون پول داد")
    response = client.post(f"/pending-interpretations/{interpretation['id']}/confirm")

    assert interpretation["suggested_entity_id"] is None
    assert response.status_code == 409
    assert client.get(f"/projects/{project['id']}/payments").json() == []


def test_natural_input_invoice_creates_vendor_debt(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    create_worker(client, project["id"], "جوشکار", "VENDOR")
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {
            "intent": "INVOICE",
            "entities": [{"name": "جوشکار", "role_guess": "VENDOR"}],
            "events": [
                {
                    "type": "INVOICE",
                    "amount_text": "۳۴۵ میلیون",
                    "quantity_text": None,
                    "unit": None,
                    "description": "جوشکار فاکتور ۳۴۵ میلیونی داده",
                }
            ],
        },
    )

    interpretation = create_interpretation(client, project["id"], "جوشکار فاکتور ۳۴۵ میلیونی داده")
    assert client.get(f"/projects/{project['id']}/invoices").json() == []
    response = confirm_interpretation(client, interpretation)
    summary = client.get(f"/projects/{project['id']}/operating-summary")

    assert response["invoices"][0]["total_amount"] == "345000000.00"
    assert response["states"][0]["financial_balance"] == "345000000.00"
    assert summary.json()["vendor_debts"][0]["debt"] == "345000000.00"


def test_purchase_with_money_defaults_to_paid_purchase(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    create_worker(client, project["id"], "هادی‌پور سیم", "VENDOR")
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {
            "intent": "INVOICE",
            "entity": "هادی‌پور سیم",
            "action": "INVOICE",
            "confidence": 0.9,
        },
    )

    interpretation = create_interpretation(client, project["id"], "از هادی‌پور سیم ۵ میلیون خرید کردم")
    assert client.get(f"/projects/{project['id']}/payments").json() == []
    response = confirm_interpretation(client, interpretation)
    summary = client.get(f"/projects/{project['id']}/operating-summary").json()

    assert response["payments"][0]["amount"] == "5000000.00"
    assert response["payments"][0]["type"] == "BANK_TRANSFER"
    assert response["payments"][0]["direction"] == "OUTGOING"
    assert response["invoices"] == []
    explanation = response["history_entries"][0]["explanation"]
    assert explanation["semantic_action"] == "PURCHASE_PAID"
    assert response["states"][0]["financial_balance"] == "0.00"
    assert summary["total_paid_out"] == "5000000.00"
    assert summary["total_received"] == "0.00"
    assert sum(float(debt["debt"]) for debt in summary["vendor_debts"]) == 0


def test_material_purchase_without_money_does_not_create_payment_or_debt(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {"intent": "NOTE", "entities": [], "confidence": 0.5},
    )

    response = confirm_interpretation(
        client,
        create_interpretation(client, project["id"], "۲۰ متر سیم خریدم"),
    )

    assert response["payments"] == []
    assert response["invoices"] == []
    assert response["history_entries"][0]["change_type"] == "NOTE"


def test_unpaid_purchase_creates_debt(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    create_worker(client, project["id"], "هادی‌پور سیم", "VENDOR")
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {
            "intent": "PAYMENT",
            "entity": "هادی‌پور سیم",
            "action": "PAYMENT",
            "confidence": 0.9,
        },
    )

    response = submit_and_confirm(client, project["id"], "۵ میلیون خرید کردم ولی پولش را هنوز ندادم")
    summary = client.get(f"/projects/{project['id']}/operating-summary").json()

    assert response["invoices"][0]["total_amount"] == "5000000.00"
    assert response["payments"] == []
    assert response["history_entries"][0]["explanation"]["semantic_action"] == "DEBT_CREATED"
    assert response["states"][0]["financial_balance"] == "5000000.00"
    assert summary["vendor_debts"][0]["debt"] == "5000000.00"
    assert summary["total_paid_out"] == "0.00"


def test_payment_against_existing_invoice_reduces_payables(client: TestClient) -> None:
    project = create_project(client)
    vendor = create_worker(client, project["id"], "هادی‌پور سیم", "VENDOR")
    invoice = client.post(
        f"/projects/{project['id']}/invoices",
        json={"vendor_id": vendor["id"], "total_amount": "5000000", "description": "wire"},
    ).json()

    before = client.get(f"/projects/{project['id']}/operating-summary").json()
    payment = client.post(
        f"/projects/{project['id']}/payments",
        json={
            "entity_id": vendor["id"],
            "amount": "5000000",
            "related_invoice_id": invoice["id"],
            "type": "BANK_TRANSFER",
            "direction": "OUTGOING",
        },
    )
    after = client.get(f"/projects/{project['id']}/operating-summary").json()

    assert payment.status_code == 201
    assert before["vendor_debts"][0]["debt"] == "5000000.00"
    assert after["vendor_debts"][0]["debt"] == "0.00"
    assert after["total_paid_out"] == "5000000.00"


def test_client_receivable_equals_paid_out_when_client_paid_nothing(client: TestClient) -> None:
    project = create_project(client)
    vendor = create_worker(client, project["id"], "هادی‌پور سیم", "VENDOR")
    client.post(
        f"/projects/{project['id']}/payments",
        json={"entity_id": vendor["id"], "amount": "105000000", "type": "BANK_TRANSFER"},
    )

    summary = client.get(f"/projects/{project['id']}/operating-summary").json()

    assert summary["total_received_from_client"] == "0.00"
    assert summary["total_paid_out"] == "105000000.00"
    assert summary["open_payables"] == "0"
    assert summary["project_balance"] == "-105000000.00"
    assert summary["client_receivable"] == "105000000.00"
    assert summary["available_balance"] == "0"


def test_client_receivable_accounts_for_partial_client_payment(client: TestClient) -> None:
    project = create_project(client)
    owner = create_worker(client, project["id"], "میثم کبیری", "CLIENT")
    vendor = create_worker(client, project["id"], "هادی‌پور سیم", "VENDOR")
    client.post(
        f"/projects/{project['id']}/payments",
        json={"entity_id": owner["id"], "amount": "50000000", "type": "BANK_TRANSFER", "direction": "INCOMING"},
    )
    client.post(
        f"/projects/{project['id']}/payments",
        json={"entity_id": vendor["id"], "amount": "105000000", "type": "BANK_TRANSFER"},
    )

    summary = client.get(f"/projects/{project['id']}/operating-summary").json()

    assert summary["project_balance"] == "-55000000.00"
    assert summary["client_receivable"] == "55000000.00"
    assert summary["available_balance"] == "0"


def test_available_balance_when_client_overfunds_project(client: TestClient) -> None:
    project = create_project(client)
    owner = create_worker(client, project["id"], "میثم کبیری", "CLIENT")
    vendor = create_worker(client, project["id"], "هادی‌پور سیم", "VENDOR")
    client.post(
        f"/projects/{project['id']}/payments",
        json={"entity_id": owner["id"], "amount": "120000000", "type": "BANK_TRANSFER", "direction": "INCOMING"},
    )
    client.post(
        f"/projects/{project['id']}/payments",
        json={"entity_id": vendor["id"], "amount": "105000000", "type": "BANK_TRANSFER"},
    )

    summary = client.get(f"/projects/{project['id']}/operating-summary").json()

    assert summary["project_balance"] == "15000000.00"
    assert summary["client_receivable"] == "0"
    assert summary["available_balance"] == "15000000.00"


def test_open_payables_increase_client_receivable_separately(client: TestClient) -> None:
    project = create_project(client)
    vendor = create_worker(client, project["id"], "هادی‌پور سیم", "VENDOR")
    client.post(
        f"/projects/{project['id']}/payments",
        json={"entity_id": vendor["id"], "amount": "50000000", "type": "BANK_TRANSFER"},
    )
    client.post(
        f"/projects/{project['id']}/invoices",
        json={"vendor_id": vendor["id"], "total_amount": "25000000", "description": "unpaid materials"},
    )

    summary = client.get(f"/projects/{project['id']}/operating-summary").json()

    assert summary["total_paid_out"] == "50000000.00"
    assert summary["open_payables"] == "25000000.00"
    assert summary["client_receivable"] == "75000000.00"
    assert summary["vendor_debts"][0]["debt"] == "25000000.00"


def test_check_purchase_records_deferred_payment_due_date(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    create_worker(client, project["id"], "رفیعی سرامیک", "VENDOR")
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {
            "intent": "PAYMENT",
            "entity": "رفیعی سرامیک",
            "action": "PAYMENT",
            "confidence": 0.9,
        },
    )

    response = submit_and_confirm(
        client,
        project["id"],
        "۵۰ میلیون سرامیک خریدم برای ۱۴ مهر ۱۴۰۵ چک دادم",
    )

    assert response["payments"][0]["amount"] == "50000000.00"
    assert response["payments"][0]["type"] == "CHECK"
    assert response["payments"][0]["direction"] == "DEFERRED"
    assert response["payments"][0]["due_date"] == "14 مهر 1405"
    assert response["invoices"] == []
    explanation = response["history_entries"][0]["explanation"]
    assert explanation["semantic_action"] == "CHECK_PAYMENT"


def test_discard_pending_interpretation_has_no_side_effects(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    create_worker(client, project["id"], "جوشکار", "SKILLED_WORKER")
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {"intent": "WORK", "entity": "مش رحیم", "confidence": 0.8},
    )
    interpretation = create_interpretation(client, project["id"], "مش رحیم امروز کار کرد")

    response = client.post(f"/pending-interpretations/{interpretation['id']}/discard")

    assert response.status_code == 200
    assert response.json()["status"] == "DISCARDED"
    assert client.get(f"/projects/{project['id']}/worker-states").json() == []
    assert client.get(f"/projects/{project['id']}/history").json() == []


def test_edit_pending_interpretation_executes_edited_values(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    create_worker(client, project["id"], "جوشکار", "SKILLED_WORKER")
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {"intent": "PAYMENT", "entity": "جوشکار", "confidence": 0.8},
    )
    interpretation = create_interpretation(client, project["id"], "۱۰۰ میلیون دادم به جوشکار")
    edit = client.patch(
        f"/pending-interpretations/{interpretation['id']}",
        json={"extracted_amount": "75000000", "description": "edited payment"},
    )

    response = confirm_interpretation(client, edit.json())

    assert edit.status_code == 200
    assert edit.json()["status"] == "EDITED"
    assert response["payments"][0]["amount"] == "75000000.00"
    assert response["payments"][0]["amount"] != "100000000.00"


def test_multiple_extracted_actions_create_independent_interpretations(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    create_worker(client, project["id"], "جوشکار", "SKILLED_WORKER")
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {
            "intent": "PAYMENT",
            "entities": [{"name": "جوشکار", "role_guess": "WORKER"}],
            "events": [
                {"type": "PAYMENT", "amount_text": "۱ میلیون", "description": "first"},
                {"type": "PAYMENT", "amount_text": "۲ میلیون", "description": "second"},
            ],
        },
    )

    response = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "۱ میلیون و ۲ میلیون دادم به جوشکار"},
    )

    assert response.status_code == 201
    interpretations = response.json()["interpretations"]
    assert len(interpretations) == 2
    first = confirm_interpretation(client, interpretations[0])
    assert first["payments"][0]["amount"] == "1000000.00"
    assert client.get(f"/projects/{project['id']}/payments").json()[0]["amount"] == "1000000.00"


def test_natural_input_skilled_work_defaults_to_one_unit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client)
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {
            "intent": "WORK",
            "entity": "نادری جوشکار",
            "action": "INCREMENT",
            "confidence": 0.8,
        },
    )

    response = submit_and_confirm(client, project["id"], "نادری جوشکار امروز اومد و جوش زد")
    workers = client.get(f"/projects/{project['id']}/workers").json()

    assert response["workers"][0]["type"] == "SKILLED_WORKER"
    assert response["states"][0]["role"] == "SKILLED"
    assert response["states"][0]["total_quantity"] == "1.00"
    assert response["history_entries"][0]["change_type"] == "WORK"
    assert workers[0]["type"] == "SKILLED_WORKER"


def test_semantic_normalizer_classifies_implicit_work() -> None:
    event = SemanticNormalizerService().normalize(
        {"intent": "NOTE", "entity": "مش رحیم", "confidence": 0.3},
        "مش رحیم امروز کار کرد",
        [],
    )

    assert event.type == CanonicalEventType.WORK
    assert event.action == "INCREMENT"


def test_semantic_normalizer_classifies_financial_text() -> None:
    event = SemanticNormalizerService().normalize(
        {"intent": "NOTE", "entities": [], "confidence": 0.3},
        "۱۰۰ میلیون دادم",
        [],
    )

    assert event.type == CanonicalEventType.FINANCIAL
    assert event.action == "PAYMENT"


def test_semantic_normalizer_classifies_setup_text() -> None:
    event = SemanticNormalizerService().normalize(
        {
            "intent": "NOTE",
            "entities": [{"name": "میثم کبیری", "type": "CLIENT"}],
            "confidence": 0.3,
        },
        "کارفرما میثم کبیری است",
        [],
    )

    assert event.type == CanonicalEventType.SETUP


def test_semantic_normalizer_keeps_ambiguous_text_as_note() -> None:
    event = SemanticNormalizerService().normalize(
        {"intent": "NOTE", "entities": [], "confidence": 0.3},
        "یادم باشد بعدا بررسی کنم",
        [],
    )

    assert event.type == CanonicalEventType.NOTE


def test_known_entity_today_context_does_not_become_note() -> None:
    worker = Worker(id=1, project_id=1, name="مش رحیم", type=WorkerType.DAILY_WORKER)
    event = SemanticNormalizerService().normalize(
        {"intent": "NOTE", "entity": None, "entities": [], "confidence": 0.3},
        "رحیم امروز",
        [worker],
    )

    assert event.type == CanonicalEventType.WORK


def test_firewall_reclassifies_illegal_note_financial_input() -> None:
    event = CanonicalEvent(
        type=CanonicalEventType.NOTE,
        entity_id=None,
        entity_name=None,
        action="NOTE",
        metadata={"confidence": 0.3, "source_text": "۱۰۰ میلیون دادم"},
    )

    decision = SemanticFirewallService().validate(event, "۱۰۰ میلیون دادم", [], {})

    assert decision.status == "FIXED"
    assert decision.event.type == CanonicalEventType.FINANCIAL


def test_firewall_blocks_known_entity_note_without_action() -> None:
    worker = Worker(id=1, project_id=1, name="مش رحیم", type=WorkerType.DAILY_WORKER)
    event = CanonicalEvent(
        type=CanonicalEventType.NOTE,
        entity_id=worker.id,
        entity_name=worker.name,
        action="NOTE",
        metadata={"confidence": 0.3, "source_text": "رحیم"},
    )

    with pytest.raises(SemanticFirewallError):
        SemanticFirewallService().validate(event, "رحیم", [worker], {})


def test_semantic_rule_engine_defines_all_canonical_events() -> None:
    assert set(EVENT_RULES) == {"SETUP_EVENT", "WORK_EVENT", "FINANCIAL_EVENT", "NOTE_EVENT"}
    assert EVENT_RULES["FINANCIAL_EVENT"]["priority"] < EVENT_RULES["WORK_EVENT"]["priority"]


def test_llm_raw_intent_does_not_control_classification() -> None:
    event = SemanticRuleEngine().classify(
        {"raw_intent": "NOTE", "intent": "NOTE", "entity": "مش رحیم", "confidence": 0.1},
        "مش رحیم امروز کار کرد",
        [],
    )

    assert event.type == CanonicalEventType.WORK


def test_semantic_explanation_generated_for_classification() -> None:
    event = SemanticRuleEngine().classify(
        {"intent": "NOTE", "entity": "مش رحیم", "confidence": 0.92},
        "مش رحیم امروز کار کرد",
        [],
    )

    explanation = event.metadata["semantic_explanation"]
    assert explanation["event_type"] == "WORK_EVENT"
    assert explanation["triggered_rule"] == "WORK_RULE_01"
    assert "کار کرد" in explanation["matched_signals"]
    assert explanation["decision_path"][-1] == "event classified as WORK_EVENT"


def test_conflict_detector_finds_overlapping_priority_collision() -> None:
    rules = {
        "WORK_EVENT": {
            "rule_id": "WORK_RULE_01",
            "event_type": "WORK_EVENT",
            "triggers": {"keywords": ["دادم"], "patterns": []},
            "priority": 1,
        },
        "FINANCIAL_EVENT": {
            "rule_id": "FINANCIAL_RULE_03",
            "event_type": "FINANCIAL_EVENT",
            "triggers": {"keywords": ["دادم"], "patterns": []},
            "priority": 1,
        },
        "NOTE_EVENT": {
            "rule_id": "NOTE_RULE_01",
            "event_type": "NOTE_EVENT",
            "triggers": {"keywords": [], "patterns": ["no_action"]},
            "fallback": None,
        },
    }

    report = ConflictDetectorService().audit(rules)

    assert report["severity"] == "HIGH"
    assert {conflict["type"] for conflict in report["conflicts"]} == {
        "OVERLAPPING_RULES",
        "PRIORITY_COLLISION",
    }


def test_conflict_detector_flags_ambiguous_input() -> None:
    report = ConflictDetectorService().audit_text(
        "رحیم امروز متر کار کرد و پول دادم",
        [
            {"rule_id": "WORK_RULE_01", "event_type": "WORK_EVENT", "confidence": 0.82},
            {
                "rule_id": "FINANCIAL_RULE_01",
                "event_type": "FINANCIAL_EVENT",
                "confidence": 0.8,
            },
        ],
    )

    assert report["severity"] == "HIGH"
    assert report["conflicts"][0]["type"] == "AMBIGUOUS_CLASSIFICATION_ZONE"


def test_history_entry_contains_full_semantic_traceability(client, monkeypatch) -> None:
    project = create_project(client)
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {
            "intent": "WORK",
            "entity": "نادری جوشکار",
            "action": "INCREMENT",
            "confidence": 0.88,
        },
    )

    response = submit_and_confirm(client, project["id"], "نادری جوشکار امروز کار کرد")

    history = response["history_entries"][0]
    assert history["rule_id"] == "WORK_RULE_01"
    assert history["explanation"]["event_type"] == "WORK_EVENT"
    assert history["conflict_warnings"] == []

    with client.app.state.testing_session_factory() as db:
        stored = db.scalar(select(HistoryEntry).where(HistoryEntry.id == history["id"]))
        assert stored.rule_id == "WORK_RULE_01"
        assert stored.explanation["triggered_rule"] == "WORK_RULE_01"
