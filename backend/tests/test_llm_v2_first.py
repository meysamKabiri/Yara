from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.natural_input_helpers import natural_input_interpretation, natural_input_interpretations, submit_natural_input
from sqlalchemy import select

from app.models.core import PendingInterpretation, PendingInterpretationStatus, Worker


def _mock_llm_v2(result: dict) -> dict:
    """Wrap a structured interpretation dict for use as LLM v2 mock."""
    return result


def _confirm_financial(client: TestClient, pi: dict, payload: dict | None = None) -> dict:
    response = client.post(
        f"/pending-interpretations/{pi['id']}/confirm",
        json=payload or {},
    )
    assert response.status_code == 200
    body = response.json()
    if body.get("status") == "ENTITY_RESOLVED":
        response = client.post(
            f"/pending-interpretations/{pi['id']}/confirm",
            json={"entity_id": body["entity_id"], "confirmed": True},
        )
        assert response.status_code == 200
        body = response.json()
    return body


def test_llm_v2_setup_adds_client_entity(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM v2 interpretation of a client setup creates the correct pending interpretation."""
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "SETUP",
            "action": "ADD_ENTITY",
            "entities": [{"name": "مش رحیم", "kind": "PERSON", "project_role": "CLIENT", "role_detail": None}],
            "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.95,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "مش رحیم به عنوان کارفرما ثبت شد",
        }),
    )

    project = client.post("/projects", json={"name": "test"}).json()
    interpretations = natural_input_interpretations(client, project["id"], "مش رحیم کارفرمای پروژه است")
    assert len(interpretations) == 1
    pi = interpretations[0]
    assert pi["canonical_event_type"] == "SETUP_EVENT"
    assert pi["semantic_action"] == "SET_ROLE"
    assert pi["structured_interpretation"] is not None
    assert pi["structured_interpretation"]["intent"] == "SET_ROLE"
    assert pi["structured_interpretation"]["action"] == "SET_ROLE"
    assert pi["structured_interpretation"]["missing_fields"] == []
    assert pi["extracted_entities"][0]["name"] == "مش رحیم"
    assert pi["extracted_entities"][0]["project_role"] == "CLIENT"

    confirm = client.post(f"/pending-interpretations/{pi['id']}/confirm", json={"create_new": True}).json()
    assert confirm["workers"][0]["name"] == "مش رحیم"
    assert confirm["workers"][0]["type"] == "CLIENT"


def test_llm_v2_role_only_statement_is_set_role_without_missing_fields(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "SETUP",
            "action": "UPDATE_ENTITY",
            "entities": [{
                "name": "میثم کبیری",
                "kind": "PERSON",
                "project_role": "CLIENT",
                "role_detail": None,
            }],
            "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.95,
            "ambiguity": False,
            "missing_fields": ["phone", "account_number", "role_detail"],
            "reasoning_summary": "میثم کبیری کارفرمای پروژه است",
        }),
    )

    project = client.post("/projects", json={"name": "role-only"}).json()
    pi = natural_input_interpretation(client, project["id"], "میثم کبیری کارفرمای پروژه است")

    assert pi["canonical_event_type"] == "SETUP_EVENT"
    assert pi["semantic_action"] == "SET_ROLE"
    assert pi["structured_interpretation"]["intent"] == "SET_ROLE"
    assert pi["structured_interpretation"]["action"] == "SET_ROLE"
    assert pi["structured_interpretation"]["missing_fields"] == []
    assert pi["extracted_entities"][0]["name"] == "میثم کبیری"
    assert pi["extracted_entities"][0]["project_role"] == "CLIENT"


def test_llm_v2_work_records_daily_labor(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM v2 interpretation of daily work creates work log via structured interpretation."""
    existing_worker = _make_worker(client, "مش رحیم", "DAILY_WORKER")

    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "WORK",
            "action": "WORK_LOG",
            "entities": [{"name": "مش رحیم", "kind": "PERSON", "project_role": "DAILY_WORKER", "role_detail": None}],
            "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": "امروز سر کار بود"},
            "note": {"text": None},
            "confidence": 0.92,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "مش رحیم امروز کار کرد",
        }),
    )

    project = client.post("/projects", json={"name": "test2"}).json()
    pi = natural_input_interpretation(client, project["id"], "مش رحیم امروز کار کرد")
    assert pi["canonical_event_type"] == "WORK_EVENT"
    assert pi["semantic_action"] == "INCREMENT"
    assert pi["structured_interpretation"]["intent"] == "WORK"

    confirm = client.post(f"/pending-interpretations/{pi['id']}/confirm").json()
    assert len(confirm["work_logs"]) == 1
    states = client.get(f"/projects/{project['id']}/worker-states").json()
    assert any(s["name"] == "مش رحیم" and s["total_days_worked"] == "1.00" for s in states)


def test_llm_v2_financial_payment_out(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM v2 financial OUT interpretation creates a payment with direction OUTGOING."""
    project = client.post("/projects", json={"name": "test3"}).json()
    worker = _make_worker(client, "نادری جوشکار", "SKILLED_WORKER", project["id"])

    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "FINANCIAL",
            "action": "PAYMENT_OUT",
            "entities": [{"name": "نادری جوشکار", "kind": "PERSON", "project_role": "SKILLED_WORKER", "role_detail": "جوشکار"}],
            "financial": {"amount": 100000000, "direction": "OUT", "payment_method": "BANK_TRANSFER", "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.95,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "۱۰۰ میلیون به نادری جوشکار پرداخت شد",
        }),
    )

    pi = natural_input_interpretation(client, project["id"], "۱۰۰ میلیون دادم به نادری جوشکار")
    assert pi["canonical_event_type"] == "FINANCIAL_EVENT"
    assert pi["semantic_action"] == "PAYMENT"
    assert pi["extracted_amount"] == "100000000.00"
    assert pi["financial_direction"] == "OUTGOING"

    confirm = _confirm_financial(client, pi, {"selected_person_id": worker["id"]})
    assert len(confirm["payments"]) == 1
    assert confirm["payments"][0]["amount"] == "100000000.00"
    assert confirm["payments"][0]["direction"] == "OUTGOING"
    assert confirm["payments"][0]["type"] == "BANK_TRANSFER"


def test_llm_v2_financial_payment_in(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM v2 financial IN interpretation creates an incoming payment."""
    project = client.post("/projects", json={"name": "test4"}).json()
    worker = _make_worker(client, "میثم کبیری", "CLIENT", project["id"])

    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "FINANCIAL",
            "action": "PAYMENT_IN",
            "entities": [{"name": "میثم کبیری", "kind": "PERSON", "project_role": "CLIENT", "role_detail": None}],
            "financial": {"amount": 200000000, "direction": "IN", "payment_method": "BANK_TRANSFER", "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.95,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "۲۰۰ میلیون از کارفرما دریافت شد",
        }),
    )

    pi = natural_input_interpretation(client, project["id"], "میثم ۲۰۰ میلیون پول داد")
    assert pi["financial_direction"] == "INCOMING"

    confirm = _confirm_financial(client, pi, {"selected_person_id": worker["id"]})
    assert len(confirm["payments"]) == 1
    assert confirm["payments"][0]["direction"] == "INCOMING"


def test_llm_v2_repairs_titled_client_project_deposit_and_confirms_money_in(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = client.post("/projects", json={"name": "titled deposit"}).json()
    client_worker = _make_worker(client, "خانم احمدی", "CLIENT", project["id"])
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "SETUP",
            "action": "UPDATE_ENTITY",
            "entities": [{"name": "خانم احمدی", "kind": "PERSON", "project_role": "CLIENT", "role_detail": None}],
            "financial": {"amount": 80000000, "direction": "OUT", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.4,
            "ambiguity": True,
            "missing_fields": [],
            "reasoning_summary": "مدل پرداخت ورودی را با setup اشتباه گرفته است",
        }),
    )

    pi = natural_input_interpretation(client, project["id"], "خانم احمدی 80 میلیون تومان به حساب پروژه واریز کرد.")

    assert pi["canonical_event_type"] == "FINANCIAL_EVENT"
    assert pi["semantic_action"] == "PAYMENT"
    assert pi["financial_direction"] == "INCOMING"
    assert pi["payment_method"] == "BANK_TRANSFER"
    assert pi["suggested_entity_id"] == client_worker["id"]

    confirm = _confirm_financial(client, pi, {"selected_person_id": client_worker["id"]})
    assert confirm["payments"][0]["amount"] == "80000000.00"
    assert confirm["payments"][0]["direction"] == "INCOMING"
    summary = client.get(f"/projects/{project['id']}/operating-summary").json()
    assert summary["total_received"] == "80000000.00"


def test_llm_v2_repairs_project_account_deposit_with_missing_entity(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = client.post("/projects", json={"name": "deposit repair"}).json()
    existing = _make_worker(client, "میثم کبیری", "CLIENT", project["id"])
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "FINANCIAL",
            "action": "PAYMENT_OUT",
            "entities": [],
            "financial": {"amount": None, "direction": "OUT", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.3,
            "ambiguity": True,
            "missing_fields": [],
            "reasoning_summary": "مدل جهت را اشتباه تشخیص داده است",
        }),
    )

    pi = natural_input_interpretation(client, project["id"], "میثم 300 میلیون به حساب پروژه واریز کرد")
    entity = pi["extracted_entities"][0]

    assert pi["canonical_event_type"] == "FINANCIAL_EVENT"
    assert pi["semantic_action"] == "PAYMENT"
    assert pi["extracted_amount"] == "300000000.00"
    assert pi["payment_method"] == "BANK_TRANSFER"
    assert pi["financial_direction"] == "INCOMING"
    assert entity["name"] == "میثم"
    assert entity["type"] == "CLIENT"
    assert entity["project_role"] == "CLIENT"
    assert entity["candidate_matches"][0]["person_id"] == existing["id"]


def test_llm_v2_financial_debt(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM v2 DEBT_CREATED interpretation creates an invoice."""
    project = client.post("/projects", json={"name": "test5"}).json()
    worker = _make_worker(client, "هادی‌پور سیم", "VENDOR", project["id"])

    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "FINANCIAL",
            "action": "DEBT_CREATED",
            "entities": [{"name": "هادی‌پور سیم", "kind": "COMPANY", "project_role": "VENDOR", "role_detail": "سیم فروش"}],
            "financial": {"amount": 5000000, "direction": "OUT", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.9,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "۵ میلیون بدهی به هادی‌پور سیم",
        }),
    )

    pi = natural_input_interpretation(client, project["id"], "۵ میلیون از هادی‌پور سیم خرید کردم نسیه")
    assert pi["financial_direction"] == "DEBT"
    assert pi["semantic_action"] == "DEBT_CREATED"

    confirm = _confirm_financial(client, pi, {"selected_person_id": worker["id"]})
    assert len(confirm["invoices"]) == 1
    assert confirm["invoices"][0]["total_amount"] == "5000000.00"


def test_llm_v2_compact_prefix_vendor_name_requires_later_resolution(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    project = client.post("/projects", json={"name": "compact vendor"}).json()
    _make_worker(client, "هادی‌پور سیم", "VENDOR", project["id"])

    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "FINANCIAL",
            "action": "PURCHASE_PAID",
            "entities": [{"name": "هادیپور", "kind": "COMPANY", "project_role": "VENDOR", "role_detail": "سیم فروش"}],
            "financial": {"amount": 5000000, "direction": "OUT", "payment_method": "BANK_TRANSFER", "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.92,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "۵ میلیون خرید سیم از هادیپور",
        }),
    )

    pi = natural_input_interpretation(client, project["id"], "از هادیپور ۵ میلیون سیم خریدم")
    assert pi["suggested_entity_id"] is None
    assert pi["matched_input_text"] is None


def test_llm_v2_named_vendor_auto_create_allows_unknown_kind(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    project = client.post("/projects", json={"name": "vendor auto create"}).json()

    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "FINANCIAL",
            "action": "PURCHASE_PAID",
            "entities": [{"name": "هادیپور", "kind": "UNKNOWN", "project_role": "VENDOR", "role_detail": None}],
            "financial": {"amount": 5000000, "direction": "OUT", "payment_method": "BANK_TRANSFER", "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.92,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "۵ میلیون خرید سیم از هادیپور",
        }),
    )

    pi = natural_input_interpretation(client, project["id"], "از هادیپور ۵ میلیون سیم خریدم")

    assert pi["suggested_entity_id"] is None
    assert pi["extracted_entities"][0]["project_role"] == "VENDOR"
    assert pi["structured_interpretation"]["ambiguity"] is False
    assert pi["confidence"] >= 0.85

    confirm = client.post(f"/pending-interpretations/{pi['id']}/confirm", json={"create_new": True})
    assert confirm.status_code == 200
    resolved = confirm.json()
    assert resolved["status"] == "ENTITY_RESOLVED"
    result = _confirm_financial(client, pi, {"entity_id": resolved["entity_id"], "confirmed": True})
    assert result["workers"][0]["name"] == "هادیپور"
    assert result["workers"][0]["type"] == "VENDOR"


def test_llm_v2_paid_purchase_corrects_amount_direction_and_worker_role_conflict(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = client.post("/projects", json={"name": "purchase conflict"}).json()
    daily_worker = _make_worker(client, "هادی پور", "DAILY_WORKER", project["id"])

    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "FINANCIAL",
            "action": "PURCHASE_PAID",
            "entities": [{"name": "هادی پور", "kind": "PERSON", "project_role": "OTHER", "role_detail": None}],
            "financial": {"amount": 2500000, "direction": "IN", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.95,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "خورطومی",
        }),
    )

    pi = natural_input_interpretation(client, project["id"], "از هادی پور ۲ ملیون و ۳۵۰ هزار تومن خورطومی خریدم")

    assert pi["semantic_action"] == "PURCHASE_PAID"
    assert pi["extracted_amount"] == "2350000.00"
    assert pi["financial_direction"] == "OUTGOING"
    assert pi["payment_method"] == "CASH"
    assert pi["suggested_entity_id"] is None
    assert pi["extracted_entities"][0]["name"] == "هادی پور"
    assert pi["extracted_entities"][0]["project_role"] == "VENDOR"
    assert pi["extracted_entities"][0]["type"] == "VENDOR"
    assert pi["description"] == "خورطومی"

    confirm = client.post(
        f"/pending-interpretations/{pi['id']}/confirm",
        json={"selected_person_id": daily_worker["id"]},
    )
    assert confirm.status_code == 200
    resolved = confirm.json()
    assert resolved["status"] == "ENTITY_RESOLVED"

    confirm = client.post(
        f"/pending-interpretations/{pi['id']}/confirm",
        json={"entity_id": resolved["entity_id"], "confirmed": True},
    )
    assert confirm.status_code == 409
    assert confirm.json()["detail"] == "Matched entity role conflicts with expected vendor role"


def test_llm_v2_purchase_rejects_explicit_daily_worker_vendor_conflict(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = client.post("/projects", json={"name": "purchase explicit conflict"}).json()
    daily_worker = _make_worker(client, "هادی پور", "DAILY_WORKER", project["id"])

    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "FINANCIAL",
            "action": "PURCHASE_PAID",
            "entities": [{"name": "هادی پور", "kind": "PERSON", "project_role": "VENDOR", "role_detail": None}],
            "financial": {"amount": 2350000, "direction": "OUT", "payment_method": "CASH", "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.95,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "خورطومی",
        }),
    )

    pi = natural_input_interpretation(client, project["id"], "از هادی پور ۲ میلیون و ۳۵۰ هزار تومن خورطومی خریدم")
    edit = client.patch(
        f"/pending-interpretations/{pi['id']}",
        json={"suggested_entity_id": daily_worker["id"]},
    )
    assert edit.status_code == 200

    confirm = client.post(
        f"/pending-interpretations/{pi['id']}/confirm",
        json={"entity_id": daily_worker["id"], "confirmed": True},
    )
    assert confirm.status_code == 409
    assert "vendor role" in confirm.json()["detail"]


def test_unpaid_purchase_creates_invoice_without_cash_payment(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = client.post("/projects", json={"name": "unpaid purchase"}).json()
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "FINANCIAL",
            "action": "PURCHASE_PAID",
            "entities": [{"name": "آهنچی", "kind": "COMPANY", "project_role": "VENDOR", "role_detail": None}],
            "financial": {"amount": 80000000, "direction": "OUT", "payment_method": "CASH", "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.9,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "میلگرد خریداری شد",
        }),
    )

    pi = natural_input_interpretation(
        client,
        project["id"],
        "از آهنچی 80 میلیون تومان میلگرد خریداری شد و هنوز پرداخت نشده.",
    )

    assert pi["semantic_action"] == "DEBT_CREATED"
    assert pi["financial_direction"] == "DEBT"
    assert pi["payment_method"] is None

    body = _confirm_financial(client, pi, {"create_new": True})
    assert body["payments"] == []
    assert body["invoices"][0]["total_amount"] == "80000000.00"
    summary = client.get(f"/projects/{project['id']}/operating-summary").json()
    assert summary["total_paid_out"] == "0.00"
    assert summary["open_payables"] == "80000000.00"


def test_check_purchase_confirms_as_check_payment_not_cash(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = client.post("/projects", json={"name": "check purchase"}).json()
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "FINANCIAL",
            "action": "PURCHASE_PAID",
            "entities": [{"name": "بتن آماده شرق", "kind": "COMPANY", "project_role": "VENDOR", "role_detail": None}],
            "financial": {"amount": 55000000, "direction": "OUT", "payment_method": "CASH", "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.9,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "بتن خریداری شد",
        }),
    )

    pi = natural_input_interpretation(
        client,
        project["id"],
        "از بتن آماده شرق 55 میلیون تومان بتن خریداری شد و چک یک‌ماهه پرداخت شد.",
    )

    assert pi["semantic_action"] == "CHECK_PAYMENT"
    assert pi["payment_method"] == "CHECK"

    body = _confirm_financial(client, pi, {"create_new": True})
    payment = body["payments"][0]
    assert payment["amount"] == "55000000.00"
    assert payment["type"] == "CHECK"
    assert payment["direction"] == "DEFERRED"


def test_outgoing_payment_to_existing_daily_worker_does_not_require_vendor_role(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = client.post("/projects", json={"name": "worker payment"}).json()
    worker = _make_worker(client, "مش رحیم", "DAILY_WORKER", project["id"])
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "FINANCIAL",
            "action": "PAYMENT_OUT",
            "entities": [{"name": "مش رحیم", "kind": "PERSON", "project_role": "VENDOR", "role_detail": None}],
            "financial": {"amount": 2000000, "direction": "OUT", "payment_method": "CASH", "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.8,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "به مش رحیم پرداخت شد",
        }),
    )

    pi = natural_input_interpretation(client, project["id"], "2 میلیون تومان به مش رحیم پرداخت شد.")
    confirm = _confirm_financial(client, pi, {"selected_person_id": worker["id"]})

    assert confirm["payments"][0]["amount"] == "2000000.00"
    assert confirm["payments"][0]["direction"] == "OUTGOING"
    workers = client.get(f"/projects/{project['id']}/workers").json()
    assert workers[0]["type"] == "DAILY_WORKER"


def test_llm_v2_note_creates_no_state(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM v2 NOTE interpretation creates a history entry without side effects."""
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "NOTE",
            "action": "NOTE",
            "entities": [],
            "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": "فردا صبح زود شروع کنیم"},
            "confidence": 0.6,
            "ambiguity": True,
            "missing_fields": [],
            "reasoning_summary": "یادداشت عمومی",
        }),
    )

    project = client.post("/projects", json={"name": "test6"}).json()
    pi = natural_input_interpretation(client, project["id"], "فردا صبح زود شروع کنیم")
    assert pi["canonical_event_type"] == "NOTE_EVENT"

    confirm = client.post(f"/pending-interpretations/{pi['id']}/confirm").json()
    assert len(confirm["history_entries"]) == 1
    assert confirm["payments"] == []
    assert confirm["workers"] == []


def test_note_text_misclassified_as_setup_is_repaired_to_safe_note(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = client.post("/projects", json={"name": "safe note"}).json()
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "SETUP",
            "action": "ADD_ENTITY",
            "entities": [{"name": "کارفرما", "kind": "PERSON", "project_role": "CLIENT", "role_detail": None}],
            "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.6,
            "ambiguity": True,
            "missing_fields": [],
            "reasoning_summary": "مدل یادداشت را setup گرفته است",
        }),
    )

    pi = natural_input_interpretation(client, project["id"], "کارفرما رنگ طوسی روشن را تایید کرد.")

    assert pi["canonical_event_type"] == "NOTE_EVENT"
    assert pi["semantic_action"] == "NOTE"
    confirm = client.post(f"/pending-interpretations/{pi['id']}/confirm")
    assert confirm.status_code == 200
    assert confirm.json()["workers"] == []
    assert client.get(f"/projects/{project['id']}/workers").json() == []


def test_work_like_setup_misclassification_does_not_create_corrupted_person(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = client.post("/projects", json={"name": "safe work candidate"}).json()
    existing = _make_worker(client, "مش رحیم", "DAILY_WORKER", project["id"])
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "SET_ROLE",
            "action": "SET_ROLE",
            "entities": [{"name": "مش رح:م", "kind": "PERSON", "project_role": "DAILY_WORKER", "role_detail": None}],
            "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.5,
            "ambiguity": True,
            "missing_fields": [],
            "reasoning_summary": "مدل کارکرد را setup گرفته است",
        }),
    )

    pi = natural_input_interpretation(client, project["id"], "مش رحیم امروز کار کرد.")

    assert pi["canonical_event_type"] == "NOTE_EVENT"
    confirm = client.post(f"/pending-interpretations/{pi['id']}/confirm")
    assert confirm.status_code == 200
    assert confirm.json()["workers"] == []
    workers = client.get(f"/projects/{project['id']}/workers").json()
    assert workers == [existing]
    assert all(worker["name"] != "مش رح:م" for worker in workers)


def test_llm_v2_structured_interpretation_stored(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """The full LLM v2 output is stored as structured_interpretation JSON."""
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "WORK",
            "action": "WORK_LOG",
            "entities": [{"name": "نادری جوشکار", "kind": "PERSON", "project_role": "SKILLED_WORKER", "role_detail": "جوشکار"}],
            "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
            "work": {"quantity": 20, "unit": "meter", "description": "۲۰ متر جوشکاری"},
            "note": {"text": None},
            "confidence": 0.93,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "نادری جوشکار ۲۰ متر جوش داد",
        }),
    )

    project = client.post("/projects", json={"name": "test7"}).json()
    pi = natural_input_interpretation(client, project["id"], "نادری جوشکار ۲۰ متر جوش داد")

    si = pi["structured_interpretation"]
    assert si["intent"] == "WORK"
    assert si["action"] == "WORK_LOG"
    assert si["entities"][0]["name"] == "نادری جوشکار"
    assert si["entities"][0]["project_role"] == "SKILLED_WORKER"
    assert si["work"]["quantity"] == 20.0
    assert si["work"]["unit"] == "meter"
    assert si["confidence"] == 0.93


def test_llm_v2_add_entity_with_existing_phone_update_is_coerced_to_update(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = client.post("/projects", json={"name": "profile phone"}).json()
    existing = _make_worker(client, "میثم", "CLIENT", project["id"])
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "SETUP",
            "action": "ADD_ENTITY",
            "entities": [{
                "name": "میثم",
                "kind": "PERSON",
                "project_role": "CLIENT",
                "role_detail": None,
                "field_updates": {"phone": "09123456789"},
                "phone": "09123456789",
            }],
            "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.94,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "شماره تماس میثم ثبت شد",
        }),
    )

    pi = natural_input_interpretation(client, project["id"], "شماره تماس میثم 09123456789")

    assert pi["suggested_entity_id"] is None
    assert pi["semantic_action"] == "ENTITY_UPDATE"
    assert pi["structured_interpretation"]["action"] == "UPDATE_ENTITY"

    unresolved = client.post(f"/pending-interpretations/{pi['id']}/confirm")
    assert unresolved.status_code == 400
    assert unresolved.json()["detail"]["status"] == "NEEDS_SELECTION"

    confirm = client.post(
        f"/pending-interpretations/{pi['id']}/confirm",
        json={"selected_person_id": existing["id"]},
    )
    assert confirm.status_code == 200
    workers = client.get(f"/projects/{project['id']}/workers").json()
    assert len(workers) == 1
    assert workers[0]["name"] == "میثم"
    assert workers[0]["type"] == "CLIENT"
    assert workers[0]["phone"] == "09123456789"


def test_llm_v2_existing_account_number_update_does_not_create_duplicate(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = client.post("/projects", json={"name": "profile account"}).json()
    existing = _make_worker(client, "میثم", "CLIENT", project["id"])
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "SETUP",
            "action": "ADD_ENTITY",
            "entities": [{
                "name": "میثم",
                "kind": "PERSON",
                "project_role": "CLIENT",
                "role_detail": None,
                "field_updates": {"account_number": "45734643565444"},
                "account_number": "45734643565444",
            }],
            "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.94,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "شماره حساب میثم ثبت شد",
        }),
    )

    pi = natural_input_interpretation(client, project["id"], "شماره حساب میثم 45734643565444")
    unresolved = client.post(f"/pending-interpretations/{pi['id']}/confirm")
    assert unresolved.status_code == 400
    assert unresolved.json()["detail"]["status"] == "NEEDS_SELECTION"

    confirm = client.post(
        f"/pending-interpretations/{pi['id']}/confirm",
        json={"selected_person_id": existing["id"]},
    )
    workers = client.get(f"/projects/{project['id']}/workers").json()

    assert confirm.status_code == 200
    assert pi["structured_interpretation"]["action"] == "UPDATE_ENTITY"
    assert len(workers) == 1
    assert workers[0]["account_number"] == "45734643565444"


def test_llm_v2_existing_daily_rate_update_does_not_change_role(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = client.post("/projects", json={"name": "profile rate"}).json()
    existing = _make_worker(client, "مش رحیم", "DAILY_WORKER", project["id"])
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "SETUP",
            "action": "ADD_ENTITY",
            "entities": [{
                "name": "مش رحیم",
                "kind": "PERSON",
                "project_role": "DAILY_WORKER",
                "role_detail": None,
                "field_updates": {"daily_rate": 1200000},
                "daily_rate": 1200000,
            }],
            "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.94,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "دستمزد روزانه مش رحیم ثبت شد",
        }),
    )

    pi = natural_input_interpretation(client, project["id"], "دستمزد روزانه مش رحیم ۱۲۰۰۰۰۰ تومان است")
    unresolved = client.post(f"/pending-interpretations/{pi['id']}/confirm")
    assert unresolved.status_code == 400
    assert unresolved.json()["detail"]["status"] == "NEEDS_SELECTION"

    confirm = client.post(
        f"/pending-interpretations/{pi['id']}/confirm",
        json={"selected_person_id": existing["id"]},
    )
    workers = client.get(f"/projects/{project['id']}/workers").json()

    assert confirm.status_code == 200
    assert pi["structured_interpretation"]["action"] == "UPDATE_ENTITY"
    assert len(workers) == 1
    assert workers[0]["type"] == "DAILY_WORKER"
    assert workers[0]["daily_rate"] == "1200000.00"


def test_llm_v2_partial_setup_creation_is_blocked_until_confirmation_resolution(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    project = client.post("/projects", json={"name": "partial setup block"}).json()
    existing = _make_worker(client, "میثم کبیری", "CLIENT", project["id"])
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "SETUP",
            "action": "ADD_ENTITY",
            "entities": [{
                "name": "میثم",
                "kind": "PERSON",
                "project_role": "DAILY_WORKER",
                "role_detail": None,
            }],
            "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.9,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "میثم به پروژه اضافه شود",
        }),
    )

    pi = natural_input_interpretation(client, project["id"], "میثم کارگر پروژه است")

    entity = pi["extracted_entities"][0]
    assert pi["suggested_entity_id"] is None
    assert pi["semantic_action"] == "SET_ROLE"
    assert pi["structured_interpretation"]["missing_fields"] == []
    assert entity["name"] == "میثم"
    assert entity["type"] == "DAILY_WORKER"
    assert entity["project_role"] == "DAILY_WORKER"
    assert entity["requires_confirmation"] is True
    assert entity["candidate_matches"][0]["person_id"] == existing["id"]

    confirm = client.post(f"/pending-interpretations/{pi['id']}/confirm")
    workers = client.get(f"/projects/{project['id']}/workers").json()

    assert confirm.status_code == 400
    assert confirm.json()["detail"]["status"] == "NEEDS_SELECTION"
    assert workers == [existing]


def test_skilled_worker_setup_with_phone_uses_same_pending_entity(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = client.post("/projects", json={"name": "skilled setup phone"}).json()
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "NOTE",
            "action": "NOTE",
            "entities": [],
            "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": "fallback should not be needed"},
            "confidence": 0.1,
            "ambiguity": True,
            "missing_fields": [],
            "reasoning_summary": "bad model fallback",
        }),
    )

    pi = natural_input_interpretation(
        client,
        project["id"],
        "ریاحی سرامیک‌کار به پروژه اضافه شد. شماره تماس ریاحی 09121111111",
    )

    assert pi["canonical_event_type"] == "SETUP_EVENT"
    assert pi["semantic_action"] == "ENTITY_UPDATE"
    entity = pi["extracted_entities"][0]
    assert entity["name"] == "ریاحی"
    assert entity["type"] == "SKILLED_WORKER"
    assert entity["role_detail"] == "سرامیک کار"
    assert entity["phone"] == "09121111111"

    confirm = client.post(f"/pending-interpretations/{pi['id']}/confirm", json={"create_new": True})
    assert confirm.status_code == 200
    worker = confirm.json()["workers"][0]
    assert worker["name"] == "ریاحی"
    assert worker["type"] == "SKILLED_WORKER"
    assert worker["role_detail"] == "سرامیک کار"
    assert worker["phone"] == "09121111111"


def test_multi_sentence_skilled_worker_setup_creates_each_role_detail(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = client.post("/projects", json={"name": "multi skilled setup"}).json()
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "NOTE",
            "action": "NOTE",
            "entities": [],
            "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": "fallback should not be needed"},
            "confidence": 0.1,
            "ambiguity": True,
            "missing_fields": [],
            "reasoning_summary": "bad model fallback",
        }),
    )

    interpretations = natural_input_interpretations(
        client,
        project["id"],
        "کاظمی نقاش به پروژه اضافه شد.\nصادقی کابینت‌کار به پروژه اضافه شد.\nرحمانی گچ‌کار به پروژه اضافه شد.",
    )

    setup_interpretations = [
        pi for pi in interpretations if pi.get("extracted_entities")
    ]
    assert [
        (pi["extracted_entities"][0]["name"], pi["extracted_entities"][0]["role_detail"])
        for pi in setup_interpretations
    ] == [
        ("کاظمی", "نقاش"),
        ("صادقی", "کابینت کار"),
        ("رحمانی", "گچ کار"),
    ]


def test_confirmation_modal_phone_update_copy_is_not_add_copy() -> None:
    source = Path(__file__).resolve().parents[2] / "frontend" / "src" / "ui" / "entity" / "EntityUpdateModal.tsx"
    modal_source = source.read_text()

    assert "به‌روزرسانی اطلاعات فرد" in modal_source
    assert "شماره موبایل" in modal_source
    assert "به عنوان" not in modal_source


def _make_worker(client: TestClient, name: str, worker_type: str, project_id: int | None = None) -> dict:
    if project_id is None:
        project = client.post("/projects", json={"name": f"p-{name}"}).json()
        project_id = project["id"]
    response = client.post(f"/projects/{project_id}/workers", json={"name": name, "type": worker_type})
    assert response.status_code == 201
    return response.json()


def test_counterparty_partial_client_match_preselects_existing_client(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Partial client match (score 0.7) preselects existing project client when only one client exists."""
    project = client.post("/projects", json={"name": "partial client"}).json()
    _make_worker(client, "میثم کبیری", "CLIENT", project["id"])

    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "FINANCIAL",
            "action": "PAYMENT",
            "entities": [{"name": "میثم", "kind": "PERSON", "project_role": "CLIENT", "role_detail": None}],
            "financial": {"amount": 300000000, "direction": "IN", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.95,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "میثم پول واریز کرد",
        }),
    )

    pi = natural_input_interpretation(client, project["id"], "میثم ۳۰۰ میلیون به حساب پروژه واریز کرد")

    assert pi["suggested_entity_id"] is not None, "Should preselect existing CLIENT on partial match"
    workers = client.get(f"/projects/{project['id']}/workers").json()
    assert workers[0]["id"] == pi["suggested_entity_id"]


def test_counterparty_unknown_vendor_creates_new_draft(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Purchase from unknown vendor with no matching worker creates create-new draft (null suggested_entity_id)."""
    project = client.post("/projects", json={"name": "unknown vendor"}).json()

    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "FINANCIAL",
            "action": "PURCHASE_PAID",
            "entities": [{"name": "هادی پور", "kind": "PERSON", "project_role": "VENDOR", "role_detail": None}],
            "financial": {"amount": 25000000, "direction": "OUT", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.95,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "هادی پور سیم فروخت",
        }),
    )

    pi = natural_input_interpretation(client, project["id"], "از هادی پور ۲۵ میلیون سیم خریدم و پرداخت کردم")

    assert pi["suggested_entity_id"] is None, "Should not preselect when no matching vendor exists"


def test_counterparty_existing_vendor_preselects(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Purchase from existing vendor preselects that vendor."""
    project = client.post("/projects", json={"name": "existing vendor"}).json()
    vendor = _make_worker(client, "هادی پور", "VENDOR", project["id"])

    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "FINANCIAL",
            "action": "PURCHASE_PAID",
            "entities": [{"name": "هادی پور", "kind": "PERSON", "project_role": "VENDOR", "role_detail": None}],
            "financial": {"amount": 25000000, "direction": "OUT", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.95,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "هادی پور سیم فروخت",
        }),
    )

    pi = natural_input_interpretation(client, project["id"], "از هادی پور ۲۵ میلیون سیم خریدم و پرداخت کردم")

    assert pi["suggested_entity_id"] == vendor["id"], "Should preselect existing vendor on exact name match"


def test_counterparty_outgoing_unknown_person_creates_draft(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Outgoing payment to unknown person does not preselect (create-new OTHER draft)."""
    project = client.post("/projects", json={"name": "unknown person"}).json()

    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "FINANCIAL",
            "action": "PAYMENT_OUT",
            "entities": [{"name": "علی احمدی", "kind": "PERSON", "project_role": "OTHER", "role_detail": None}],
            "financial": {"amount": 5000000, "direction": "OUT", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.95,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "به علی احمدی پول دادم",
        }),
    )

    pi = natural_input_interpretation(client, project["id"], "به علی احمدی ۵ میلیون دادم")

    assert pi["suggested_entity_id"] is None, "Should not preselect for unknown person with no role evidence"
    entities = pi.get("extracted_entities") or []
    assert len(entities) > 0, f"Expected at least one extracted entity, got {entities}"
    assert entities[0]["name"] == "علی احمدی"


def test_counterparty_low_confidence_ambiguous_does_not_preselect(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Low-confidence partial match below threshold does not auto-select."""
    project = client.post("/projects", json={"name": "low conf"}).json()
    _make_worker(client, "محمد رضایی", "VENDOR", project["id"])
    _make_worker(client, "محمد کریمی", "VENDOR", project["id"])

    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "intent": "FINANCIAL",
            "action": "PURCHASE_PAID",
            "entities": [{"name": "محمد", "kind": "PERSON", "project_role": "VENDOR", "role_detail": None}],
            "financial": {"amount": 1000000, "direction": "OUT", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.95,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "به محمد پول دادم",
        }),
    )

    pi = natural_input_interpretation(client, project["id"], "به محمد ۱ میلیون دادم")

    assert pi["suggested_entity_id"] is None, "Should not auto-select when multiple ambiguous candidates exist"


def test_outgoing_worker_payment_strips_purpose_clause_and_links_existing_worker(client: TestClient) -> None:
    project = client.post("/projects", json={"name": "purpose payment"}).json()
    worker = _make_worker(client, "ریاحی", "SKILLED_WORKER", project["id"])

    pi = natural_input_interpretation(
        client,
        project["id"],
        "به ریاحی بابت سرامیک کاری 20 میلیون تومان پرداخت شد",
    )

    assert pi["canonical_event_type"] == "FINANCIAL_EVENT"
    assert pi["semantic_action"] == "PAYMENT"
    assert pi["suggested_entity_id"] == worker["id"]
    assert pi["extracted_entities"][0]["name"] == "ریاحی"

    _confirm_financial(client, pi, {"entity_id": worker["id"], "confirmed": True})

    workers = client.get(f"/projects/{project['id']}/workers").json()
    payments = client.get(f"/projects/{project['id']}/payments").json()
    assert [item["name"] for item in workers] == ["ریاحی"]
    assert payments[0]["entity_id"] == worker["id"]
    assert payments[0]["amount"] == "20000000.00"


@pytest.mark.parametrize(
    "text",
    [
        "سرامیک طبقه اول تمام شد",
        "کارفرما رنگ دیوار پذیرایی را تغییر داد",
    ],
)
def test_realistic_progress_and_change_phrases_are_safe_notes(client: TestClient, text: str) -> None:
    project = client.post("/projects", json={"name": "notes"}).json()

    pi = natural_input_interpretation(client, project["id"], text)

    assert pi["canonical_event_type"] == "NOTE_EVENT"
    assert pi["semantic_action"] == "NOTE"
    assert pi["extracted_entities"] is None
    response = client.post(f"/pending-interpretations/{pi['id']}/confirm")
    assert response.status_code == 200
    assert client.get(f"/projects/{project['id']}/workers").json() == []
    assert client.get(f"/projects/{project['id']}/payments").json() == []
