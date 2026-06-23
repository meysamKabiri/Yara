from decimal import Decimal

from fastapi.testclient import TestClient
from tests.natural_input_helpers import natural_input_interpretation, natural_input_interpretations, submit_natural_input

from app.models.core import Payment, Project, Worker, WorkerType
from app.services.entity_resolution_service import EntityResolutionService
from app.services.execution_engine import ConfirmedFinancialInterpretation, ExecutionEngine


def test_create_new_entity_returns_resolved_entity_id(client: TestClient) -> None:
    db = client.app.state.testing_session_factory()
    try:
        project = _project(db)
        result = EntityResolutionService(db, project.id).resolve(
            name="جعفری",
            role="VENDOR",
            create_new=True,
        )

        assert result == {
            "entity_id": result["entity_id"],
            "is_new": True,
            "name": "جعفری",
            "role": "VENDOR",
            "status": "RESOLVED",
        }
        assert db.get(Worker, result["entity_id"]).name == "جعفری"
    finally:
        db.close()


def test_existing_entity_resolves_by_name(client: TestClient) -> None:
    db = client.app.state.testing_session_factory()
    try:
        project = _project(db)
        worker = Worker(project_id=project.id, name="علی", type=WorkerType.CLIENT)
        db.add(worker)
        db.flush()

        result = EntityResolutionService(db, project.id).resolve(name="علی", role="CLIENT")

        assert result["entity_id"] == worker.id
        assert result["is_new"] is False
        assert result["role"] == "CLIENT"
    finally:
        db.close()


def test_financial_execution_blocked_if_entity_id_missing(client: TestClient) -> None:
    db = client.app.state.testing_session_factory()
    try:
        project = _project(db)
        confirmed = ConfirmedFinancialInterpretation(
            project_id=project.id,
            semantic_action="PAYMENT",
            amount=Decimal("50000000"),
            entity_id=None,
            financial_direction="INCOMING",
            payment_method="BANK_TRANSFER",
        )

        try:
            ExecutionEngine().execute_confirmed_interpretation(confirmed, db, None)
        except ValueError as exc:
            assert str(exc) == "Entity must be resolved before execution"
        else:
            raise AssertionError("ExecutionEngine accepted unresolved entity")
    finally:
        db.close()


def test_financial_execution_succeeds_with_valid_entity_id(client: TestClient) -> None:
    db = client.app.state.testing_session_factory()
    try:
        project = _project(db)
        worker = Worker(project_id=project.id, name="علی", type=WorkerType.CLIENT)
        db.add(worker)
        db.flush()
        confirmed = ConfirmedFinancialInterpretation(
            project_id=project.id,
            semantic_action="PAYMENT",
            amount=Decimal("50000000"),
            entity_id=worker.id,
            financial_direction="INCOMING",
            payment_method="BANK_TRANSFER",
        )

        result = ExecutionEngine().execute_confirmed_interpretation(confirmed, db, None)

        assert result["payments"][0]["entity_id"] == worker.id
        assert result["payments"][0]["direction"] == "INCOMING"
    finally:
        db.close()


def test_create_new_financial_confirm_resolves_only_without_payment(
    client: TestClient,
    monkeypatch,
) -> None:
    project = _create_project(client)
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {"intent": "PAYMENT", "entities": [], "confidence": 0.9},
    )
    pending = natural_input_interpretation(client, project["id"], "از جعفری 25 میلیون سیم خریدم و پرداخت کردم")

    resolution = client.post(
        f"/pending-interpretations/{pending['id']}/confirm",
        json={"create_new": True, "name": "جعفری", "role": "VENDOR"},
    )

    assert resolution.status_code == 200
    body = resolution.json()
    assert body["status"] == "ENTITY_RESOLVED"
    assert body["entity_id"]
    assert client.get(f"/projects/{project['id']}/payments").json() == []

    executed = client.post(
        f"/pending-interpretations/{pending['id']}/confirm",
        json={"entity_id": body["entity_id"], "confirmed": True},
    )

    assert executed.status_code == 200
    assert executed.json()["payments"][0]["entity_id"] == body["entity_id"]


def _project(db):
    project = Project(name="ویلا")
    db.add(project)
    db.flush()
    return project


def _create_project(client: TestClient) -> dict:
    response = client.post("/projects", json={"name": "ویلا"})
    assert response.status_code == 201
    return response.json()
