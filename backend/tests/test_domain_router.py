import pytest
from fastapi.testclient import TestClient

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

    pending = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "علی کارفرمای پروژه است و 50 میلیون به حساب پروژه واریز کرد"},
    ).json()["interpretations"][0]

    assert pending["domain_route"]["domain"] == "MIXED"
    response = client.post(f"/pending-interpretations/{pending['id']}/confirm")
    assert response.status_code == 409
    assert response.json()["detail"] == "Mixed setup and financial input must be split before confirmation"


def test_invalid_project_path_is_not_defaulted(client: TestClient) -> None:
    response = client.post("/projects/1/natural-input", json={"text": "از علی 50 میلیون گرفتم بابت پروژه"})

    assert response.status_code == 404
