import ast
import inspect
import logging
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.natural_input_helpers import natural_input_interpretation, natural_input_interpretations, submit_natural_input
from sqlalchemy.orm import Session

from app.models.core import (
    FinancialDirection,
    Payment,
    PaymentType,
    Project,
    Worker,
    WorkerState,
    WorkerStateRole,
    WorkerType,
)
from app.services import execution_engine
from app.services.execution_engine import ConfirmedFinancialInterpretation, ExecutionEngine

OBSOLETE_SHADOW_SKIP = pytest.mark.skip(
    reason="obsolete architecture audit: legacy observability/shadow path removed"
)


def test_execution_engine_produces_valid_payment_structure(client: TestClient) -> None:
    db = _session(client)
    try:
        project, worker, state = _project_worker_and_state(db, WorkerType.VENDOR)
        confirmed = ConfirmedFinancialInterpretation(
            project_id=project.id,
            semantic_action="PURCHASE_PAID",
            amount=Decimal("25000000"),
            entity_id=worker.id,
            financial_direction=FinancialDirection.OUTGOING,
            payment_method=PaymentType.CASH,
            description="سیم",
        )

        result = ExecutionEngine().execute_confirmed_interpretation(confirmed, db, state)
    finally:
        db.close()

    assert result["invoices"] == []
    assert result["payments"][0]["entity_id"] == worker.id
    assert result["payments"][0]["amount"] == "25000000.00"
    assert result["payments"][0]["type"] == "CASH"
    assert result["payments"][0]["direction"] == "OUTGOING"


def test_execution_engine_uses_no_llm_or_semantic_parsing_imports() -> None:
    tree = ast.parse(inspect.getsource(execution_engine))
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module)

    forbidden_fragments = {
        "llm",
        "semantic",
        "persian_money_engine",
        "persian_project_payment",
        "persian_role_extractor",
    }
    assert not [
        module
        for module in imported_modules
        if any(fragment in module.lower() for fragment in forbidden_fragments)
    ]
    source = inspect.getsource(execution_engine)
    assert "normalize_text" not in source
    assert "parse_persian_money" not in source
    assert "extract_graph" not in source


def test_execution_engine_same_confirmed_input_is_deterministic(db_session: Session) -> None:
    first = _execute_in_isolated_session(db_session)
    db_session.rollback()
    second = _execute_in_isolated_session(db_session)

    assert _without_ids(first) == _without_ids(second)


@OBSOLETE_SHADOW_SKIP
def test_confirmation_runs_execution_engine_shadow_without_double_writing(
    client: TestClient,
    monkeypatch,
    caplog,
) -> None:
    project = _create_project(client)
    worker = _create_worker(client, project["id"], "هادی پور", "VENDOR")
    monkeypatch.setattr("app.api.projects.USE_EXECUTION_ENGINE", False)
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {"intent": "PAYMENT", "entity": "هادی پور", "confidence": 0.9},
    )

    pending = natural_input_interpretation(client, project["id"], "از هادی پور 25 میلیون سیم خریدم و پرداخت کردم")

    with caplog.at_level(logging.INFO):
        resolution = client.post(
            f"/pending-interpretations/{pending['id']}/confirm",
            json={"selected_person_id": worker["id"]},
        )
        confirmed = client.post(
            f"/pending-interpretations/{pending['id']}/confirm",
            json={"entity_id": resolution.json()["entity_id"], "confirmed": True},
        )

    assert confirmed.status_code == 200
    payments = client.get(f"/projects/{project['id']}/payments").json()
    assert len(payments) == 1
    assert payments[0]["amount"] == "25000000.00"
    assert any(
        record.message == "legacy_execution_shadow_comparison"
        for record in caplog.records
    )


def test_execution_engine_is_primary_when_flag_is_on(
    client: TestClient,
    monkeypatch,
) -> None:
    project = _create_project(client)
    worker = _create_worker(client, project["id"], "هادی پور", "VENDOR")
    monkeypatch.setattr("app.api.projects.USE_EXECUTION_ENGINE", True)
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {"intent": "PAYMENT", "entity": "هادی پور", "confidence": 0.9},
    )
    calls = {"count": 0}
    real_engine = ExecutionEngine

    class SpyExecutionEngine(real_engine):
        def execute_confirmed_interpretation(self, confirmed_interpretation, db, state):
            calls["count"] += 1
            return super().execute_confirmed_interpretation(confirmed_interpretation, db, state)

    monkeypatch.setattr("app.api.projects.ExecutionEngine", SpyExecutionEngine)

    pending = natural_input_interpretation(client, project["id"], "از هادی پور 25 میلیون سیم خریدم و پرداخت کردم")
    resolution = client.post(
        f"/pending-interpretations/{pending['id']}/confirm",
        json={"selected_person_id": worker["id"]},
    )
    confirmed = client.post(
        f"/pending-interpretations/{pending['id']}/confirm",
        json={"entity_id": resolution.json()["entity_id"], "confirmed": True},
    )

    assert confirmed.status_code == 200
    assert calls["count"] == 1
    assert confirmed.json()["payments"][0]["amount"] == "25000000.00"


def test_legacy_primary_fallback_works_when_execution_engine_flag_is_off(
    client: TestClient,
    monkeypatch,
) -> None:
    project = _create_project(client)
    worker = _create_worker(client, project["id"], "هادی پور", "VENDOR")
    monkeypatch.setattr("app.api.projects.USE_EXECUTION_ENGINE", False)
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {"intent": "PAYMENT", "entity": "هادی پور", "confidence": 0.9},
    )

    pending = natural_input_interpretation(client, project["id"], "از هادی پور 25 میلیون سیم خریدم و پرداخت کردم")
    confirmed = client.post(
        f"/pending-interpretations/{pending['id']}/confirm",
        json={"selected_person_id": worker["id"]},
    )

    assert confirmed.status_code == 200
    assert confirmed.json()["payments"][0]["amount"] == "25000000.00"


@OBSOLETE_SHADOW_SKIP
def test_engine_primary_shadow_comparison_reports_matching_financial_output(
    client: TestClient,
    monkeypatch,
    caplog,
) -> None:
    project = _create_project(client)
    worker = _create_worker(client, project["id"], "هادی پور", "VENDOR")
    monkeypatch.setattr("app.api.projects.USE_EXECUTION_ENGINE", False)
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {"intent": "PAYMENT", "entity": "هادی پور", "confidence": 0.9},
    )
    pending = natural_input_interpretation(client, project["id"], "از هادی پور 25 میلیون سیم خریدم و پرداخت کردم")

    with caplog.at_level(logging.INFO):
        resolution = client.post(
            f"/pending-interpretations/{pending['id']}/confirm",
            json={"selected_person_id": worker["id"]},
        )
        confirmed = client.post(
            f"/pending-interpretations/{pending['id']}/confirm",
            json={"entity_id": resolution.json()["entity_id"], "confirmed": True},
        )

    assert confirmed.status_code == 200
    comparison_records = [
        record for record in caplog.records if record.message == "legacy_execution_shadow_comparison"
    ]
    assert comparison_records
    assert comparison_records[0].comparison["matches"] is True


def _execute_in_isolated_session(db: Session) -> dict[str, Any]:
    project, worker, state = _project_worker_and_state(db, WorkerType.CLIENT)
    confirmed = ConfirmedFinancialInterpretation(
        project_id=project.id,
        semantic_action="PAYMENT",
        amount=Decimal("50000000"),
        entity_id=worker.id,
        financial_direction=FinancialDirection.INCOMING,
        payment_method=PaymentType.BANK_TRANSFER,
    )
    return ExecutionEngine().execute_confirmed_interpretation(confirmed, db, state)


def _without_ids(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: [
            {
                field: value
                for field, value in item.items()
                if field not in {"id", "project_id", "entity_id", "vendor_id", "worker_id"}
            }
            for item in value
        ]
        for key, value in result.items()
    }


def _session(client: TestClient) -> Session:
    return client.app.state.testing_session_factory()


def _project_worker_and_state(
    db: Session,
    worker_type: WorkerType,
) -> tuple[Project, Worker, WorkerState]:
    project = Project(name="ویلا")
    db.add(project)
    db.flush()
    worker = Worker(
        project_id=project.id,
        name="هادی پور",
        type=worker_type,
        identity_key=f"hadi-{project.id}-{worker_type.value}",
    )
    db.add(worker)
    db.flush()
    state = WorkerState(
        project_id=project.id,
        worker_id=worker.id,
        name=worker.name,
        role=WorkerStateRole.CLIENT if worker_type == WorkerType.CLIENT else WorkerStateRole.VENDOR,
    )
    db.add(state)
    db.flush()
    return project, worker, state


def _create_project(client: TestClient) -> dict[str, Any]:
    response = client.post("/projects", json={"name": "ویلا"})
    assert response.status_code == 201
    return response.json()


def _create_worker(
    client: TestClient,
    project_id: int,
    name: str,
    worker_type: str,
) -> dict[str, Any]:
    response = client.post(
        f"/projects/{project_id}/workers",
        json={"name": name, "type": worker_type},
    )
    assert response.status_code == 201
    return response.json()
