import pytest
from fastapi.testclient import TestClient
from tests.natural_input_helpers import natural_input_interpretation, natural_input_interpretations, submit_natural_input

from app.services.domain_router_service import DomainRouterService, DomainType
from app.services.entity_resolution_service import EntityResolutionService


def test_role_assignment_routes_to_setup_schema() -> None:
    route = DomainRouterService().route(
        "میثم کبیری کارفرمای پروژه است",
        {"intent": "SET_ROLE", "action": "SET_ROLE"},
    )

    assert route == {
        "domain": DomainType.SETUP.value,
        "confidence": route["confidence"],
        "required_schema": "setup_confirmation",
        "ui_mode": "SetupModal",
    }


def test_payment_routes_to_financial_schema() -> None:
    route = DomainRouterService().route(
        "از علی 50 میلیون گرفتم بابت پروژه",
        {
            "intent": "FINANCIAL",
            "action": "PAYMENT",
            "financial": {"amount": 50_000_000, "direction": "INCOMING"},
        },
    )

    assert route["domain"] == DomainType.FINANCIAL.value
    assert route["required_schema"] == "financial_confirmation"
    assert route["ui_mode"] == "FinancialModal"


def test_profile_update_fields_route_to_entity_update_schema_even_if_action_is_set_role() -> None:
    route = DomainRouterService().route(
        "شماره تماس میثم 09123456789",
        {
            "intent": "SETUP",
            "action": "SET_ROLE",
            "semantic_action": "SET_ROLE",
            "entities": [
                {
                    "name": "میثم",
                    "phone": "09123456789",
                    "field_updates": {"phone": "09123456789"},
                }
            ],
        },
    )

    assert route["domain"] == "ENTITY_UPDATE"
    assert route["required_schema"] == "entity_update_confirmation"
    assert route["ui_mode"] == "EntityUpdateModal"


def test_account_update_fields_route_to_entity_update_schema() -> None:
    route = DomainRouterService().route(
        "شماره حساب میثم 6037991234567890",
        {
            "intent": "SETUP",
            "action": "SET_ROLE",
            "semantic_action": "SET_ROLE",
            "extracted_entities": [
                {
                    "name": "میثم",
                    "account_number": "6037991234567890",
                }
            ],
        },
    )

    assert route["domain"] == "ENTITY_UPDATE"
    assert route["ui_mode"] == "EntityUpdateModal"


def test_mixed_sentence_requires_split_flow() -> None:
    route = DomainRouterService().route(
        "علی کارفرمای پروژه است و 50 میلیون به حساب پروژه واریز کرد",
        {
            "intent": "FINANCIAL",
            "action": "PAYMENT",
            "financial": {"amount": 50_000_000, "direction": "INCOMING"},
        },
    )

    assert route["domain"] == DomainType.MIXED.value
    assert route["required_schema"] == "split_confirmation"
    assert route["ui_mode"] == "SplitFlow"


def test_project_must_never_default_in_entity_resolution(client: TestClient) -> None:
    db = client.app.state.testing_session_factory()
    try:
        with pytest.raises(ValueError, match="Project must be explicitly resolved"):
            EntityResolutionService(db, 0)
    finally:
        db.close()


def test_mixed_pending_interpretation_blocks_confirmation(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    project = client.post("/projects", json={"name": "domain router"}).json()
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, text, project_id: {
            "intent": "FINANCIAL",
            "action": "PAYMENT",
            "entities": [{"name": "علی", "kind": "PERSON", "project_role": "CLIENT", "role_detail": None}],
            "financial": {"amount": 50_000_000, "direction": "IN", "payment_method": "BANK_TRANSFER", "due_date_text": None},
            "work": {"quantity": None, "unit": None, "description": None},
            "note": {"text": None},
            "confidence": 0.95,
            "ambiguity": False,
            "missing_fields": [],
            "reasoning_summary": "mixed setup and payment",
        },
    )

    pending = natural_input_interpretation(client, project["id"], "علی کارفرمای پروژه است و 50 میلیون به حساب پروژه واریز کرد")

    assert pending["domain_route"]["domain"] == "MIXED"
    response = client.post(f"/pending-interpretations/{pending['id']}/confirm")
    assert response.status_code == 409
    assert response.json()["detail"] == "Mixed setup and financial input must be split before confirmation"


def test_invalid_project_path_is_not_defaulted(client: TestClient) -> None:
    response = client.post("/projects/1/natural-input", json={"text": "از علی 50 میلیون گرفتم بابت پروژه"})

    assert response.status_code == 404


def test_field_updates_role_only_does_not_route_entity_update() -> None:
    route = DomainRouterService().route(
        "نقش کارگر به علی تخصیص داده شد",
        {
            "intent": "SET_ROLE",
            "action": "SET_ROLE",
            "entities": [
                {"name": "علی", "field_updates": {"role": "WORKER"}}
            ],
        },
    )
    assert route["domain"] == DomainType.SETUP.value
    assert route["ui_mode"] == "SetupModal"


def test_field_updates_project_role_does_not_route_entity_update() -> None:
    route = DomainRouterService().route(
        "علی به عنوان کارفرما اضافه شد",
        {
            "intent": "SET_ROLE",
            "action": "SET_ROLE",
            "entities": [
                {"name": "علی", "field_updates": {"project_role": "CLIENT"}}
            ],
        },
    )
    assert route["domain"] == DomainType.SETUP.value
    assert route["ui_mode"] == "SetupModal"


def test_field_updates_role_detail_does_not_route_entity_update() -> None:
    route = DomainRouterService().route(
        "جعفری لوله کش به پروژه اضافه شد",
        {
            "intent": "SET_ROLE",
            "action": "SET_ROLE",
            "entities": [
                {"name": "جعفری", "field_updates": {"role_detail": "لوله کش"}}
            ],
        },
    )
    assert route["domain"] == DomainType.SETUP.value
    assert route["ui_mode"] == "SetupModal"


def test_field_updates_phone_routes_to_entity_update() -> None:
    route = DomainRouterService().route(
        "شماره تماس علی 09123456789",
        {
            "intent": "SETUP",
            "action": "SET_ROLE",
            "entities": [
                {
                    "name": "علی",
                    "field_updates": {"phone": "09123456789"},
                }
            ],
        },
    )
    assert route["domain"] == "ENTITY_UPDATE"
    assert route["ui_mode"] == "EntityUpdateModal"


def test_field_updates_account_number_routes_to_entity_update() -> None:
    route = DomainRouterService().route(
        "شماره حساب علی 6037991234567890",
        {
            "intent": "SETUP",
            "action": "SET_ROLE",
            "entities": [
                {
                    "name": "علی",
                    "field_updates": {"account_number": "6037991234567890"},
                }
            ],
        },
    )
    assert route["domain"] == "ENTITY_UPDATE"
    assert route["ui_mode"] == "EntityUpdateModal"


def test_field_updates_daily_rate_routes_to_entity_update() -> None:
    route = DomainRouterService().route(
        "دستمزد روزانه علی 1200000 تومان",
        {
            "intent": "SETUP",
            "action": "SET_ROLE",
            "entities": [
                {
                    "name": "علی",
                    "field_updates": {"daily_rate": 1200000},
                }
            ],
        },
    )
    assert route["domain"] == "ENTITY_UPDATE"
    assert route["ui_mode"] == "EntityUpdateModal"
