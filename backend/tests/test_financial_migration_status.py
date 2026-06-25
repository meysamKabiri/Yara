from typing import Any

from fastapi.testclient import TestClient
from tests.natural_input_helpers import natural_input_interpretation, natural_input_interpretations, submit_natural_input
from sqlalchemy import select

from app.models.core import FinancialMigrationLog, Project


def _create_project(client: TestClient) -> dict[str, Any]:
    response = client.post("/projects", json={"name": "Financial migration"})
    assert response.status_code == 201
    return response.json()


def _legacy_graph() -> dict[str, Any]:
    return {
        "entity": "میثم",
        "entities": [{"type": "CLIENT", "name": "میثم"}],
        "amount_text": "۲۰۰ میلیون",
        "confidence": 0.9,
    }


def _shadow_result() -> dict[str, Any]:
    return {
        "intent": "FINANCIAL",
        "action": "PAYMENT_OUT",
        "entities": [{"name": "میثم", "kind": "PERSON", "project_role": "CLIENT"}],
        "financial": {"amount": 200000000, "direction": "OUT", "payment_method": None, "due_date_text": None},
        "work": {"quantity": None, "unit": None, "description": None},
        "note": {"text": None},
        "confidence": 0.9,
        "ambiguity": False,
        "missing_fields": [],
        "reasoning_summary": "test",
    }


def test_financial_input_logs_migration_decision_in_off_mode(
    client: TestClient,
    monkeypatch,
) -> None:
    project = _create_project(client)
    monkeypatch.setattr("app.api.projects.extract_graph", lambda text: _legacy_graph())
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, raw_text, project_id, db=None: _shadow_result(),
    )

    submit_natural_input(client, project["id"], "میثم ۲۰۰ میلیون پول داد")
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        logs = list(db.scalars(select(FinancialMigrationLog)))
    assert logs == []


def test_financial_migration_status_endpoint(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        project = Project(name="Status")
        db.add(project)
        db.flush()
        db.add_all(
            [
                FinancialMigrationLog(
                    project_id=project.id,
                    input_text="a",
                    legacy_json=[
                        {
                            "canonical_event_type": "FINANCIAL_EVENT",
                            "extracted_entities": [{"name": "میثم"}],
                            "extracted_amount": "1",
                            "financial_direction": "OUTGOING",
                        }
                    ],
                    shadow_json={
                        "intent": "FINANCIAL",
                        "entities": [{"name": "میثم", "kind": "PERSON"}],
                        "financial": {"amount": 1, "direction": "OUT"},
                    },
                    chosen_system="LEGACY",
                    reason="test",
                ),
                FinancialMigrationLog(
                    project_id=project.id,
                    input_text="b",
                    legacy_json=[
                        {
                            "canonical_event_type": "FINANCIAL_EVENT",
                            "extracted_entities": [{"name": "علی"}],
                            "extracted_amount": "1",
                            "financial_direction": "OUTGOING",
                        }
                    ],
                    shadow_json={
                        "intent": "FINANCIAL",
                        "entities": [{"name": "میثم", "kind": "PERSON"}],
                        "financial": {"amount": 1, "direction": "OUT"},
                    },
                    chosen_system="SHADOW",
                    reason="test",
                ),
            ]
        )
        db.commit()

    response = client.get("/shadow/financial-migration-status")

    assert response.status_code == 200
    assert response.json() == {
        "mode": "OFF",
        "usage": {"legacy": 1, "shadow": 1},
        "agreement_rate": 0.5,
        "conflict_rate": 0.5,
    }


def test_llm_authority_status_endpoint(client: TestClient) -> None:
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        project = Project(name="Authority")
        db.add(project)
        db.flush()
        db.add_all(
            [
                FinancialMigrationLog(
                    project_id=project.id,
                    input_text="a",
                    legacy_json=[],
                    shadow_json={},
                    chosen_system="SHADOW",
                    reason="LLM financial safety checks passed",
                ),
                FinancialMigrationLog(
                    project_id=project.id,
                    input_text="b",
                    legacy_json=[],
                    shadow_json={},
                    chosen_system="LEGACY",
                    reason="Safety override: legacy/shadow mismatch",
                ),
            ]
        )
        db.commit()

    response = client.get("/shadow/llm-authority-status")

    assert response.status_code == 200
    assert response.json() == {
        "llm_primary_rate": 0.5,
        "legacy_fallback_rate": 0.5,
        "top_fallback_reasons": ["Safety override: legacy/shadow mismatch"],
        "risk_level": "HIGH",
    }
