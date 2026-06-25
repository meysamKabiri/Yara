from fastapi.testclient import TestClient
import pytest
from app.core.event_tracker import get_trace_events
from tests.natural_input_helpers import natural_input_interpretations, natural_input_result, natural_input_interpretation


def _mock_llm_v2(result: dict) -> dict:
    return result


def _make_worker(client: TestClient, name: str, worker_type: str, project_id: int | None = None) -> dict:
    if project_id is None:
        project = client.post("/projects", json={"name": f"p-{name}"}).json()
        project_id = project["id"]
    response = client.post(f"/projects/{project_id}/workers", json={"name": name, "type": worker_type})
    assert response.status_code == 201
    return response.json()


def test_multi_event_three_interpretations_created(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Multi-event LLM response creates three PendingInterpretations."""
    project = client.post("/projects", json={"name": "multi-three"}).json()
    _make_worker(client, "نادری جوشکار", "SKILLED_WORKER", project["id"])
    _make_worker(client, "میثم کبیری", "CLIENT", project["id"])

    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "events": [
                {
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
                    "matched_text": "۱۰۰ میلیون به نادری جوشکار پرداخت شد",
                },
                {
                    "intent": "FINANCIAL",
                    "action": "PAYMENT_IN",
                    "entities": [{"name": "میثم کبیری", "kind": "PERSON", "project_role": "CLIENT", "role_detail": None}],
                    "financial": {"amount": 50000000, "direction": "IN", "payment_method": None, "due_date_text": None},
                    "work": {"quantity": None, "unit": None, "description": None},
                    "note": {"text": None},
                    "confidence": 0.95,
                    "ambiguity": False,
                    "missing_fields": [],
                    "reasoning_summary": "۵۰ میلیون از میثم دریافت شد",
                    "matched_text": "۵۰ میلیون از میثم دریافت شد",
                },
                {
                    "intent": "WORK",
                    "action": "WORK_LOG",
                    "entities": [{"name": "رضا سرامیک کار", "kind": "PERSON", "project_role": "SKILLED_WORKER", "role_detail": "سرامیک کار"}],
                    "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
                    "work": {"quantity": 20, "unit": "meter", "description": "۲۰ متر کاشی کاری"},
                    "note": {"text": None},
                    "confidence": 0.9,
                    "ambiguity": False,
                    "missing_fields": [],
                    "reasoning_summary": "رضا سرامیک کار ۲۰ متر کاشی کاری کرد",
                    "matched_text": "رضا سرامیک کار ۲۰ متر کاشی کاری کرد",
                },
            ],
        }),
    )

    pis = natural_input_interpretations(
        client,
        project["id"],
        "۱۰۰ میلیون به نادری جوشکار دادم. رضا سرامیک کار ۲۰ متر کاشی کاری کرد. میثم ۵۰ میلیون واریز کرد",
    )
    assert len(pis) == 3


def test_multi_event_correct_amount_direction_action(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each event preserves correct amount, direction, and semantic action."""
    project = client.post("/projects", json={"name": "multi-amounts"}).json()
    _make_worker(client, "نادری جوشکار", "SKILLED_WORKER", project["id"])
    _make_worker(client, "میثم کبیری", "CLIENT", project["id"])

    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "events": [
                {
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
                    "matched_text": "۱۰۰ میلیون به نادری جوشکار پرداخت شد",
                },
                {
                    "intent": "FINANCIAL",
                    "action": "PAYMENT_IN",
                    "entities": [{"name": "میثم کبیری", "kind": "PERSON", "project_role": "CLIENT", "role_detail": None}],
                    "financial": {"amount": 50000000, "direction": "IN", "payment_method": None, "due_date_text": None},
                    "work": {"quantity": None, "unit": None, "description": None},
                    "note": {"text": None},
                    "confidence": 0.95,
                    "ambiguity": False,
                    "missing_fields": [],
                    "reasoning_summary": "۵۰ میلیون از میثم دریافت شد",
                    "matched_text": "۵۰ میلیون از میثم دریافت شد",
                },
            ],
        }),
    )

    pis = natural_input_interpretations(
        client,
        project["id"],
        "۱۰۰ میلیون به نادری جوشکار دادم. میثم ۵۰ میلیون واریز کرد",
    )
    assert len(pis) == 2

    payment_out = pis[0]
    assert payment_out["canonical_event_type"] == "FINANCIAL_EVENT"
    assert payment_out["semantic_action"] == "PAYMENT"
    assert payment_out["financial_direction"] == "OUTGOING"
    assert payment_out["extracted_amount"] == "100000000.00"

    payment_in = pis[1]
    assert payment_in["canonical_event_type"] == "FINANCIAL_EVENT"
    assert payment_in["semantic_action"] == "PAYMENT"
    assert payment_in["financial_direction"] == "INCOMING"
    assert payment_in["extracted_amount"] == "50000000.00"


def test_multi_event_matched_text_per_event(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each interpretation preserves its per-event matched_input_text."""
    project = client.post("/projects", json={"name": "multi-matched"}).json()
    _make_worker(client, "میثم کبیری", "CLIENT", project["id"])

    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "events": [
                {
                    "intent": "FINANCIAL",
                    "action": "PAYMENT_IN",
                    "entities": [{"name": "میثم کبیری", "kind": "PERSON", "project_role": "CLIENT", "role_detail": None}],
                    "financial": {"amount": 300000000, "direction": "IN", "payment_method": None, "due_date_text": None},
                    "work": {"quantity": None, "unit": None, "description": None},
                    "note": {"text": None},
                    "confidence": 0.95,
                    "ambiguity": False,
                    "missing_fields": [],
                    "reasoning_summary": "میثم ۳۰۰ میلیون واریز کرد به حساب پروژه",
                    "matched_text": "میثم ۳۰۰ میلیون واریز کرد به حساب پروژه",
                },
                {
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
                    "matched_text": "فردا صبح زود شروع کنیم",
                },
            ],
        }),
    )

    pis = natural_input_interpretations(
        client,
        project["id"],
        "میثم ۳۰۰ میلیون واریز کرد به حساب پروژه. فردا صبح زود شروع کنیم",
    )
    assert len(pis) == 2

    financial_pi = pis[0]
    assert financial_pi["matched_input_text"] == "میثم ۳۰۰ میلیون واریز کرد به حساب پروژه"
    assert financial_pi["canonical_event_type"] == "FINANCIAL_EVENT"

    note_pi = pis[1]
    assert note_pi["matched_input_text"] == "فردا صبح زود شروع کنیم"
    assert note_pi["canonical_event_type"] == "NOTE_EVENT"


def test_multi_event_bad_chunk_does_not_block_others(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """An ambiguous low-confidence NOTE event does not prevent valid financial events from becoming PENDING."""
    project = client.post("/projects", json={"name": "multi-bad"}).json()
    _make_worker(client, "نادری جوشکار", "SKILLED_WORKER", project["id"])

    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "events": [
                {
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
                    "matched_text": "۱۰۰ میلیون به نادری جوشکار پرداخت شد",
                },
                {
                    "intent": "NOTE",
                    "action": "NOTE",
                    "entities": [],
                    "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
                    "work": {"quantity": None, "unit": None, "description": None},
                    "note": {"text": "متن نامشخص"},
                    "confidence": 0.2,
                    "ambiguity": True,
                    "missing_fields": [],
                    "reasoning_summary": "نامشخص",
                    "matched_text": "متن نامشخص",
                },
            ],
        }),
    )

    pis = natural_input_interpretations(
        client,
        project["id"],
        "۱۰۰ میلیون به نادری جوشکار پرداخت کردم. متن نامشخص",
    )
    assert len(pis) == 2

    financial_pi = pis[0]
    assert financial_pi["canonical_event_type"] == "FINANCIAL_EVENT"
    assert financial_pi["extracted_amount"] == "100000000.00"
    assert financial_pi["financial_direction"] == "OUTGOING"

    note_pi = pis[1]
    assert note_pi["canonical_event_type"] == "NOTE_EVENT"


def test_multi_event_job_result_contains_all(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """natural_input_result returns all interpretations in the job result."""
    project = client.post("/projects", json={"name": "multi-result"}).json()
    _make_worker(client, "میثم کبیری", "CLIENT", project["id"])

    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, pid: _mock_llm_v2({
            "events": [
                {
                    "intent": "FINANCIAL",
                    "action": "PAYMENT_IN",
                    "entities": [{"name": "میثم کبیری", "kind": "PERSON", "project_role": "CLIENT", "role_detail": None}],
                    "financial": {"amount": 200000000, "direction": "IN", "payment_method": "BANK_TRANSFER", "due_date_text": None},
                    "work": {"quantity": None, "unit": None, "description": None},
                    "note": {"text": None},
                    "confidence": 0.95,
                    "ambiguity": False,
                    "missing_fields": [],
                    "reasoning_summary": "میثم ۲۰۰ میلیون واریز کرد",
                    "matched_text": "میثم ۲۰۰ میلیون واریز کرد",
                },
            ],
        }),
    )

    result = natural_input_result(
        client,
        project["id"],
        "میثم ۲۰۰ میلیون واریز کرد",
    )
    assert "interpretations" in result
    assert len(result["interpretations"]) == 1
    pi = result["interpretations"][0]
    assert pi["canonical_event_type"] == "FINANCIAL_EVENT"
    assert pi["financial_direction"] == "INCOMING"


def test_multi_event_single_legacy_compat(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A single-event response (no events key) still works (backward compat)."""
    project = client.post("/projects", json={"name": "multi-legacy-compat"}).json()
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

    pis = natural_input_interpretations(
        client,
        project["id"],
        "۱۰۰ میلیون به نادری جوشکار پرداخت کردم",
    )
    assert len(pis) == 1
    assert pis[0]["canonical_event_type"] == "FINANCIAL_EVENT"
    assert pis[0]["financial_direction"] == "OUTGOING"
    assert pis[0]["extracted_amount"] == "100000000.00"


def test_runtime_split_fallback_keeps_three_financial_events(client: TestClient) -> None:
    project = client.post("/projects", json={"name": "runtime-split-financial"}).json()

    result = natural_input_result(
        client,
        project["id"],
        "میثم 300 میلیون به حساب پروژه واریز کرد. به علی احمدی 5 میلیون دادم. از هادی پور 25 میلیون سیم خریدم و پرداخت کردم.",
        headers={"X-Trace-Id": "trace-runtime-split-financial"},
    )

    pis = result["interpretations"]
    assert len(pis) == 3
    assert all(pi["matched_input_text"] is not None for pi in pis)
    assert [pi["extracted_amount"] for pi in pis] == [
        "300000000.00",
        "5000000.00",
        "25000000.00",
    ]
    assert [pi["financial_direction"] for pi in pis] == [
        "INCOMING",
        "OUTGOING",
        "OUTGOING",
    ]
    assert [pi["payment_method"] for pi in pis] == [
        "BANK_TRANSFER",
        "CASH",
        "CASH",
    ]
    assert pis[1]["extracted_entities"][0]["name"] == "علی احمدی"
    assert pis[1]["extracted_entities"][0]["project_role"] == "OTHER"
    assert pis[2]["semantic_action"] == "PURCHASE_PAID"
    assert pis[2]["extracted_entities"][0]["project_role"] == "VENDOR"

    factory = client.app.state.testing_session_factory
    with factory() as db:
        events = get_trace_events("trace-runtime-split-financial", db=db)
    split_event = next(event for event in events if (event.get("event_name") or event.get("event")) == "MULTI_EVENT_SPLIT_APPLIED")
    assert split_event["payload"]["chunk_count"] == 3


def test_runtime_split_fallback_keeps_setup_phone_and_account_events(client: TestClient) -> None:
    project = client.post("/projects", json={"name": "runtime-split-profile"}).json()

    result = natural_input_result(
        client,
        project["id"],
        "میثم کبیری کارفرمای پروژه است\nشماره تماس میثم 09123456789\nشماره حساب میثم 6037991234567890",
        headers={"X-Trace-Id": "trace-runtime-split-profile"},
    )

    pis = result["interpretations"]
    assert len(pis) == 3
    assert all(pi["matched_input_text"] is not None for pi in pis)
    assert pis[0]["semantic_action"] == "SET_ROLE"
    assert pis[0]["extracted_entities"][0]["project_role"] == "CLIENT"
    assert pis[1]["semantic_action"] == "ENTITY_UPDATE"
    assert pis[1]["extracted_entities"][0]["phone"] == "09123456789"
    assert pis[2]["semantic_action"] == "ENTITY_UPDATE"
    assert pis[2]["extracted_entities"][0]["account_number"] == "6037991234567890"

    factory = client.app.state.testing_session_factory
    with factory() as db:
        events = get_trace_events("trace-runtime-split-profile", db=db)
    split_event = next(event for event in events if (event.get("event_name") or event.get("event")) == "MULTI_EVENT_SPLIT_APPLIED")
    assert split_event["payload"]["chunk_count"] == 3
