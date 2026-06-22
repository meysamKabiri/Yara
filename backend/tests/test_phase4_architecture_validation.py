import ast
from pathlib import Path

from fastapi.testclient import TestClient

from app.models.core import Payment, PendingInterpretation, Worker
from app.services.execution_engine import ExecutionEngine

ROOT = Path(__file__).resolve().parents[1]
PROJECTS_API = ROOT / "app" / "api" / "projects.py"
SEMANTIC_ENGINE = ROOT / "app" / "core" / "semantic_rules" / "semantic_rule_engine.py"
PERSIAN_PAYMENT = ROOT / "app" / "services" / "persian_project_payment.py"
FRONTEND_APP = ROOT.parent / "frontend" / "src" / "App.tsx"
FRONTEND_FINANCIAL_MODAL = ROOT.parent / "frontend" / "src" / "ui" / "financial" / "FinancialModal.tsx"


def test_semantic_and_persian_hint_layers_do_not_import_financial_write_models() -> None:
    forbidden = {"Payment", "Invoice", "WorkerState", "PaymentType", "FinancialDirection"}
    for path in [SEMANTIC_ENGINE, PERSIAN_PAYMENT]:
        tree = ast.parse(path.read_text())
        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                imported_names.update(alias.name for alias in node.names)
        assert forbidden.isdisjoint(imported_names)


def test_semantic_financial_actions_are_marked_deprecated_hints() -> None:
    source = SEMANTIC_ENGINE.read_text()
    assert "deprecated_scope" in source
    assert "_deprecated_financial_action_hint" in source
    assert "ExecutionEngine owns final financial effects" in source


def test_frontend_does_not_infer_financial_direction_from_worker_role() -> None:
    source = FRONTEND_FINANCIAL_MODAL.read_text()
    assert "useState(interpretation.financial_direction" in source
    direction_handler = source.split("setDirection", 1)[1]
    assert "resolvedWorker" not in direction_handler
    assert "preferredEntityType" not in direction_handler
    assert "worker.type" not in direction_handler


def test_default_financial_confirmation_uses_execution_engine_only(
    client: TestClient,
    monkeypatch,
) -> None:
    project = _create_project(client)
    worker = _create_worker(client, project["id"], "هادی پور", "VENDOR")
    monkeypatch.setattr("app.api.projects.USE_EXECUTION_ENGINE", True)
    calls = {"engine": 0, "legacy": 0}
    real_execute = ExecutionEngine.execute_confirmed_interpretation

    def spy_engine(self, confirmed_interpretation, db, state):
        calls["engine"] += 1
        return real_execute(self, confirmed_interpretation, db, state)

    def spy_legacy(*args, **kwargs):
        calls["legacy"] += 1
        return original_legacy(*args, **kwargs)

    original_legacy = __import__(
        "app.api.projects",
        fromlist=["_execute_legacy_interpretation"],
    )._execute_legacy_interpretation
    monkeypatch.setattr("app.api.projects.ExecutionEngine.execute_confirmed_interpretation", spy_engine)
    monkeypatch.setattr("app.api.projects._execute_legacy_interpretation", spy_legacy)
    monkeypatch.setattr(
        "app.api.projects.extract_graph",
        lambda text: {"intent": "PAYMENT", "entity": "هادی پور", "confidence": 0.9},
    )

    pending = client.post(
        f"/projects/{project['id']}/natural-input",
        json={"text": "از هادی پور 25 میلیون سیم خریدم و پرداخت کردم"},
    ).json()["interpretations"][0]
    resolution = client.post(
        f"/pending-interpretations/{pending['id']}/confirm",
        json={"selected_person_id": worker["id"]},
    )
    response = client.post(
        f"/pending-interpretations/{pending['id']}/confirm",
        json={"entity_id": resolution.json()["entity_id"], "confirmed": True},
    )

    assert response.status_code == 200
    assert calls["engine"] == 1
    assert calls["legacy"] == 1
    assert client.get(f"/projects/{project['id']}/payments").json()[0]["amount"] == "25000000.00"


def test_only_confirmed_interpretation_reaches_execution_layer(client: TestClient) -> None:
    db = client.app.state.testing_session_factory()
    try:
        project = _project(db)
        worker = Worker(project_id=project.id, name="هادی پور", type="VENDOR")
        db.add(worker)
        db.flush()
        pending = PendingInterpretation(
            project_id=project.id,
            raw_input_text="از هادی پور 25 میلیون سیم خریدم",
            canonical_event_type="FINANCIAL_EVENT",
            semantic_action="PURCHASE_PAID",
            suggested_entity_id=worker.id,
            extracted_entities=[{"name": "هادی پور", "type": "VENDOR", "project_role": "VENDOR"}],
            extracted_amount="25000000",
            payment_method="CASH",
            financial_direction="OUTGOING",
            description="از هادی پور 25 میلیون سیم خریدم",
        )
        db.add(pending)
        db.flush()
        assert db.query(Payment).count() == 0
    finally:
        db.close()


def _project(db):
    from app.models.core import Project

    project = Project(name="ویلا")
    db.add(project)
    db.flush()
    return project


def _create_project(client: TestClient) -> dict:
    response = client.post("/projects", json={"name": "ویلا"})
    assert response.status_code == 201
    return response.json()


def _create_worker(client: TestClient, project_id: int, name: str, worker_type: str) -> dict:
    response = client.post(
        f"/projects/{project_id}/workers",
        json={"name": name, "type": worker_type},
    )
    assert response.status_code == 201
    return response.json()
