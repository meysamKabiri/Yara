from time import perf_counter
from typing import Any

from fastapi.testclient import TestClient
from tests.natural_input_helpers import natural_input_interpretation, natural_input_interpretations, submit_natural_input

from app.core.observability.performance_logger import latest_performance_events


def _create_project(client: TestClient) -> dict[str, Any]:
    response = client.post("/projects", json={"name": "Performance"})
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
        "entities": [{"name": "میثم", "kind": "PERSON"}],
        "financial": {"amount": 200000000, "direction": "OUT"},
        "work": {"quantity": None, "unit": None},
        "confidence": 0.9,
        "ambiguity": False,
        "missing_fields": [],
        "reasoning": "test",
    }


def test_shadow_interpreter_executes_once_per_financial_request(
    client: TestClient,
    monkeypatch,
) -> None:
    project = _create_project(client)
    calls = 0
    monkeypatch.setattr("app.api.projects.extract_graph", lambda text: _legacy_graph())

    def fake_interpret(self, raw_text: str, project_id: int) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return _shadow_result()

    monkeypatch.setattr("app.api.projects.LLMv2Interpreter.interpret", fake_interpret)

    submit_natural_input(client, project["id"], "میثم ۲۰۰ میلیون پول داد")
    assert calls == 1


def test_governance_evaluates_once_per_financial_request(
    client: TestClient,
    monkeypatch,
) -> None:
    project = _create_project(client)
    calls = 0
    monkeypatch.setattr("app.api.projects.extract_graph", lambda text: _legacy_graph())
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, raw_text, project_id: _shadow_result(),
    )
    original = (
        "app.core.governance.unified_governance_engine.UnifiedGovernanceEngine.evaluate"
    )

    from app.core.governance.unified_governance_engine import UnifiedGovernanceEngine

    original_evaluate = UnifiedGovernanceEngine.evaluate

    def counting_evaluate(self, context: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return original_evaluate(self, context)

    monkeypatch.setattr(original, counting_evaluate)

    submit_natural_input(client, project["id"], "میثم ۲۰۰ میلیون پول داد")
    assert calls == 1


def test_performance_metrics_are_recorded(client: TestClient, monkeypatch) -> None:
    project = _create_project(client)
    before = len(latest_performance_events())
    monkeypatch.setattr("app.api.projects.extract_graph", lambda text: _legacy_graph())
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, raw_text, project_id: _shadow_result(),
    )

    submit_natural_input(client, project["id"], "میثم ۲۰۰ میلیون پول داد")
    events = latest_performance_events()
    assert len(events) == before + 1
    assert events[-1]["legacy_duration_ms"] >= 0
    assert events[-1]["llm_latency_ms"] >= 0
    assert events[-1]["governance_evaluation_time_ms"] >= 0


def test_mocked_latency_remains_stable(client: TestClient, monkeypatch) -> None:
    project = _create_project(client)
    monkeypatch.setattr("app.api.projects.extract_graph", lambda text: _legacy_graph())
    monkeypatch.setattr(
        "app.api.projects.LLMv2Interpreter.interpret",
        lambda self, raw_text, project_id: _shadow_result(),
    )

    start = perf_counter()
    submit_natural_input(client, project["id"], "میثم ۲۰۰ میلیون پول داد")
    duration_ms = (perf_counter() - start) * 1000

    assert duration_ms < 500


def test_role_only_setup_bypasses_slow_llm(client: TestClient, monkeypatch) -> None:
    project = _create_project(client)

    def slow_interpret(self, raw_text: str, project_id: int) -> dict[str, Any]:
        raise AssertionError("role-only setup should not call LLM")

    monkeypatch.setattr("app.api.projects.LLMv2Interpreter.interpret", slow_interpret)

    start = perf_counter()
    interpretation = natural_input_interpretation(
        client,
        project["id"],
        "میثم کبیری کارفرمای پروژه است",
    )
    duration_ms = (perf_counter() - start) * 1000

    assert interpretation["canonical_event_type"] == "SETUP_EVENT"
    assert interpretation["semantic_action"] == "SET_ROLE"
    assert interpretation["structured_interpretation"]["intent"] == "SET_ROLE"
    assert duration_ms < 500
