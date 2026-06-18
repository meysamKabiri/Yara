import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models.core import PendingInterpretation, PendingInterpretationStatus, Worker


def _mock_llm_v2(result: dict) -> dict:
    """Wrap a structured interpretation dict for use as LLM v2 mock."""
    return result


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
    response = client.post(f"/projects/{project['id']}/natural-input", json={"text": "مش رحیم کارفرمای پروژه است"})
    assert response.status_code == 201
    interpretations = response.json()["interpretations"]
    assert len(interpretations) == 1
    pi = interpretations[0]
    assert pi["canonical_event_type"] == "SETUP_EVENT"
    assert pi["semantic_action"] == "SETUP"
    assert pi["structured_interpretation"] is not None
    assert pi["structured_interpretation"]["intent"] == "SETUP"
    assert pi["structured_interpretation"]["action"] == "ADD_ENTITY"
    assert pi["extracted_entities"][0]["name"] == "مش رحیم"
    assert pi["extracted_entities"][0]["project_role"] == "CLIENT"

    confirm = client.post(f"/pending-interpretations/{pi['id']}/confirm").json()
    assert confirm["workers"][0]["name"] == "مش رحیم"
    assert confirm["workers"][0]["type"] == "CLIENT"


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
    pi = client.post(f"/projects/{project['id']}/natural-input", json={"text": "مش رحیم امروز کار کرد"}).json()["interpretations"][0]
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
    _make_worker(client, "نادری جوشکار", "SKILLED_WORKER", project["id"])

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

    pi = client.post(f"/projects/{project['id']}/natural-input", json={"text": "۱۰۰ میلیون دادم به نادری جوشکار"}).json()["interpretations"][0]
    assert pi["canonical_event_type"] == "FINANCIAL_EVENT"
    assert pi["semantic_action"] == "PAYMENT"
    assert pi["extracted_amount"] == "100000000.00"
    assert pi["financial_direction"] == "OUTGOING"

    confirm = client.post(f"/pending-interpretations/{pi['id']}/confirm").json()
    assert len(confirm["payments"]) == 1
    assert confirm["payments"][0]["amount"] == "100000000.00"
    assert confirm["payments"][0]["direction"] == "OUTGOING"
    assert confirm["payments"][0]["type"] == "BANK_TRANSFER"


def test_llm_v2_financial_payment_in(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM v2 financial IN interpretation creates an incoming payment."""
    project = client.post("/projects", json={"name": "test4"}).json()
    _make_worker(client, "میثم کبیری", "CLIENT", project["id"])

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

    pi = client.post(f"/projects/{project['id']}/natural-input", json={"text": "میثم ۲۰۰ میلیون پول داد"}).json()["interpretations"][0]
    assert pi["financial_direction"] == "INCOMING"

    confirm = client.post(f"/pending-interpretations/{pi['id']}/confirm").json()
    assert len(confirm["payments"]) == 1
    assert confirm["payments"][0]["direction"] == "INCOMING"


def test_llm_v2_financial_debt(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM v2 DEBT_CREATED interpretation creates an invoice."""
    project = client.post("/projects", json={"name": "test5"}).json()
    _make_worker(client, "هادی‌پور سیم", "VENDOR", project["id"])

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

    pi = client.post(f"/projects/{project['id']}/natural-input", json={"text": "۵ میلیون از هادی‌پور سیم خرید کردم نسیه"}).json()["interpretations"][0]
    assert pi["financial_direction"] == "DEBT"
    assert pi["semantic_action"] == "DEBT_CREATED"

    confirm = client.post(f"/pending-interpretations/{pi['id']}/confirm").json()
    assert len(confirm["invoices"]) == 1
    assert confirm["invoices"][0]["total_amount"] == "5000000.00"


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
    pi = client.post(f"/projects/{project['id']}/natural-input", json={"text": "فردا صبح زود شروع کنیم"}).json()["interpretations"][0]
    assert pi["canonical_event_type"] == "NOTE_EVENT"

    confirm = client.post(f"/pending-interpretations/{pi['id']}/confirm").json()
    assert len(confirm["history_entries"]) == 1
    assert confirm["payments"] == []
    assert confirm["workers"] == []


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
    pi = client.post(f"/projects/{project['id']}/natural-input", json={"text": "نادری جوشکار ۲۰ متر جوش داد"}).json()["interpretations"][0]

    si = pi["structured_interpretation"]
    assert si["intent"] == "WORK"
    assert si["action"] == "WORK_LOG"
    assert si["entities"][0]["name"] == "نادری جوشکار"
    assert si["entities"][0]["project_role"] == "SKILLED_WORKER"
    assert si["work"]["quantity"] == 20.0
    assert si["work"]["unit"] == "meter"
    assert si["confidence"] == 0.93


def _make_worker(client: TestClient, name: str, worker_type: str, project_id: int | None = None) -> dict:
    if project_id is None:
        project = client.post("/projects", json={"name": f"p-{name}"}).json()
        project_id = project["id"]
    response = client.post(f"/projects/{project_id}/workers", json={"name": name, "type": worker_type})
    assert response.status_code == 201
    return response.json()
