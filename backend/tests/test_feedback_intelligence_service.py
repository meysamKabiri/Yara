from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.models.core import InterpretationFeedbackSource
from app.services.feedback_intelligence_service import analyze_feedback_intelligence
from app.services.interpretation_feedback import create_interpretation_feedback


def _project(client: TestClient, name: str) -> dict[str, Any]:
    response = client.post("/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _feedback(
    db,
    *,
    project_id: int,
    raw_input: str,
    system_output: dict[str, Any],
    user_final_state: dict[str, Any],
    trace_id: str,
) -> None:
    create_interpretation_feedback(
        db,
        project_id=project_id,
        trace_id=trace_id,
        raw_input=raw_input,
        system_output=system_output,
        user_final_state=user_final_state,
        correction_source=InterpretationFeedbackSource.USER_EDIT,
    )


def _setup_feedback_dataset(client: TestClient) -> tuple[int, int]:
    project_a = _project(client, "feedback intelligence a")
    project_b = _project(client, "feedback intelligence b")
    with client.app.state.testing_session_factory() as db:
        for index, raw in enumerate(["کارفر مای مش رحیم", "کارفرما مش رحیم", "کار فر ما ی مش رحیم"], start=1):
            _feedback(
                db,
                project_id=project_a["id"],
                trace_id=f"cluster-{index}",
                raw_input=raw,
                system_output={
                    "domain": "NOTE",
                    "entities": [{"name": raw, "project_role": "OTHER"}],
                    "financials": {"amount": None},
                },
                user_final_state={
                    "domain": "SETUP",
                    "entities": [{"name": "مش رحیم", "project_role": "CLIENT"}],
                    "financials": {"amount": None},
                },
            )

        for index in range(3):
            _feedback(
                db,
                project_id=project_a["id"],
                trace_id=f"unknown-role-{index}",
                raw_input=f"اپراتور دستگاه CNC علی رضایی {index}",
                system_output={
                    "domain": "SETUP",
                    "entities": [{"name": f"علی رضایی {index}", "project_role": "OTHER"}],
                    "financials": {"amount": None},
                },
                user_final_state={
                    "domain": "SETUP",
                    "entities": [{"name": f"علی رضایی {index}", "project_role": "SKILLED_WORKER"}],
                    "financials": {"amount": None},
                },
            )

        _feedback(
            db,
            project_id=project_a["id"],
            trace_id="amount-1",
            raw_input="مش رحیم ۱۰۰ پرداخت کرد",
            system_output={
                "domain": "FINANCIAL",
                "entities": [{"name": "مش رحیم", "project_role": "OTHER"}],
                "financials": {"amount": 100},
            },
            user_final_state={
                "domain": "FINANCIAL",
                "entities": [{"name": "مش رحیم", "project_role": "OTHER"}],
                "financials": {"amount": 200},
            },
        )

        _feedback(
            db,
            project_id=project_b["id"],
            trace_id="other-project",
            raw_input="پروژه دیگر",
            system_output={"domain": "NOTE", "entities": [], "financials": {}},
            user_final_state={"domain": "WORK", "entities": [], "financials": {}},
        )
        db.commit()
    return project_a["id"], project_b["id"]


def test_feedback_intelligence_aggregates_error_types(client: TestClient) -> None:
    project_id, _ = _setup_feedback_dataset(client)

    with client.app.state.testing_session_factory() as db:
        analytics = analyze_feedback_intelligence(db, project_id=project_id)

    assert analytics["project_id"] == project_id
    assert analytics["time_window"] == "last_7_days"
    assert analytics["error_distribution"]["WRONG_DOMAIN"] == 3
    assert analytics["error_distribution"]["WRONG_ENTITY"] >= 3
    assert analytics["error_distribution"]["WRONG_ROLE"] >= 3
    assert analytics["error_distribution"]["WRONG_AMOUNT"] == 1
    assert analytics["llm_disagreement_rate"] == 1.0


def test_feedback_intelligence_clusters_similar_corrupted_inputs(client: TestClient) -> None:
    project_id, _ = _setup_feedback_dataset(client)

    with client.app.state.testing_session_factory() as db:
        analytics = analyze_feedback_intelligence(db, project_id=project_id)

    patterns = analytics["top_problem_patterns"]
    assert patterns
    assert any(pattern["frequency"] >= 3 for pattern in patterns)
    assert any(pattern["suggested_fix"] == "add spacing normalization rule" for pattern in patterns)


def test_feedback_intelligence_detects_unknown_role_candidates(client: TestClient) -> None:
    project_id, _ = _setup_feedback_dataset(client)

    with client.app.state.testing_session_factory() as db:
        analytics = analyze_feedback_intelligence(db, project_id=project_id, unknown_role_threshold=2)

    candidates = analytics["unknown_role_candidates"]
    assert candidates
    assert candidates[0]["text"] == "اپراتور دستگاه CNC"
    assert candidates[0]["frequency"] == 3
    assert candidates[0]["suggested_category"] == "SKILLED_WORKER"


def test_feedback_intelligence_empty_dataset(client: TestClient) -> None:
    project = _project(client, "empty feedback intelligence")

    with client.app.state.testing_session_factory() as db:
        analytics = analyze_feedback_intelligence(db, project_id=project["id"])

    assert analytics["error_distribution"] == {
        "WRONG_DOMAIN": 0,
        "WRONG_ENTITY": 0,
        "WRONG_AMOUNT": 0,
        "WRONG_ROLE": 0,
        "MISSING_EXTRACTION": 0,
    }
    assert analytics["top_problem_patterns"] == []
    assert analytics["unknown_role_candidates"] == []
    assert analytics["normalization_failures"] == []
    assert analytics["llm_disagreement_rate"] == 0.0
    assert analytics["system_recommendations"] == []


def test_feedback_intelligence_multi_project_isolation(client: TestClient) -> None:
    project_a, project_b = _setup_feedback_dataset(client)

    with client.app.state.testing_session_factory() as db:
        analytics_a = analyze_feedback_intelligence(db, project_id=project_a)
        analytics_b = analyze_feedback_intelligence(db, project_id=project_b)

    assert analytics_a["error_distribution"]["WRONG_DOMAIN"] == 3
    assert analytics_b["error_distribution"]["WRONG_DOMAIN"] == 1
    assert analytics_b["unknown_role_candidates"] == []


def test_feedback_intelligence_api_returns_structured_json(client: TestClient) -> None:
    project_id, _ = _setup_feedback_dataset(client)

    response = client.get(f"/admin/feedback/intelligence?project_id={project_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == project_id
    assert set(body["error_distribution"]) == {
        "WRONG_DOMAIN",
        "WRONG_ENTITY",
        "WRONG_AMOUNT",
        "WRONG_ROLE",
        "MISSING_EXTRACTION",
    }
    assert isinstance(body["top_problem_patterns"], list)
    assert isinstance(body["unknown_role_candidates"], list)
    assert isinstance(body["normalization_failures"], list)
    assert isinstance(body["llm_disagreement_rate"], float)
    assert isinstance(body["system_recommendations"], list)
