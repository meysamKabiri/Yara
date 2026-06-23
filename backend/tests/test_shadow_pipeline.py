from typing import Any

from fastapi.testclient import TestClient
from tests.natural_input_helpers import natural_input_interpretation, natural_input_interpretations, submit_natural_input
from sqlalchemy import func, select

from app.models.core import Payment, ShadowInterpretationLog, Worker, WorkLog
from app.services.compare_legacy_vs_shadow import compare_legacy_vs_shadow


def _create_project(client: TestClient) -> dict[str, Any]:
    response = client.post("/projects", json={"name": "Shadow project"})
    assert response.status_code == 201
    return response.json()


def _shadow_result() -> dict[str, Any]:
    return {
        "intent": "FINANCIAL",
        "entities": [{"name": "میثم", "kind": "PERSON"}],
        "financial": {"amount": 200000000, "direction": "OUT"},
        "work": {"quantity": None, "unit": None},
        "confidence": 0.91,
        "ambiguity": False,
        "missing_fields": [],
        "reasoning": "The note says Meysam gave money.",
    }


def _legacy_graph() -> dict[str, Any]:
    return {
        "raw_intent": None,
        "entity": "میثم",
        "entities": [{"type": "CLIENT", "name": "میثم"}],
        "amount_text": "۲۰۰ میلیون",
        "raw_context": "میثم ۲۰۰ میلیون پول داد",
        "confidence": 0.88,
    }


def _shadow_logs(client: TestClient) -> list[ShadowInterpretationLog]:
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        return list(
            db.scalars(select(ShadowInterpretationLog).order_by(ShadowInterpretationLog.id))
        )


def test_diff_is_computed_correctly() -> None:
    diff = compare_legacy_vs_shadow(
        [
            {
                "canonical_event_type": "FINANCIAL_EVENT",
                "extracted_entities": [{"name": "میثم"}],
                "extracted_amount": "200000000.00",
                "financial_direction": "OUTGOING",
            }
        ],
        _shadow_result(),
    )

    assert diff == {
        "intent_match": True,
        "entity_match": True,
        "amount_match": True,
        "direction_match": True,
    }


def test_shadow_runs_alongside_legacy_and_creates_log(
    client: TestClient,
    monkeypatch,
) -> None:
    project = _create_project(client)
    calls: list[tuple[str, int]] = []

    monkeypatch.setattr("app.api.projects.extract_graph", lambda text: _legacy_graph())

    def fake_interpret(self, raw_text: str, project_id: int) -> dict[str, Any]:
        calls.append((raw_text, project_id))
        return _shadow_result()

    monkeypatch.setattr("app.api.projects.LLMv2Interpreter.interpret", fake_interpret)

    interpretation = natural_input_interpretation(client, project["id"], "میثم ۲۰۰ میلیون پول داد")
    assert interpretation["canonical_event_type"] == "FINANCIAL_EVENT"
    assert calls == [("میثم ۲۰۰ میلیون پول داد", project["id"])]

    logs = _shadow_logs(client)
    assert len(logs) == 1
    assert logs[0].project_id == project["id"]
    assert logs[0].input_text == "میثم ۲۰۰ میلیون پول داد"
    assert logs[0].shadow_json["intent"] == "FINANCIAL"
    assert logs[0].diff_json["intent_match"] is True


def test_shadow_does_not_execute_or_modify_domain_state(
    client: TestClient,
    monkeypatch,
) -> None:
    project = _create_project(client)
    monkeypatch.setattr("app.api.projects.extract_graph", lambda text: _legacy_graph())
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, raw_text, project_id: _shadow_result(),
    )

    submit_natural_input(client, project["id"], "میثم ۲۰۰ میلیون پول داد")
    session_factory = client.app.state.testing_session_factory
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Worker)) == 0
        assert db.scalar(select(func.count()).select_from(WorkLog)) == 0
        assert db.scalar(select(func.count()).select_from(Payment)) == 0
        assert db.scalar(select(func.count()).select_from(ShadowInterpretationLog)) == 1


def test_shadow_failure_does_not_change_legacy_response(
    client: TestClient,
    monkeypatch,
) -> None:
    project = _create_project(client)
    monkeypatch.setattr("app.api.projects.extract_graph", lambda text: _legacy_graph())

    def fail_interpret(self, raw_text: str, project_id: int) -> dict[str, Any]:
        raise RuntimeError("shadow failed")

    monkeypatch.setattr("app.api.projects.LLMv2Interpreter.interpret", fail_interpret)

    interpretation = natural_input_interpretation(client, project["id"], "میثم ۲۰۰ میلیون پول داد")
    assert interpretation["canonical_event_type"] == "FINANCIAL_EVENT"
    assert interpretation["extracted_amount"] == "200000000.00"
    assert _shadow_logs(client) == []


def test_financial_input_produces_valid_legacy_and_shadow_outputs(
    client: TestClient,
    monkeypatch,
) -> None:
    project = _create_project(client)
    monkeypatch.setattr("app.api.projects.extract_graph", lambda text: _legacy_graph())
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, raw_text, project_id: _shadow_result(),
    )

    legacy = natural_input_interpretation(client, project["id"], "میثم ۲۰۰ میلیون پول داد")
    shadow = _shadow_logs(client)[0].shadow_json
    assert legacy["canonical_event_type"] == "FINANCIAL_EVENT"
    assert legacy["extracted_amount"] == "200000000.00"
    assert shadow["intent"] == "FINANCIAL"
    assert shadow["financial"]["amount"] == 200000000
