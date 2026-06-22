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


def _valid_llm_v2_financial(
    action: str,
    amount: int,
    direction: str = "OUT",
    name: str = "هادی‌پور سیم",
    project_role: str = "VENDOR",
    confidence: float = 0.95,
    ambiguity: bool = False,
    payment_method: str = "BANK_TRANSFER",
    due_date_text: str | None = None,
) -> dict:
    return {
        "intent": "FINANCIAL",
        "action": action,
        "entities": [
            {
                "name": name,
                "kind": "COMPANY" if project_role == "VENDOR" else "PERSON",
                "project_role": project_role,
                "role_detail": "سیم فروش",
            }
        ],
        "financial": {
            "amount": amount,
            "direction": direction,
            "payment_method": payment_method,
            "due_date_text": due_date_text,
        },
        "work": {"quantity": None, "unit": None, "description": None},
        "note": {"text": None},
        "confidence": confidence,
        "ambiguity": ambiguity,
        "missing_fields": [],
        "reasoning_summary": "برداشت مالی ساختاریافته",
    }


def _create_project(client: TestClient) -> dict:
    response = client.post("/projects", json={"name": "LLM audit"})
    assert response.status_code == 201
    return response.json()


def _confirm_financial(client: TestClient, draft: dict, payload: dict | None = None) -> dict:
    response = client.post(
        f"/pending-interpretations/{draft['id']}/confirm",
        json=payload or {},
    )
    assert response.status_code == 200
    body = response.json()
    if body.get("status") == "ENTITY_RESOLVED":
        response = client.post(
            f"/pending-interpretations/{draft['id']}/confirm",
            json={"entity_id": body["entity_id"], "confirmed": True},
        )
        assert response.status_code == 200
        body = response.json()
    return body


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
    assert response.json()["interpretations"][0]["structured_interpretation"]["intent"] == "SET_ROLE"


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


def test_llm_v2_setup_repairs_skilled_role_from_raw_text(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, project_id: {
            **_valid_llm_v2_setup("ریاحی"),
            "entities": [
                {
                    "name": "ریاحی",
                    "kind": "UNKNOWN",
                    "project_role": "OTHER",
                    "role_detail": "سرمایه سرامیک",
                }
            ],
            "confidence": 1,
        },
    )
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: pytest.fail("legacy should not run after valid LLM v2"),
    )

    project = _create_project(client)
    response = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "ریاحی سرامیک کار به پروژه اضافه شد"},
    )

    assert response.status_code == 201
    draft = response.json()["interpretations"][0]
    assert draft["canonical_event_type"] == "SETUP_EVENT"
    assert draft["semantic_action"] == "SET_ROLE"
    assert draft["payment_method"] is None
    assert draft["extracted_entities"] == [
        {
            "name": "ریاحی",
            "kind": "UNKNOWN",
            "project_role": "SKILLED_WORKER",
            "role_detail": "سرامیک کار",
            "type": "SKILLED_WORKER",
        }
    ]
    assert draft["structured_interpretation"]["entities"][0]["project_role"] == "SKILLED_WORKER"
    assert draft["structured_interpretation"]["entities"][0]["role_detail"] == "سرامیک کار"


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
    vendor = client.post(
        f"/projects/{project['id']}/workers",
        json={"name": "هادی‌پور سیم", "type": "VENDOR"},
    ).json()
    draft = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "از هادی‌پور سیم ۵ میلیون خرید کردم"},
    ).json()["interpretations"][0]

    assert draft["semantic_action"] == "PURCHASE_PAID"
    before = client.get(f"/projects/{project['id']}/operating-summary").json()
    assert before["open_payables"] == "0"

    confirmed = _confirm_financial(client, draft, {"selected_person_id": vendor["id"]})
    assert confirmed["payments"][0]["direction"] == "OUTGOING"
    assert confirmed["invoices"] == []
    after = client.get(f"/projects/{project['id']}/operating-summary").json()
    assert after["open_payables"] == "0"


def test_edited_llm_v2_purchase_to_debt_creates_invoice_not_payment(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, project_id: _valid_llm_v2_financial(
            "PURCHASE_PAID",
            25_000_000,
            payment_method="CASH",
        ),
    )
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: pytest.fail("legacy should not run after valid LLM v2"),
    )

    project = _create_project(client)
    vendor = client.post(
        f"/projects/{project['id']}/workers",
        json={"name": "هادی‌پور سیم", "type": "VENDOR"},
    ).json()
    draft = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "از هادی‌پور سیم ۲۵ میلیون سیم خریدم و پرداخت کردم"},
    ).json()["interpretations"][0]

    edit = client.patch(
        f"/pending-interpretations/{draft['id']}",
        json={
            "semantic_action": "DEBT_CREATED",
            "financial_direction": "DEBT",
            "payment_method": None,
            "description": "edited unpaid purchase",
        },
    )
    assert edit.status_code == 200

    confirmed = _confirm_financial(client, draft, {"selected_person_id": vendor["id"]})

    assert confirmed["payments"] == []
    assert confirmed["invoices"][0]["vendor_id"] == vendor["id"]
    assert confirmed["invoices"][0]["total_amount"] == "25000000.00"


def test_edited_llm_v2_financial_direction_incoming_is_respected(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, project_id: _valid_llm_v2_financial(
            "PAYMENT_OUT",
            50_000_000,
            direction="OUT",
            name="علی",
            project_role="CLIENT",
            payment_method="BANK_TRANSFER",
        ),
    )
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: pytest.fail("legacy should not run after valid LLM v2"),
    )

    project = _create_project(client)
    client_worker = client.post(
        f"/projects/{project['id']}/workers",
        json={"name": "علی", "type": "CLIENT"},
    ).json()
    draft = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "از علی ۵۰ میلیون گرفتم بابت پروژه"},
    ).json()["interpretations"][0]

    edit = client.patch(
        f"/pending-interpretations/{draft['id']}",
        json={
            "semantic_action": "PAYMENT",
            "financial_direction": "INCOMING",
            "payment_method": "BANK_TRANSFER",
        },
    )
    assert edit.status_code == 200

    confirmed = _confirm_financial(client, draft, {"selected_person_id": client_worker["id"]})

    assert confirmed["payments"][0]["direction"] == "INCOMING"
    assert confirmed["payments"][0]["entity_id"] == client_worker["id"]


def test_edited_llm_v2_payment_method_check_is_respected(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, project_id: _valid_llm_v2_financial(
            "PURCHASE_PAID",
            25_000_000,
            payment_method="CASH",
        ),
    )
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: pytest.fail("legacy should not run after valid LLM v2"),
    )

    project = _create_project(client)
    vendor = client.post(
        f"/projects/{project['id']}/workers",
        json={"name": "هادی‌پور سیم", "type": "VENDOR"},
    ).json()
    draft = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "به هادی‌پور سیم چک ۲۵ میلیونی دادم برای سیم"},
    ).json()["interpretations"][0]

    edit = client.patch(
        f"/pending-interpretations/{draft['id']}",
        json={"payment_method": "CHECK", "financial_direction": "OUTGOING"},
    )
    assert edit.status_code == 200

    confirmed = _confirm_financial(client, draft, {"selected_person_id": vendor["id"]})

    assert confirmed["payments"][0]["type"] == "CHECK"
    assert confirmed["payments"][0]["direction"] == "OUTGOING"


def test_edited_llm_v2_debt_to_generic_payment_does_not_use_stale_debt_action(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, project_id: _valid_llm_v2_financial(
            "DEBT_CREATED",
            25_000_000,
            payment_method=None,
        ),
    )
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: pytest.fail("legacy should not run after valid LLM v2"),
    )

    project = _create_project(client)
    vendor = client.post(
        f"/projects/{project['id']}/workers",
        json={"name": "هادی‌پور سیم", "type": "VENDOR"},
    ).json()
    draft = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "از هادی‌پور سیم ۲۵ میلیون سیم خریدم و بدهکار شدم"},
    ).json()["interpretations"][0]

    edit = client.patch(
        f"/pending-interpretations/{draft['id']}",
        json={
            "semantic_action": "PAYMENT",
            "financial_direction": "OUTGOING",
            "payment_method": "CASH",
        },
    )
    assert edit.status_code == 200

    confirmed = _confirm_financial(client, draft, {"selected_person_id": vendor["id"]})

    assert confirmed["invoices"] == []
    assert confirmed["payments"][0]["type"] == "CASH"
    assert confirmed["payments"][0]["direction"] == "OUTGOING"


def test_edited_llm_v2_deferred_payment_preserves_check_direction(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, project_id: _valid_llm_v2_financial(
            "PAYMENT_OUT",
            25_000_000,
            payment_method="BANK_TRANSFER",
        ),
    )
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: pytest.fail("legacy should not run after valid LLM v2"),
    )

    project = _create_project(client)
    vendor = client.post(
        f"/projects/{project['id']}/workers",
        json={"name": "هادی‌پور سیم", "type": "VENDOR"},
    ).json()
    draft = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "به هادی‌پور سیم ۲۵ میلیون دادم"},
    ).json()["interpretations"][0]

    edit = client.patch(
        f"/pending-interpretations/{draft['id']}",
        json={
            "semantic_action": "DEFERRED_PAYMENT",
            "financial_direction": "DEFERRED",
            "payment_method": "CHECK",
            "due_date": "۱۴ مهر ۱۴۰۵",
        },
    )
    assert edit.status_code == 200

    confirmed = _confirm_financial(client, draft, {"selected_person_id": vendor["id"]})

    assert confirmed["invoices"] == []
    assert confirmed["payments"][0]["type"] == "CHECK"
    assert confirmed["payments"][0]["direction"] == "DEFERRED"
    assert confirmed["payments"][0]["due_date"] == "۱۴ مهر ۱۴۰۵"


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
    if response.status_code == 200 and response.json().get("status") == "ENTITY_RESOLVED":
        response = client.post(
            f"/pending-interpretations/{draft['id']}/confirm",
            json={"entity_id": response.json()["entity_id"], "confirmed": True},
        )
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
    if response.status_code == 200 and response.json().get("status") == "ENTITY_RESOLVED":
        response = client.post(
            f"/pending-interpretations/{draft['id']}/confirm",
            json={"entity_id": response.json()["entity_id"], "confirmed": True},
        )
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
    if response.status_code == 200 and response.json().get("status") == "ENTITY_RESOLVED":
        response = client.post(
            f"/pending-interpretations/{draft['id']}/confirm",
            json={"entity_id": response.json()["entity_id"], "confirmed": True},
        )
    assert response.status_code == 409


def test_llm_v2_new_vendor_paid_purchase_auto_creates_vendor_after_confirm(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, project_id: _valid_llm_v2_financial(
            "PURCHASE_PAID",
            5_000_000,
            name="هادیپور",
        ),
    )
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: pytest.fail("legacy should not run after valid LLM v2"),
    )

    project = _create_project(client)
    draft = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "از هادیپور ۵ میلیون سیم خریدم"},
    ).json()["interpretations"][0]

    assert draft["suggested_entity_id"] is None
    assert client.get(f"/projects/{project['id']}/workers").json() == []

    unresolved = client.post(f"/pending-interpretations/{draft['id']}/confirm")
    assert unresolved.status_code == 409

    confirmed = client.post(
        f"/pending-interpretations/{draft['id']}/confirm",
        json={"create_new": True},
    )
    assert confirmed.status_code == 200
    resolved = confirmed.json()
    assert resolved["status"] == "ENTITY_RESOLVED"
    body = _confirm_financial(client, draft, {"entity_id": resolved["entity_id"], "confirmed": True})
    assert body["workers"][0]["name"] == "هادیپور"
    assert body["workers"][0]["type"] == "VENDOR"
    assert body["payments"][0]["entity_id"] == resolved["entity_id"]
    assert body["payments"][0]["amount"] == "5000000.00"
    assert body["invoices"] == []
    assert len(client.get(f"/projects/{project['id']}/workers").json()) == 1


def test_llm_v2_new_vendor_unpaid_purchase_auto_creates_payable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, project_id: _valid_llm_v2_financial(
            "DEBT_CREATED",
            10_000_000,
            name="هادیپور",
        ),
    )
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: pytest.fail("legacy should not run after valid LLM v2"),
    )

    project = _create_project(client)
    draft = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "از هادیپور ۱۰ میلیون سیم خریدم ولی پولش را ندادم"},
    ).json()["interpretations"][0]

    unresolved = client.post(f"/pending-interpretations/{draft['id']}/confirm")
    assert unresolved.status_code == 409

    confirmed = client.post(
        f"/pending-interpretations/{draft['id']}/confirm",
        json={"create_new": True},
    )
    assert confirmed.status_code == 200
    resolved = confirmed.json()
    assert resolved["status"] == "ENTITY_RESOLVED"
    body = _confirm_financial(client, draft, {"entity_id": resolved["entity_id"], "confirmed": True})
    assert body["workers"][0]["type"] == "VENDOR"
    assert body["invoices"][0]["vendor_id"] == resolved["entity_id"]
    assert body["invoices"][0]["total_amount"] == "10000000.00"
    assert body["payments"] == []


def test_llm_v2_new_vendor_check_purchase_auto_creates_check_payment_with_due_date(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, project_id: _valid_llm_v2_financial(
            "CHECK_PAYMENT",
            50_000_000,
            name="هادیپور",
            payment_method="CHECK",
            due_date_text="۱۴ مهر",
        ),
    )
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: pytest.fail("legacy should not run after valid LLM v2"),
    )

    project = _create_project(client)
    draft = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "از هادیپور ۵۰ میلیون سیم خریدم و برای ۱۴ مهر چک دادم"},
    ).json()["interpretations"][0]

    unresolved = client.post(f"/pending-interpretations/{draft['id']}/confirm")
    assert unresolved.status_code == 409

    confirmed = client.post(
        f"/pending-interpretations/{draft['id']}/confirm",
        json={"create_new": True},
    )
    assert confirmed.status_code == 200
    resolved = confirmed.json()
    assert resolved["status"] == "ENTITY_RESOLVED"
    payment = _confirm_financial(client, draft, {"entity_id": resolved["entity_id"], "confirmed": True})["payments"][0]
    assert payment["type"] == "CHECK"
    assert payment["due_date"] == "۱۴ مهر"


def test_llm_v2_existing_vendor_reused_for_compact_purchase_name(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, project_id: _valid_llm_v2_financial(
            "PURCHASE_PAID",
            5_000_000,
            name="هادیپور",
        ),
    )
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: pytest.fail("legacy should not run after valid LLM v2"),
    )

    project = _create_project(client)
    vendor = client.post(
        f"/projects/{project['id']}/workers",
        json={"name": "هادی‌پور سیم", "type": "VENDOR"},
    ).json()
    draft = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "از هادیپور ۵ میلیون سیم خریدم"},
    ).json()["interpretations"][0]

    assert draft["suggested_entity_id"] is None
    unresolved = client.post(f"/pending-interpretations/{draft['id']}/confirm")
    assert unresolved.status_code == 409

    confirmed = client.post(
        f"/pending-interpretations/{draft['id']}/confirm",
        json={"selected_person_id": vendor["id"]},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "ENTITY_RESOLVED"
    body = _confirm_financial(client, draft, {"entity_id": vendor["id"], "confirmed": True})
    assert body["payments"][0]["entity_id"] == vendor["id"]
    assert len(client.get(f"/projects/{project['id']}/workers").json()) == 1


def test_llm_v2_ambiguous_vendor_purchase_requires_selection(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, project_id: _valid_llm_v2_financial(
            "PURCHASE_PAID",
            5_000_000,
            name="هادیپور",
            ambiguity=True,
        ),
    )
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: pytest.fail("legacy should not run after valid LLM v2"),
    )

    project = _create_project(client)
    client.post(f"/projects/{project['id']}/workers", json={"name": "هادیپور سیم", "type": "VENDOR"})
    client.post(f"/projects/{project['id']}/workers", json={"name": "هادیپور ابزار", "type": "VENDOR"})
    draft = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "از هادیپور ۵ میلیون سیم خریدم"},
    ).json()["interpretations"][0]

    assert draft["suggested_entity_id"] is None
    response = client.post(f"/pending-interpretations/{draft['id']}/confirm")
    assert response.status_code == 409
    assert len(client.get(f"/projects/{project['id']}/workers").json()) == 2


@pytest.mark.parametrize("project_role", ["DAILY_WORKER", "SKILLED_WORKER", "CLIENT"])
def test_llm_v2_non_vendor_financial_entity_is_not_auto_created(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    project_role: str,
) -> None:
    action = "PAYMENT_IN" if project_role == "CLIENT" else "PAYMENT_OUT"
    direction = "IN" if project_role == "CLIENT" else "OUT"
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, project_id: _valid_llm_v2_financial(
            action,
            5_000_000,
            direction=direction,
            name="نادری",
            project_role=project_role,
        ),
    )
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: pytest.fail("legacy should not run after valid LLM v2"),
    )

    project = _create_project(client)
    draft = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "۵ میلیون به نادری دادم"},
    ).json()["interpretations"][0]

    response = client.post(f"/pending-interpretations/{draft['id']}/confirm")
    assert response.status_code == 409
    assert client.get(f"/projects/{project['id']}/workers").json() == []


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
    assert draft["semantic_action"] == "SET_ROLE"
    assert draft["extracted_entities"][0]["project_role"] == "SKILLED_WORKER"
    assert role_detail in draft["extracted_entities"][0]["role_detail"]
    assert draft["structured_interpretation"]["intent"] == "SET_ROLE"
    assert draft["structured_interpretation"]["action"] == "SET_ROLE"
    assert client.get(f"/projects/{project['id']}/workers").json() == []
    assert client.get(f"/projects/{project['id']}/payments").json() == []
    assert client.get(f"/projects/{project['id']}/invoices").json() == []
    assert client.get(f"/projects/{project['id']}/worker-states").json() == []


def test_create_new_confirmation_creates_skilled_worker_with_role_detail(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, raw_text, project_id: {
            **_valid_llm_v2_setup("جعفری"),
            "entities": [
                {
                    "name": "جعفری",
                    "kind": "PERSON",
                    "project_role": "SKILLED_WORKER",
                    "role_detail": "لوله کش",
                }
            ],
            "reasoning_summary": "ثبت جعفری به عنوان لوله کش",
        },
    )
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: pytest.fail("legacy should not run after valid LLM v2"),
    )

    project = _create_project(client)
    draft = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "جعفری لوله کش به پروژه اضافه شد"},
    ).json()["interpretations"][0]

    response = client.post(
        f"/pending-interpretations/{draft['id']}/confirm",
        json={
            "create_new": True,
            "name": "جعفری",
            "role": "SKILLED_WORKER",
            "role_detail": "لوله کش",
        },
    )

    assert response.status_code == 200
    assert response.json().get("status") != "NEEDS_SELECTION"
    workers = client.get(f"/projects/{project['id']}/workers").json()
    assert len(workers) == 1
    assert workers[0]["name"] == "جعفری"
    assert workers[0]["type"] == "SKILLED_WORKER"
    assert workers[0]["role_detail"] == "لوله کش"
