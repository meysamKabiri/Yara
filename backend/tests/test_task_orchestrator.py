from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.services.task_orchestrator import TaskOrchestrator

BASE_DATE = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)


class _RouteStub:
    def route(self, _text: str) -> dict:
        return {"domain": "TASK", "confidence": 0.95}


class _AssignmentStub:
    def suggest(self, _text: str, _project_context: dict) -> dict:
        return {
            "suggested_person": {"id": 1, "name": "مش رحیم", "confidence": 1.0},
            "source": "name_match",
            "candidates": [],
        }


class _LlmDateStub:
    def interpret(self, _text: str) -> dict:
        return {"due_date": {"value": "2099-01-01", "confidence": 1.0}}


class _LlmTodaySignalStub:
    def interpret(self, _text: str) -> dict:
        return {
            "due_date": {"value": None, "confidence": 0.0},
            "semantic_explanation": {"matched_signals": ["امروز"]},
        }


def _project(client: TestClient) -> dict:
    response = client.post("/projects", json={"name": "هماهنگی کارها"})
    assert response.status_code == 201
    return response.json()


def _worker(
    client: TestClient,
    project_id: int,
    name: str,
    role_detail: str | None = None,
) -> dict:
    response = client.post(
        f"/projects/{project_id}/workers",
        json={"name": name, "type": "SKILLED_WORKER", "role_detail": role_detail},
    )
    assert response.status_code == 201
    return response.json()


def test_orchestrator_builds_today_task_with_exact_assignee(client: TestClient) -> None:
    project = _project(client)
    worker = _worker(client, project["id"], "مش رحیم")

    response = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "امروز مش رحیم بیاد نخاله ها رو جمع کنه"},
    )

    assert response.status_code == 201
    body = response.json()
    final_task = body["final_task_object"]
    expected_today = datetime.now(UTC).date().isoformat()

    assert body["task_id"] == body["task"]["id"]
    assert body["interpretations"] == []
    assert body["interpretations_deprecated"] is True
    assert final_task["domain"] == "TASK"
    assert final_task["ui_mode"] == "TaskDashboard"
    assert final_task["due_date"] == expected_today
    assert final_task["due_date_source"] == "deterministic"
    assert final_task["assignee"]["id"] == worker["id"]
    assert final_task["assignee"]["name"] == "مش رحیم"
    assert final_task["assignee"]["source"] == "exact_match"
    assert body["task"]["assignee_id"] is None
    assert body["task"]["assignment_status"] == "suggested"


def test_task_endpoint_creates_physical_task_input(client: TestClient) -> None:
    project = _project(client)

    response = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "امروز مش رحیم بیاد نخاله ها رو جمع کنه"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["final_task_object"]["domain"] == "TASK"
    assert body["task"]["project_id"] == project["id"]


def test_task_endpoint_rejects_setup_like_input_without_creating_task(client: TestClient) -> None:
    project = _project(client)

    response = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "کاظمی نقاش به پروژه اضافه شد"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "detected_domain": "SETUP",
        "message": "Only TASK domain inputs can be created through the task endpoint.",
    }
    assert client.get(f"/projects/{project['id']}/tasks").json() == []


def test_task_endpoint_rejects_financial_input_without_creating_task(
    client: TestClient,
) -> None:
    project = _project(client)

    response = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "از علی 50 میلیون گرفتم بابت پروژه"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "detected_domain": "FINANCIAL",
        "message": "Only TASK domain inputs can be created through the task endpoint.",
    }
    assert client.get(f"/projects/{project['id']}/tasks").json() == []


def test_task_endpoint_rejects_note_input_without_creating_task(client: TestClient) -> None:
    project = _project(client)

    response = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "این فقط یک یادداشت مبهم است"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "detected_domain": "NOTE",
        "message": "Only TASK domain inputs can be created through the task endpoint.",
    }
    assert client.get(f"/projects/{project['id']}/tasks").json() == []


def test_orchestrator_maps_normalized_date_today_into_final_task_due_date() -> None:
    class TimeStub:
        def extract_due_date(self, _text: str, _base_date: datetime) -> dict:
            return {"normalized_date": "today", "confidence": 0.95, "source": "deterministic_rule"}

    final_task = TaskOrchestrator(
        time_service=TimeStub(),
        assignment_service=_AssignmentStub(),
        domain_router=_RouteStub(),
    ).build_task(
        "امروز مش رحیم بیاد نخاله ها را جمع کنه",
        {"base_date": BASE_DATE},
    )

    assert final_task["due_date"]["value"] == "2026-07-01"
    assert final_task["due_date"]["source"] == "deterministic"


def test_orchestrator_maps_extracted_time_tomorrow_into_final_task_due_date() -> None:
    class TimeStub:
        def extract_due_date(self, _text: str, _base_date: datetime) -> dict:
            return {"extracted_time": "فردا", "confidence": 0.95, "source": "deterministic_rule"}

    final_task = TaskOrchestrator(
        time_service=TimeStub(),
        assignment_service=_AssignmentStub(),
        domain_router=_RouteStub(),
    ).build_task(
        "فردا مش رحیم بیاد نخاله ها را جمع کنه",
        {"base_date": BASE_DATE},
    )

    assert final_task["due_date"]["value"] == "2026-07-02"
    assert final_task["due_date"]["source"] == "deterministic"


def test_orchestrator_does_not_let_llm_override_extracted_time_due_date() -> None:
    class TimeStub:
        def extract_due_date(self, _text: str, _base_date: datetime) -> dict:
            return {"extracted_time": "امروز", "confidence": 0.3, "source": "deterministic_rule"}

    final_task = TaskOrchestrator(
        time_service=TimeStub(),
        assignment_service=_AssignmentStub(),
        domain_router=_RouteStub(),
        llm_interpreter=_LlmDateStub(),
    ).build_task(
        "امروز مش رحیم بیاد نخاله ها را جمع کنه",
        {"base_date": BASE_DATE},
    )

    assert final_task["due_date"]["value"] == "2026-07-01"
    assert final_task["due_date"]["source"] == "deterministic"


def test_orchestrator_final_mapping_forces_today_from_matched_signals() -> None:
    class TimeStub:
        def extract_due_date(self, _text: str, _base_date: datetime) -> dict:
            return {"due_date": None, "confidence": 0.0, "source": "deterministic_rule"}

    final_task = TaskOrchestrator(
        time_service=TimeStub(),
        assignment_service=_AssignmentStub(),
        domain_router=_RouteStub(),
        llm_interpreter=_LlmTodaySignalStub(),
    ).build_task(
        "امروز مش رحیم بیاد نخاله ها را جمع کنه",
        {"base_date": BASE_DATE},
    )

    assert final_task["due_date"]["value"] == "2026-07-01"
    assert final_task["due_date"]["source"] == "deterministic"
    assert final_task["due_date"]["confidence"] == 0.95


def test_orchestrator_builds_tomorrow_task_with_role_match(client: TestClient) -> None:
    project = _project(client)
    worker = _worker(client, project["id"], "نادری", "جوشکار")

    response = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "فردا جوشکار بیاد کار کنه"},
    )

    assert response.status_code == 201
    body = response.json()
    final_task = body["final_task_object"]
    expected_tomorrow = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()

    assert final_task["domain"] == "TASK"
    assert final_task["due_date"] == expected_tomorrow
    assert final_task["assignee"]["id"] == worker["id"]
    assert final_task["assignee"]["name"] == "نادری"
    assert final_task["assignee"]["source"] == "role_match"
    assert body["task"]["assignee_id"] is None
    assert body["task"]["assignment_status"] == "suggested"


def test_orchestrator_marks_unclear_task_for_confirmation(client: TestClient) -> None:
    project = _project(client)

    response = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "هیچی مشخص نیست فقط گفته بیاد کمک کنه"},
    )

    assert response.status_code == 201
    body = response.json()
    final_task = body["final_task_object"]

    assert final_task["domain"] == "TASK"
    assert final_task["assignee"]["id"] is None
    assert final_task["confidence"] < 0.7
    assert final_task["flags"]["needs_user_confirmation"] is True
    assert body["task"]["assignment_status"] == "unassigned"


def test_task_create_debug_includes_deprecated_legacy_interpretations(client: TestClient) -> None:
    project = _project(client)

    response = client.post(
        f"/projects/{project['id']}/tasks?debug=true",
        json={"title": "فردا بیاد کار کنه"},
    )

    assert response.status_code == 201
    body = response.json()

    assert body["final_task_object"]["domain"] == "TASK"
    assert body["task_id"] == body["task"]["id"]
    assert body["interpretations_deprecated"] is True
    assert len(body["interpretations"]) == 1
    assert body["interpretations"][0]["deprecated"] is True
    assert body["interpretations"][0]["source"] == "legacy_task_response"


def test_created_task_is_persisted_with_final_task_object(client: TestClient) -> None:
    project = _project(client)

    create_response = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "فردا بیاد کار کنه"},
    )
    assert create_response.status_code == 201
    created = create_response.json()

    list_response = client.get(f"/projects/{project['id']}/tasks")
    assert list_response.status_code == 200
    tasks = list_response.json()

    saved = next(task for task in tasks if task["id"] == created["task_id"])
    assert saved["status"] == "PENDING"
    assert saved["confidence"] == created["final_task_object"]["confidence"]
    assert saved["description"] == created["final_task_object"]["description"]
    assert saved["final_task_object"]["domain"] == "TASK"
    assert saved["final_task_object"]["due_date"] == created["final_task_object"]["due_date"]


def test_task_update_marks_task_completed(client: TestClient) -> None:
    project = _project(client)
    create_response = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "فردا بیاد کار کنه"},
    )
    assert create_response.status_code == 201
    task_id = create_response.json()["task_id"]

    response = client.patch(f"/tasks/{task_id}", json={"status": "COMPLETED"})

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == task_id
    assert body["status"] == "COMPLETED"
    assert body["updated"] is True
    assert body["final_task_object"]["flags"]["needs_user_confirmation"] is False


def test_task_update_changes_assignee_and_due_date(client: TestClient) -> None:
    project = _project(client)
    worker = _worker(client, project["id"], "مش رحیم")
    create_response = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "فردا بیاد کار کنه"},
    )
    assert create_response.status_code == 201
    task_id = create_response.json()["task_id"]

    response = client.patch(
        f"/tasks/{task_id}",
        json={"assignee_id": worker["id"], "due_date": "2026-08-10"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["assignee_id"] == worker["id"]
    assert body["due_date"] == "2026-08-10"
    assert body["final_task_object"]["assignee"]["name"] == "مش رحیم"
    assert body["final_task_object"]["due_date"] == "2026-08-10"


def test_task_update_rejects_invalid_status(client: TestClient) -> None:
    project = _project(client)
    create_response = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "فردا بیاد کار کنه"},
    )
    assert create_response.status_code == 201

    response = client.patch(
        f"/tasks/{create_response.json()['task_id']}",
        json={"status": "CONFIRMED"},
    )

    assert response.status_code == 400


def test_task_update_rejects_invalid_due_date(client: TestClient) -> None:
    project = _project(client)
    create_response = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "فردا بیاد کار کنه"},
    )
    assert create_response.status_code == 201

    response = client.patch(
        f"/tasks/{create_response.json()['task_id']}",
        json={"due_date": "not-a-date"},
    )

    assert response.status_code == 400


def test_task_update_returns_404_for_missing_task(client: TestClient) -> None:
    response = client.patch("/tasks/999999", json={"status": "COMPLETED"})

    assert response.status_code == 404
