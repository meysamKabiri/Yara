import json

from app.api import sandbox
from dev_tools.sandbox import seed_runner


def test_sandbox_status_not_run(client, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(sandbox, "STATUS_PATH", tmp_path / "missing.json")

    response = client.get("/sandbox/status")

    assert response.status_code == 200
    assert response.json() == {"last_scenario_run": None, "status": "not_run"}


def test_sandbox_status_returns_last_run(client, monkeypatch, tmp_path) -> None:
    status_path = tmp_path / "last_status.json"
    status_path.write_text(
        json.dumps({"scenario": "villa_project_basic", "history_count": 10}),
        encoding="utf-8",
    )
    monkeypatch.setattr(sandbox, "STATUS_PATH", status_path)

    response = client.get("/sandbox/status")

    assert response.status_code == 200
    assert response.json() == {
        "last_scenario_run": "villa_project_basic",
        "status": {"scenario": "villa_project_basic", "history_count": 10},
    }


def test_sandbox_pipeline_confirms_pending_interpretations(client, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(seed_runner, "SessionLocal", client.app.state.testing_session_factory)
    monkeypatch.setattr(seed_runner, "STATUS_PATH", tmp_path / "last_status.json")

    status = seed_runner.run_sandbox_pipeline()

    assert status["history_count"] > 0
    assert status["trace"][0]["detected_intents"] == ["SETUP_EVENT"]
    assert status["trace"][0]["history_entries"]
