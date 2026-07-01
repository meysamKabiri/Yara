from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models.core import InterpretationFeedback
from app.services.interpretation_feedback import classify_interpretation_errors


def _project(client: TestClient) -> dict:
    response = client.post("/projects", json={"name": "feedback"})
    assert response.status_code == 201
    return response.json()


def test_domain_correction_detection() -> None:
    errors = classify_interpretation_errors(
        {"domain": "FINANCIAL", "entities": [], "financials": {}},
        {"domain": "WORK", "entities": [], "financials": {}},
    )

    assert errors == ["WRONG_DOMAIN"]


def test_entity_correction_detection() -> None:
    errors = classify_interpretation_errors(
        {"domain": "SETUP", "entities": [{"name": "Ali", "project_role": "VENDOR"}]},
        {"domain": "SETUP", "entities": [{"name": "Reza", "project_role": "VENDOR"}]},
    )

    assert errors == ["WRONG_ENTITY"]


def test_amount_correction_detection() -> None:
    errors = classify_interpretation_errors(
        {"domain": "FINANCIAL", "entities": [], "financials": {"amount": "1000"}},
        {"domain": "FINANCIAL", "entities": [], "financials": {"amount": "2000"}},
    )

    assert errors == ["WRONG_AMOUNT"]


def test_multiple_simultaneous_error_types() -> None:
    errors = classify_interpretation_errors(
        {
            "domain": "FINANCIAL",
            "entities": [{"name": "Ali", "project_role": "CLIENT"}],
            "financials": {"amount": None},
        },
        {
            "domain": "WORK",
            "entities": [{"name": "Reza", "project_role": "VENDOR"}],
            "financials": {"amount": "5000"},
        },
    )

    assert errors == [
        "WRONG_DOMAIN",
        "WRONG_ENTITY",
        "WRONG_AMOUNT",
        "WRONG_ROLE",
        "MISSING_EXTRACTION",
    ]


def test_duplicate_feedback_submissions_are_idempotent(
    client: TestClient,
    db_session,
) -> None:
    project = _project(client)
    payload = {
        "trace_id": "feedback-trace-1",
        "project_id": project["id"],
        "raw_input": "Ali paid 1000",
        "system_output": {
            "domain": "FINANCIAL",
            "entities": [{"name": "Ali", "project_role": "CLIENT"}],
            "financials": {"amount": "1000"},
        },
        "user_final_state": {
            "domain": "FINANCIAL",
            "entities": [{"name": "Ali", "project_role": "CLIENT"}],
            "financials": {"amount": "2000"},
        },
    }

    first = client.post("/feedback/interpretation", json=payload)
    second = client.post("/feedback/interpretation", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["error_types"] == ["WRONG_AMOUNT"]

    records = list(
        db_session.scalars(
            select(InterpretationFeedback).where(
                InterpretationFeedback.project_id == project["id"]
            )
        )
    )
    assert len(records) == 1
