import pytest
from fastapi.testclient import TestClient


def _valid_llm_v2_setup(name: str = "ریاحی") -> dict:
    return {
        "intent": "SETUP",
        "action": "ADD_ENTITY",
        "entities": [
            {
                "name": name,
                "kind": "PERSON",
                "project_role": "SKILLED_WORKER",
                "role_detail": "سرامیک کار",
            }
        ],
        "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
        "work": {"quantity": None, "unit": None, "description": None},
        "note": {"text": None},
        "confidence": 0.92,
        "ambiguity": False,
        "missing_fields": [],
        "reasoning_summary": "ثبت استادکار پروژه",
    }


def _valid_llm_v2_financial(action: str, amount: int, direction: str = "OUT") -> dict:
    return {
        "intent": "FINANCIAL",
        "action": action,
        "entities": [
            {
                "name": "هادی‌پور سیم",
                "kind": "COMPANY",
                "project_role": "VENDOR",
                "role_detail": "سیم فروش",
            }
        ],
        "financial": {
            "amount": amount,
            "direction": direction,
            "payment_method": "BANK_TRANSFER",
            "due_date_text": None,
        },
        "work": {"quantity": None, "unit": None, "description": None},
        "note": {"text": None},
        "confidence": 0.95,
        "ambiguity": False,
        "missing_fields": [],
        "reasoning_summary": "برداشت مالی ساختاریافته",
    }


def _create_project(client: TestClient) -> dict:
    response = client.post("/projects", json={"name": "LLM audit"})
    assert response.status_code == 201
    return response.json()


def test_llm_v2_is_attempted_before_legacy(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, project_id: calls.append("llm_v2") or _valid_llm_v2_setup(),
    )
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: calls.append("legacy") or pytest.fail("legacy should not run after valid LLM v2"),
    )

    project = _create_project(client)
    response = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "ریاحی سرامیک کار به پروژه اضافه شد"},
    )

    assert response.status_code == 201
    assert calls == ["llm_v2"]
    assert response.json()["interpretations"][0]["structured_interpretation"]["intent"] == "SETUP"


def test_legacy_is_not_called_when_llm_v2_returns_valid_output(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, project_id: _valid_llm_v2_setup(),
    )
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: pytest.fail("legacy extract_graph should not run after valid LLM v2 output"),
    )

    project = _create_project(client)
    client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "ریاحی سرامیک کار به پروژه اضافه شد"},
    )


def test_legacy_is_called_when_llm_v2_fails_validation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, project_id: {"intent": "SETUP", "entities": []},
    )
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: calls.append("legacy") or {
            "intent": "SETUP",
            "entities": [{"name": "ریاحی", "role_guess": "SKILLED_WORKER", "role_detail": "سرامیک کار"}],
            "confidence": 0.8,
        },
    )

    project = _create_project(client)
    response = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "ریاحی سرامیک کار به پروژه اضافه شد"},
    )

    assert response.status_code == 201
    assert calls == ["legacy"]
    assert response.json()["interpretations"][0]["structured_interpretation"] is None


def test_semantic_rule_engine_not_used_in_primary_llm_v2_success_path(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, project_id: _valid_llm_v2_setup(),
    )
    monkeypatch.setattr(
        "app.services.semantic_normalizer.SemanticRuleEngine.classify",
        lambda self, llm_output, text, context: pytest.fail("SemanticRuleEngine should not run in primary path"),
    )

    project = _create_project(client)
    client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "ریاحی سرامیک کار به پروژه اضافه شد"},
    )


def test_paid_purchase_from_llm_v2_does_not_create_payables(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, project_id: _valid_llm_v2_financial("PURCHASE_PAID", 5_000_000),
    )
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: pytest.fail("legacy should not run after valid LLM v2"),
    )

    project = _create_project(client)
    client.post(
        f"/projects/{project['id']}/workers",
        json={"name": "هادی‌پور سیم", "type": "VENDOR"},
    )
    draft = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "از هادی‌پور سیم ۵ میلیون خرید کردم"},
    ).json()["interpretations"][0]

    assert draft["semantic_action"] == "PURCHASE_PAID"
    before = client.get(f"/projects/{project['id']}/operating-summary").json()
    assert before["open_payables"] == "0"

    confirmed = client.post(f"/pending-interpretations/{draft['id']}/confirm").json()
    assert confirmed["payments"][0]["direction"] == "OUTGOING"
    assert confirmed["invoices"] == []
    after = client.get(f"/projects/{project['id']}/operating-summary").json()
    assert after["open_payables"] == "0"


def test_llm_v2_financial_unknown_entity_must_block_confirmation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, project_id: {
            **_valid_llm_v2_financial("PAYMENT_OUT", 5_000_000),
            "entities": [
                {
                    "name": "ناشناس",
                    "kind": "UNKNOWN",
                    "project_role": "VENDOR",
                    "role_detail": None,
                }
            ],
        },
    )
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: pytest.fail("legacy should not run after valid LLM v2"),
    )

    project = _create_project(client)
    draft = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "ناشناس ۵ میلیون گرفت"},
    ).json()["interpretations"][0]

    response = client.post(f"/pending-interpretations/{draft['id']}/confirm")
    assert response.status_code == 409


def test_llm_v2_financial_missing_amount_must_block_confirmation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, project_id: {
            **_valid_llm_v2_financial("PAYMENT_OUT", 5_000_000),
            "financial": {"amount": None, "direction": "NONE", "payment_method": None, "due_date_text": None},
            "missing_fields": ["amount", "direction"],
            "ambiguity": True,
        },
    )
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: pytest.fail("legacy should not run after valid LLM v2"),
    )

    project = _create_project(client)
    client.post(
        f"/projects/{project['id']}/workers",
        json={"name": "هادی‌پور سیم", "type": "VENDOR"},
    )
    draft = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "حساب هادی‌پور معلوم نیست"},
    ).json()["interpretations"][0]

    response = client.post(f"/pending-interpretations/{draft['id']}/confirm")
    assert response.status_code == 409


def test_llm_v2_financial_missing_direction_must_block_confirmation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, project_id: {
            **_valid_llm_v2_financial("PAYMENT_OUT", 5_000_000),
            "financial": {"amount": 5_000_000, "direction": "NONE", "payment_method": None, "due_date_text": None},
            "missing_fields": ["direction"],
            "ambiguity": True,
        },
    )
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: pytest.fail("legacy should not run after valid LLM v2"),
    )

    project = _create_project(client)
    worker = client.post(
        f"/projects/{project['id']}/workers",
        json={"name": "هادی‌پور سیم", "type": "VENDOR"},
    ).json()
    draft = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "حساب هادی‌پور جهتش معلوم نیست"},
    ).json()["interpretations"][0]
    draft = client.patch(
        f"/pending-interpretations/{draft['id']}",
        json={"suggested_entity_id": worker["id"], "extracted_entities": [{"name": "هادی‌پور سیم", "type": "VENDOR"}]},
    ).json()

    response = client.post(f"/pending-interpretations/{draft['id']}/confirm")
    assert response.status_code == 409


@pytest.mark.parametrize(
    ("text", "name", "role_detail"),
    [
        ("ریاحی سرامیک کار به پروژه اضافه شد", "ریاحی", "سرامیک کار"),
        ("با ریاحی صحبت کردم که از هفته بعد بیاد سر پروژه", "ریاحی", "استادکار"),
        ("ریاحی سرامیک کاره قراره بیاد", "ریاحی", "سرامیک کار"),
        ("نجار آقای کریمی قراره ملحق بشه به پروژه", "آقای کریمی", "نجار"),
        ("با احمدی قالب بند قرارداد بستم", "احمدی", "قالب بند"),
        ("کناف کار رضایی از فردا میاد", "رضایی", "کناف کار"),
    ],
)
def test_llm_v2_flexible_persian_skilled_setup_creates_pending_only(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    name: str,
    role_detail: str,
) -> None:
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, raw_text, project_id: {
            **_valid_llm_v2_setup(name),
            "entities": [
                {
                    "name": name,
                    "kind": "PERSON",
                    "project_role": "SKILLED_WORKER",
                    "role_detail": role_detail,
                }
            ],
            "reasoning_summary": f"ثبت {name} به عنوان {role_detail}",
        },
    )
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: pytest.fail("legacy should not run after valid LLM v2"),
    )

    project = _create_project(client)
    response = client.post(f"/projects/{project['id']}/natural-input", json={"text": text})

    assert response.status_code == 201
    draft = response.json()["interpretations"][0]
    assert draft["canonical_event_type"] == "SETUP_EVENT"
    assert draft["semantic_action"] == "SETUP"
    assert draft["extracted_entities"][0]["project_role"] == "SKILLED_WORKER"
    assert role_detail in draft["extracted_entities"][0]["role_detail"]
    assert draft["structured_interpretation"]["intent"] == "SETUP"
    assert client.get(f"/projects/{project['id']}/workers").json() == []
    assert client.get(f"/projects/{project['id']}/payments").json() == []
    assert client.get(f"/projects/{project['id']}/invoices").json() == []
    assert client.get(f"/projects/{project['id']}/worker-states").json() == []
