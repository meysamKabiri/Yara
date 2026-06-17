from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.core import Project, ShadowInterpretationLog
from app.services.shadow_conflict_analyzer import analyze_shadow_conflict


def _project(db: Session) -> Project:
    project = Project(name="Analytics")
    db.add(project)
    db.flush()
    return project


def _legacy(
    *,
    intent: str = "FINANCIAL_EVENT",
    entity: str = "میثم",
    amount: str | None = "200000000.00",
    direction: str | None = "OUTGOING",
    quantity: str | None = None,
    unit: str | None = None,
    confidence: float = 0.7,
) -> dict[str, Any]:
    return {
        "canonical_event_type": intent,
        "extracted_entities": [{"name": entity}] if entity else [],
        "extracted_amount": amount,
        "financial_direction": direction,
        "extracted_quantity": quantity,
        "unit": unit,
        "confidence": confidence,
    }


def _shadow(
    *,
    intent: str = "FINANCIAL",
    entity: str = "میثم",
    amount: int | None = 200000000,
    direction: str = "OUT",
    quantity: int | None = None,
    unit: str | None = None,
    confidence: float = 0.7,
) -> dict[str, Any]:
    return {
        "intent": intent,
        "entities": [{"name": entity, "kind": "PERSON"}] if entity else [],
        "financial": {"amount": amount, "direction": direction},
        "work": {"quantity": quantity, "unit": unit},
        "confidence": confidence,
        "ambiguity": False,
        "missing_fields": [],
        "reasoning": "test row",
    }


def _insert_log(
    db: Session,
    project_id: int,
    legacy_json: dict[str, Any],
    shadow_json: dict[str, Any],
    diff_json: dict[str, bool],
    input_text: str = "میثم ۲۰۰ میلیون پول داد",
) -> None:
    db.add(
        ShadowInterpretationLog(
            project_id=project_id,
            input_text=input_text,
            legacy_json=[legacy_json],
            shadow_json=shadow_json,
            diff_json=diff_json,
        )
    )


def _seed(
    client: TestClient,
    rows: list[tuple[dict[str, Any], dict[str, Any], dict[str, bool]]],
) -> int:
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        project = _project(db)
        for legacy_json, shadow_json, diff_json in rows:
            _insert_log(db, project.id, legacy_json, shadow_json, diff_json)
        db.commit()
        return project.id


def test_empty_dataset_returns_zeros_safely(client: TestClient) -> None:
    response = client.get("/shadow/summary")

    assert response.status_code == 200
    assert response.json()["total_samples"] == 0
    assert response.json()["accuracy"] == {
        "intent": 0.0,
        "entity": 0.0,
        "financial": 0.0,
        "work": 0.0,
    }
    assert response.json()["overall_shadow_score"] == 0.0


def test_shadow_summary_computes_correctly(client: TestClient) -> None:
    _seed(
        client,
        [
            (
                _legacy(),
                _shadow(),
                {
                    "intent_match": True,
                    "entity_match": True,
                    "amount_match": True,
                    "direction_match": True,
                },
            ),
            (
                _legacy(entity="علی", confidence=0.9),
                _shadow(entity="میثم", confidence=0.95),
                {
                    "intent_match": True,
                    "entity_match": False,
                    "amount_match": True,
                    "direction_match": True,
                },
            ),
        ],
    )

    response = client.get("/shadow/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["total_samples"] == 2
    assert body["accuracy"] == {
        "intent": 1.0,
        "entity": 0.5,
        "financial": 1.0,
        "work": 1.0,
    }
    assert body["overall_shadow_score"] == 0.85
    assert body["confidence_analysis"] == {
        "high_confidence_wrong_shadow": 1,
        "high_confidence_wrong_legacy": 1,
    }


def test_conflict_detection_works(client: TestClient) -> None:
    _seed(
        client,
        [
            (
                _legacy(entity="علی"),
                _shadow(entity="میثم", confidence=0.9),
                {
                    "intent_match": True,
                    "entity_match": False,
                    "amount_match": True,
                    "direction_match": True,
                },
            )
        ],
    )

    response = client.get("/shadow/conflicts")

    assert response.status_code == 200
    conflicts = response.json()
    assert len(conflicts) == 1
    assert conflicts[0]["input_text"] == "میثم ۲۰۰ میلیون پول داد"
    assert conflicts[0]["conflict_types"] == [
        "ENTITY_MISMATCH",
        "OVERCONFIDENCE_ERROR",
    ]


def test_entity_mismatch_detected_correctly() -> None:
    conflict_types = analyze_shadow_conflict(
        [_legacy(entity="علی")],
        _shadow(entity="میثم"),
        {
            "intent_match": True,
            "entity_match": False,
            "amount_match": True,
            "direction_match": True,
        },
    )

    assert "ENTITY_MISMATCH" in conflict_types
    assert "INTENT_MISMATCH" not in conflict_types


def test_financial_mismatch_detected_correctly() -> None:
    conflict_types = analyze_shadow_conflict(
        [_legacy(amount="200000000.00", direction="OUTGOING")],
        _shadow(amount=100000000, direction="IN"),
        {
            "intent_match": True,
            "entity_match": True,
            "amount_match": False,
            "direction_match": False,
        },
    )

    assert "AMOUNT_ERROR" in conflict_types
    assert "DIRECTION_ERROR" in conflict_types


def test_mixed_dataset_returns_correct_aggregation(client: TestClient) -> None:
    _seed(
        client,
        [
            (
                _legacy(),
                _shadow(),
                {
                    "intent_match": True,
                    "entity_match": True,
                    "amount_match": True,
                    "direction_match": True,
                },
            ),
            (
                _legacy(intent="WORK_EVENT", amount=None, direction=None, quantity="2", unit="day"),
                _shadow(intent="WORK", amount=None, direction="NONE", quantity=2, unit="day"),
                {
                    "intent_match": True,
                    "entity_match": True,
                    "amount_match": True,
                    "direction_match": True,
                },
            ),
            (
                _legacy(entity="", amount=None, direction=None),
                _shadow(entity="میثم", amount=200000000, direction="OUT"),
                {
                    "intent_match": True,
                    "entity_match": False,
                    "amount_match": False,
                    "direction_match": False,
                },
            ),
        ],
    )

    summary = client.get("/shadow/summary").json()
    breakdown = client.get("/shadow/category-breakdown").json()

    assert summary["total_samples"] == 3
    assert summary["accuracy"]["intent"] == 1.0
    assert summary["accuracy"]["entity"] == 2 / 3
    assert summary["accuracy"]["financial"] == 2 / 3
    assert summary["accuracy"]["work"] == 1.0
    assert summary["summary"] == {"legacy_wins": 0, "shadow_wins": 1, "ties": 2}
    assert breakdown["FINANCIAL"] == {
        "shadow_better": 1,
        "legacy_better": 0,
        "ties": 1,
    }
    assert breakdown["WORK"] == {"shadow_better": 0, "legacy_better": 0, "ties": 1}
