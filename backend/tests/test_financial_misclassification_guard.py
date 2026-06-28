import pytest
from fastapi.testclient import TestClient

from app.services.llm_v2_interpreter import LLMv2Interpreter
from app.services.prompts.llm_v2_prompt import detect_prompt_domain
from tests.natural_input_helpers import natural_input_interpretation


def _project(client: TestClient, name: str = "financial guard") -> dict:
    response = client.post("/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _assert_incoming_payment(item: dict, amount: str, name: str | None = None) -> None:
    assert item["canonical_event_type"] == "FINANCIAL_EVENT"
    assert item["semantic_action"] == "PAYMENT"
    assert item["financial_direction"] == "INCOMING"
    assert item["extracted_amount"] == amount
    assert item["payment_method"] == "BANK_TRANSFER"
    assert item["extracted_entities"][0]["type"] == "CLIENT"
    if name is not None:
        assert item["extracted_entities"][0]["name"] == name


@pytest.mark.parametrize(
    ("text", "amount", "name"),
    [
        ("وحید ۵۰۰ ملیون ریخت به حساب", "500000000.00", "وحید"),
        ("وحید ۵۰۰ میلیون ریخت به حساب", "500000000.00", "وحید"),
        ("میثم ۱۰۰ میلیون واریز کرد", "100000000.00", "میثم"),
        ("کارفرما ۲۰ میلیون زد به حساب", "20000000.00", "کارفرما"),
        ("از وحید ۵۰۰ میلیون گرفتم", "500000000.00", "وحید"),
    ],
)
def test_money_movement_with_amount_is_incoming_financial(
    client: TestClient,
    text: str,
    amount: str,
    name: str,
) -> None:
    project = _project(client, f"guard-{name}")

    item = natural_input_interpretation(client, project["id"], text)

    _assert_incoming_payment(item, amount, name)


def test_llm_setup_result_with_money_movement_is_repaired_to_financial() -> None:
    result = LLMv2Interpreter()._coerce(
        {
            "intent": "SETUP",
            "action": "SET_ROLE",
            "entities": [{"name": "وحید", "kind": "PERSON", "project_role": "OTHER"}],
            "financial": {"amount": None, "direction": "NONE", "payment_method": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.7,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "incorrect setup",
        },
        "وحید ۵۰۰ ملیون ریخت به حساب",
    )

    assert result["intent"] == "FINANCIAL"
    assert result["action"] == "PAYMENT_IN"
    assert result["financial"]["amount"] == 500000000
    assert result["financial"]["direction"] == "IN"
    assert result["financial"]["payment_method"] == "BANK_TRANSFER"
    assert result["entities"][0]["project_role"] == "CLIENT"


def test_prompt_routes_account_deposit_to_financial() -> None:
    assert detect_prompt_domain("وحید ۵۰۰ ملیون ریخت به حساب") == "financial"
    assert detect_prompt_domain("کارفرما ۲۰ میلیون زد به حساب") == "financial"


@pytest.mark.parametrize(
    "text",
    [
        "وحید کارفرمای پروژه است",
        "دستمزد روزانه مش رحیم ۱۲۰۰۰۰۰ تومان است",
        "شماره حساب وحید ۵۰۰۱۲۳ است",
    ],
)
def test_setup_profile_inputs_do_not_become_financial(client: TestClient, text: str) -> None:
    project = _project(client, "setup-profile-guard")

    item = natural_input_interpretation(client, project["id"], text)

    assert item["canonical_event_type"] == "SETUP_EVENT"
    assert item["financial_direction"] is None


def test_purchase_payment_stays_outgoing_vendor_purchase(client: TestClient) -> None:
    project = _project(client, "purchase guard")

    item = natural_input_interpretation(client, project["id"], "از هادی پور ۲۰ میلیون سیم خریدم و پرداخت کردم")

    assert item["canonical_event_type"] == "FINANCIAL_EVENT"
    assert item["semantic_action"] == "PURCHASE_PAID"
    assert item["financial_direction"] == "OUTGOING"
    assert item["extracted_amount"] == "20000000.00"
    assert item["extracted_entities"][0]["type"] == "VENDOR"


def test_worker_payment_stays_outgoing(client: TestClient) -> None:
    project = _project(client, "worker outgoing guard")

    item = natural_input_interpretation(client, project["id"], "به مش رحیم ۲ میلیون پرداخت کردم")

    assert item["canonical_event_type"] == "FINANCIAL_EVENT"
    assert item["semantic_action"] == "PAYMENT"
    assert item["financial_direction"] == "OUTGOING"
    assert item["extracted_amount"] == "2000000.00"
