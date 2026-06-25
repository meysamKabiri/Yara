from typing import Any

from fastapi.testclient import TestClient

from app.core import unified_pipeline
from tests.natural_input_helpers import natural_input_interpretation


def _create_project(client: TestClient, name: str) -> dict[str, Any]:
    response = client.post("/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _financial_graph() -> dict[str, Any]:
    return {
        "entity": "میثم",
        "entities": [{"type": "CLIENT", "name": "میثم"}],
        "amount_text": "۲۰۰ میلیون",
        "confidence": 0.9,
    }


def _shadow_result() -> dict[str, Any]:
    return {
        "intent": "FINANCIAL",
        "entities": [{"name": "میثم", "kind": "PERSON"}],
        "financial": {"amount": 200000000, "direction": "OUT"},
        "work": {"quantity": None, "unit": None},
        "confidence": 0.9,
        "ambiguity": False,
        "missing_fields": [],
        "reasoning": "test shadow",
    }


def _normalize_interpretation(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "canonical_event_type": value["canonical_event_type"],
        "semantic_action": value["semantic_action"],
        "matched_input_text": value["matched_input_text"],
        "extracted_entities": value["extracted_entities"],
        "extracted_amount": value["extracted_amount"],
        "extracted_quantity": value["extracted_quantity"],
        "payment_method": value["payment_method"],
        "financial_direction": value["financial_direction"],
        "due_date": value["due_date"],
        "description": value["description"],
        "confidence": value["confidence"],
        "status": value["status"],
    }


def _model_to_read_shape(item: Any) -> dict[str, Any]:
    return {
        "canonical_event_type": item.canonical_event_type,
        "semantic_action": item.semantic_action,
        "matched_input_text": item.matched_input_text,
        "extracted_entities": item.extracted_entities,
        "extracted_amount": (
            str(item.extracted_amount) if item.extracted_amount is not None else None
        ),
        "extracted_quantity": (
            str(item.extracted_quantity) if item.extracted_quantity is not None else None
        ),
        "payment_method": item.payment_method,
        "financial_direction": (
            item.financial_direction.value if item.financial_direction is not None else None
        ),
        "due_date": item.due_date,
        "description": item.description,
        "confidence": item.confidence,
        "status": item.status.value,
    }


def test_natural_input_route_matches_unified_pipeline_output(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.api.projects.extract_graph", lambda text: _financial_graph())
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, raw_text, project_id, db=None: _shadow_result(),
    )
    route_project = _create_project(client, "Route")
    direct_project = _create_project(client, "Direct")

    route_item = _normalize_interpretation(
        natural_input_interpretation(client, route_project["id"], "میثم ۲۰۰ میلیون پول داد")
    )

    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        direct_items = unified_pipeline.process_input(
            db,
            direct_project["id"],
            "میثم ۲۰۰ میلیون پول داد",
        )
        direct_item = _model_to_read_shape(direct_items[0])

    assert route_item == direct_item
    assert route_item["canonical_event_type"] == "FINANCIAL_EVENT"
    assert route_item["extracted_amount"] == "200000000.00"
    assert route_item["extracted_entities"][0]["name"] == "میثم"
    assert route_item["extracted_entities"][0]["type"] == "CLIENT"


def test_unified_pipeline_preserves_setup_confirmation_data(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {
            "intent": "SETUP",
            "entities": [{"type": "CLIENT", "name": "میثم", "phone": None}],
            "confidence": 0.9,
        },
    )
    project = _create_project(client, "Setup")

    item = natural_input_interpretation(client, project["id"], "کارفرمای پروژه میثم است")
    assert item["canonical_event_type"] == "SETUP_EVENT"
    assert item["semantic_action"] == "SETUP"
    assert item["extracted_entities"][0]["name"] == "میثم"
    assert item["status"] == "PENDING"
