from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.core import Project, ShadowInterpretationLog


def _project(db: Session) -> Project:
    project = Project(name="Migration")
    db.add(project)
    db.flush()
    return project


def _legacy(
    intent: str,
    *,
    entity: str = "میثم",
    amount: str | None = None,
    direction: str | None = None,
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
    intent: str,
    *,
    entity: str = "میثم",
    amount: int | None = None,
    direction: str = "NONE",
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
        "reasoning": "seeded",
    }


def _insert_log(
    db: Session,
    project_id: int,
    legacy_json: dict[str, Any],
    shadow_json: dict[str, Any],
    diff_json: dict[str, bool],
) -> None:
    db.add(
        ShadowInterpretationLog(
            project_id=project_id,
            input_text="seeded input",
            legacy_json=[legacy_json],
            shadow_json=shadow_json,
            diff_json=diff_json,
        )
    )


def _seed(
    client: TestClient,
    rows: list[tuple[dict[str, Any], dict[str, Any], dict[str, bool]]],
) -> None:
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        project = _project(db)
        for legacy_json, shadow_json, diff_json in rows:
            _insert_log(db, project.id, legacy_json, shadow_json, diff_json)
        db.commit()


def _match_diff() -> dict[str, bool]:
    return {
        "intent_match": True,
        "entity_match": True,
        "amount_match": True,
        "direction_match": True,
    }


def test_empty_dataset_returns_safe_defaults(client: TestClient) -> None:
    response = client.get("/shadow/migration-recommendation")

    assert response.status_code == 200
    body = response.json()
    assert body["overall_migration_readiness"] == 0.0
    assert body["final_recommendation"] == "DO_NOT_MIGRATE"
    assert all(not item["ready"] for item in body["recommended_migrations"].values())


def test_financial_safe_migration_detected_correctly(client: TestClient) -> None:
    _seed(
        client,
        [
            (
                _legacy("FINANCIAL_EVENT", amount="200000000.00", direction="OUTGOING"),
                _shadow("FINANCIAL", amount=200000000, direction="OUT"),
                _match_diff(),
            ),
            (
                _legacy("FINANCIAL_EVENT", amount="100000000.00", direction="INCOMING"),
                _shadow("FINANCIAL", amount=100000000, direction="IN"),
                _match_diff(),
            ),
        ],
    )

    body = client.get("/shadow/migration-recommendation").json()

    assert body["recommended_migrations"]["FINANCIAL"]["ready"] is True
    assert body["recommended_migrations"]["WORK"]["ready"] is False
    assert body["recommended_migrations"]["SETUP"]["ready"] is False
    assert body["final_recommendation"] == "MIGRATE_FINANCIAL_ONLY"


def test_unsafe_system_blocks_migration(client: TestClient) -> None:
    _seed(
        client,
        [
            (
                _legacy("FINANCIAL_EVENT", amount="200000000.00", direction="OUTGOING"),
                _shadow("FINANCIAL", amount=100000000, direction="IN"),
                {
                    "intent_match": True,
                    "entity_match": True,
                    "amount_match": False,
                    "direction_match": False,
                },
            )
        ],
    )

    body = client.get("/shadow/migration-recommendation").json()

    assert body["recommended_migrations"]["FINANCIAL"]["ready"] is False
    assert body["final_recommendation"] == "DO_NOT_MIGRATE"


def test_partial_migration_works_correctly(client: TestClient) -> None:
    _seed(
        client,
        [
            (
                _legacy("WORK_EVENT", quantity="2", unit="day"),
                _shadow("WORK", quantity=2, unit="day"),
                _match_diff(),
            ),
            (
                _legacy("SETUP_EVENT"),
                _shadow("SETUP"),
                _match_diff(),
            ),
            (
                _legacy("FINANCIAL_EVENT", amount="200000000.00", direction="OUTGOING"),
                _shadow("FINANCIAL", amount=200000000, direction="IN"),
                {
                    "intent_match": True,
                    "entity_match": True,
                    "amount_match": True,
                    "direction_match": False,
                },
            ),
        ],
    )

    body = client.get("/shadow/migration-recommendation").json()

    assert body["recommended_migrations"]["WORK"]["ready"] is True
    assert body["recommended_migrations"]["SETUP"]["ready"] is True
    assert body["recommended_migrations"]["FINANCIAL"]["ready"] is False
    assert body["final_recommendation"] == "PARTIAL_MIGRATION"


def test_conflict_heavy_system_returns_do_not_migrate(client: TestClient) -> None:
    rows = []
    for _index in range(2):
        rows.append(
            (
                _legacy(
                    "FINANCIAL_EVENT",
                    entity="علی",
                    amount="200000000.00",
                    direction="OUTGOING",
                ),
                _shadow(
                    "FINANCIAL",
                    entity="میثم",
                    amount=100000000,
                    direction="IN",
                    confidence=0.95,
                ),
                {
                    "intent_match": True,
                    "entity_match": False,
                    "amount_match": False,
                    "direction_match": False,
                },
            )
        )
    _seed(client, rows)

    body = client.get("/shadow/migration-recommendation").json()

    assert body["final_recommendation"] == "DO_NOT_MIGRATE"
    assert any(risk["severity"] == "HIGH" for risk in body["risk_areas"])


def test_api_endpoint_returns_structured_response(client: TestClient) -> None:
    _seed(
        client,
        [
            (
                _legacy("SETUP_EVENT"),
                _shadow("SETUP"),
                _match_diff(),
            )
        ],
    )

    response = client.get("/shadow/migration-recommendation")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "overall_migration_readiness",
        "recommended_migrations",
        "risk_areas",
        "shadow_vs_legacy_summary",
        "final_recommendation",
    }
    assert set(body["recommended_migrations"]) == {"FINANCIAL", "WORK", "SETUP"}
