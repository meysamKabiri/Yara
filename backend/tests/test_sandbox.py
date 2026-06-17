import json

from app.api import sandbox


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
