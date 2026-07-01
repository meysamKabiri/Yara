from fastapi.testclient import TestClient
from datetime import UTC, datetime, timedelta


def _project(client: TestClient) -> dict:
    response = client.post("/projects", json={"name": "کارهای پروژه"})
    assert response.status_code == 201
    return response.json()


def _worker(client: TestClient, project_id: int, name: str, role_detail: str | None = None) -> dict:
    response = client.post(
        f"/projects/{project_id}/workers",
        json={"name": name, "type": "SKILLED_WORKER", "role_detail": role_detail},
    )
    assert response.status_code == 201
    return response.json()


def test_role_match_suggests_single_candidate(client: TestClient) -> None:
    project = _project(client)
    worker = _worker(client, project["id"], "نادری", "جوشکار")

    response = client.post(
        f"/projects/{project['id']}/tasks/suggest",
        json={"title": "جوشکار بیاد درب را جوش بده"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "role_match"
    assert body["suggested_person"]["id"] == worker["id"]
    assert body["suggested_person"]["name"] == "نادری"


def test_no_match_creates_unassigned_task(client: TestClient) -> None:
    project = _project(client)

    response = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "مش رحیم نخاله ها را جمع کند"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["assignment_suggestion"]["suggested_person"] is None
    assert body["task"]["assignee_id"] is None
    assert body["task"]["assignment_status"] == "unassigned"


def test_toggle_off_does_not_apply_suggestion(client: TestClient) -> None:
    project = _project(client)
    _worker(client, project["id"], "نادری", "جوشکار")

    response = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "جوشکار بیاد درب را جوش بده", "assign_to_person": False},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["assignment_suggestion"]["suggested_person"]["name"] == "نادری"
    assert body["task"]["assignee_id"] is None
    assert body["task"]["assignment_status"] == "suggested"


def test_assignment_requires_explicit_user_confirmation(client: TestClient) -> None:
    project = _project(client)
    worker = _worker(client, project["id"], "نادری", "جوشکار")

    response = client.post(
        f"/projects/{project['id']}/tasks",
        json={
            "title": "جوشکار بیاد درب را جوش بده",
            "assign_to_person": True,
            "assignee_id": worker["id"],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["task"]["assignee_id"] == worker["id"]
    assert body["task"]["assignment_status"] == "confirmed"


def test_multiple_role_candidates_are_not_auto_selected(client: TestClient) -> None:
    project = _project(client)
    _worker(client, project["id"], "نادری", "جوشکار")
    _worker(client, project["id"], "صابری", "جوشکار")

    response = client.post(
        f"/projects/{project['id']}/tasks/suggest",
        json={"title": "جوشکار بیاد درب را جوش بده"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "role_match"
    assert body["suggested_person"] is None
    assert {candidate["name"] for candidate in body["candidates"]} == {"نادری", "صابری"}


def test_task_creation_extracts_due_date_without_affecting_assignment(client: TestClient) -> None:
    project = _project(client)
    _worker(client, project["id"], "نادری", "جوشکار")

    response = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "فردا جوشکار بیاد قوطی ها رو جوش بده", "assign_to_person": False},
    )

    assert response.status_code == 201
    body = response.json()
    expected_tomorrow = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
    assert body["task"]["due_date"] == expected_tomorrow
    assert body["task"]["due_date_confidence"] == 0.95
    assert body["task"]["due_date_source"] == "deterministic"
    assert body["task"]["assignee_id"] is None
    assert body["assignment_suggestion"]["suggested_person"]["name"] == "نادری"


def test_task_creation_without_date_still_succeeds(client: TestClient) -> None:
    project = _project(client)

    response = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "بیاد کار کنه"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["task"]["due_date"] is None
    assert body["task"]["due_date_confidence"] == 0.0
    assert body["task"]["due_date_source"] == "deterministic"


def test_task_creation_accepts_manual_due_date_override(client: TestClient) -> None:
    project = _project(client)

    response = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "فردا بیاد کار کنه", "due_date": "2026-08-10"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["task"]["due_date"] == "2026-08-10"
    assert body["task"]["due_date_confidence"] == 1.0
    assert body["task"]["due_date_source"] == "user_edit"
