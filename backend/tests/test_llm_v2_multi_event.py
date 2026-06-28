from fastapi.testclient import TestClient
import pytest
from app.core.event_tracker import get_trace_events
from app.core.financial_role_repair import normalize_outgoing_payment_role
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
    manual_input = "میثم 300 میلیون به حساب پروژه واریز کرد. به علی احمدی 5 میلیون دادم. از هادی پور 25 میلیون سیم خریدم"
    project = client.post("/projects", json={"name": "runtime-split-financial"}).json()

    result = natural_input_result(
        client,
        project["id"],
        manual_input,
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
    assert pis[0]["extracted_entities"][0]["project_role"] == "CLIENT"
    assert pis[0]["matched_input_text"] == "میثم 300 میلیون به حساب پروژه واریز کرد"
    assert pis[1]["extracted_entities"][0]["project_role"] == "OTHER"
    assert pis[1]["matched_input_text"] == "به علی احمدی 5 میلیون دادم"
    if pis[1]["structured_interpretation"] is not None:
        assert pis[1]["structured_interpretation"]["entities"][0]["project_role"] == "OTHER"
    assert pis[2]["semantic_action"] == "PURCHASE_PAID"
    assert "هادی پور" in pis[2]["matched_input_text"]
    assert pis[2]["matched_input_text"] == "از هادی پور 25 میلیون سیم خریدم"
    assert pis[2]["description"] == "از هادی پور 25 میلیون سیم خریدم"
    assert pis[2]["description"] != "میثم 300 میلیون به حساب پروژه واریز کرد. به علی احمدی 5 میلیون دادم. از هادی پور 25 میلیون سیم خریدم"
    assert pis[2]["extracted_entities"][0]["name"] == "هادی پور"
    assert pis[2]["extracted_entities"][0]["name"] != "میثم"
    assert pis[2]["extracted_entities"][0]["project_role"] == "VENDOR"
    assert pis[2]["extracted_amount"] != "300000000.00"

    for pi in pis:
        structured_entities = (pi.get("structured_interpretation") or {}).get("entities") or []
        structured_financial = (pi.get("structured_interpretation") or {}).get("financial") or {}
        if not structured_entities:
            continue
        extracted = pi["extracted_entities"][0]
        structured = structured_entities[0]
        assert structured["name"] == extracted["name"]
        assert structured["project_role"] == extracted["project_role"]
        assert str(structured_financial.get("amount")) in {pi["extracted_amount"], pi["extracted_amount"].removesuffix(".00")}
        assert pi["description"] == pi["matched_input_text"]
        assert pi["description"] != manual_input

    factory = client.app.state.testing_session_factory
    with factory() as db:
        events = get_trace_events("trace-runtime-split-financial", db=db)
    split_event = next(event for event in events if (event.get("event_name") or event.get("event")) == "MULTI_EVENT_SPLIT_APPLIED")
    assert split_event["payload"]["chunk_count"] == 3
    assert [chunk["chunk_text"] for chunk in split_event["payload"]["chunks"]] == [
        "میثم 300 میلیون به حساب پروژه واریز کرد",
        "به علی احمدی 5 میلیون دادم",
        "از هادی پور 25 میلیون سیم خریدم",
    ]
    event_names = [event.get("event_name") or event.get("event") for event in events]
    split_index = event_names.index("MULTI_EVENT_SPLIT_APPLIED")
    llm_started = [
        (index, event)
        for index, event in enumerate(events)
        if (event.get("event_name") or event.get("event")) == "LLM_STARTED"
    ]
    assert all(index > split_index for index, _ in llm_started)
    assert all(event["payload"].get("chunk_text") != manual_input for _, event in llm_started)
    assert all(event["payload"].get("input_text_length") != len(manual_input) for _, event in llm_started)


def test_multi_event_mixed_fast_path_and_chunk_llm(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    project = client.post("/projects", json={"name": "multi-mixed-fast-llm"}).json()
    input_text = "به علی احمدی 5 میلیون دادم. از هادی پور 25 میلیون سیم خریدم"
    llm_calls: list[str] = []

    def fake_interpret(self, raw_text: str, project_id: int, db=None) -> dict:
        llm_calls.append(raw_text)
        if raw_text == "از هادی پور 25 میلیون سیم خریدم":
            return {
                "intent": "FINANCIAL",
                "action": "PURCHASE_PAID",
                "entities": [{"name": "هادی پور", "kind": "PERSON", "project_role": "VENDOR", "role_detail": None}],
                "financial": {"amount": 25000000, "direction": "OUT", "payment_method": "CASH", "due_date_text": None},
                "work": {"quantity": None, "unit": None, "description": None},
                "note": {"text": None},
                "confidence": 0.92,
                "ambiguity": False,
                "missing_fields": [],
                "reasoning_summary": "خرید سیم از هادی پور",
                "matched_text": raw_text,
            }
        return {
            "intent": "NOTE",
            "action": "NOTE",
            "entities": [],
            "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": raw_text},
            "confidence": 0.0,
            "ambiguity": True,
            "missing_fields": [],
            "reasoning_summary": "unexpected test call",
            "_llm_v2_failed": True,
        }

    monkeypatch.setattr("app.api.projects.LLMv2Interpreter.interpret", fake_interpret)

    result = natural_input_result(
        client,
        project["id"],
        input_text,
        headers={"X-Trace-Id": "trace-mixed-fast-llm"},
    )

    pis = result["interpretations"]
    assert len(pis) == 2
    assert llm_calls == ["از هادی پور 25 میلیون سیم خریدم"]
    assert pis[0]["matched_input_text"] == "به علی احمدی 5 میلیون دادم"
    assert pis[0]["extracted_amount"] == "5000000.00"
    assert pis[0]["financial_direction"] == "OUTGOING"
    assert pis[0]["extracted_entities"][0]["project_role"] == "OTHER"
    assert pis[1]["matched_input_text"] == "از هادی پور 25 میلیون سیم خریدم"
    assert pis[1]["extracted_amount"] == "25000000.00"
    assert pis[1]["financial_direction"] == "OUTGOING"
    assert pis[1]["extracted_entities"][0]["project_role"] == "VENDOR"

    factory = client.app.state.testing_session_factory
    with factory() as db:
        events = get_trace_events("trace-mixed-fast-llm", db=db)
    event_names = [event.get("event_name") or event.get("event") for event in events]
    assert "MULTI_EVENT_SPLIT_APPLIED" in event_names
    split_index = event_names.index("MULTI_EVENT_SPLIT_APPLIED")
    llm_events = [
        event
        for event in events
        if (event.get("event_name") or event.get("event")) == "LLM_STARTED"
    ]
    assert [event["payload"].get("chunk_text") for event in llm_events] == ["از هادی پور 25 میلیون سیم خریدم"]
    assert all(event_names.index("LLM_STARTED") > split_index for event in llm_events)
    chunk_paths = [
        event["payload"]["processing_path"]
        for event in events
        if (event.get("event_name") or event.get("event")) == "MULTI_EVENT_CHUNK_PROCESSED"
    ]
    assert chunk_paths == ["FAST_PATH", "LLM"]


def test_final_response_role_repair_updates_structured_and_extracted_entities() -> None:
    payload = {
        "canonical_event_type": "FINANCIAL_EVENT",
        "semantic_action": "PAYMENT",
        "financial_direction": "OUTGOING",
        "matched_input_text": "به علی احمدی 5 میلیون دادم",
        "extracted_entities": [
            {"name": "علی احمدی", "project_role": "CLIENT", "type": "CLIENT"},
        ],
        "structured_interpretation": {
            "entities": [
                {"name": "علی احمدی", "project_role": "CLIENT"},
            ],
            "entity": {
                "name": "علی احمدی",
                "project_role": "CLIENT",
                "profile": {"project_role": "CLIENT"},
            },
        },
    }

    normalized = normalize_outgoing_payment_role(payload)

    assert normalized["extracted_entities"][0]["project_role"] == "OTHER"
    assert normalized["extracted_entities"][0]["type"] == "OTHER"
    assert normalized["structured_interpretation"]["entities"][0]["project_role"] == "OTHER"
    assert normalized["structured_interpretation"]["entity"]["project_role"] == "OTHER"
    assert normalized["structured_interpretation"]["entity"]["profile"]["project_role"] == "OTHER"


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
