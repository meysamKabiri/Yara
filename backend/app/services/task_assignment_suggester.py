from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.role_registry import labels_for_project_role
from app.models.core import ProjectTask, Worker, WorkerType


ROLE_KEYWORDS: dict[str, tuple[WorkerType, ...]] = {
    **{label: (WorkerType.SKILLED_WORKER,) for label in labels_for_project_role("SKILLED_WORKER")},
    **{label: (WorkerType.DAILY_WORKER,) for label in labels_for_project_role("DAILY_WORKER")},
    **{label: (WorkerType.VENDOR,) for label in labels_for_project_role("VENDOR")},
    **{label: (WorkerType.CLIENT,) for label in labels_for_project_role("CLIENT")},
}


def _normalize(text: str | None) -> str:
    value = (text or "").strip().replace("ي", "ی").replace("ك", "ک")
    return " ".join(value.split())


def _person(worker: Worker, confidence: float) -> dict[str, Any]:
    return {
        "id": worker.id,
        "name": worker.name,
        "role": worker.type,
        "role_detail": worker.role_detail,
        "confidence": confidence,
    }


def _candidate_matches_role(worker: Worker, role_text: str, role_types: tuple[WorkerType, ...]) -> bool:
    normalized_detail = _normalize(worker.role_detail)
    normalized_name = _normalize(worker.name)
    if role_text and (role_text in normalized_detail or role_text in normalized_name):
        return True
    return worker.type in role_types


def _recent_confirmed_assignee(db: Session, project_id: int, candidate_ids: set[int]) -> int | None:
    if not candidate_ids:
        return None
    task = db.scalar(
        select(ProjectTask)
        .where(
            ProjectTask.project_id == project_id,
            ProjectTask.assignment_status == "confirmed",
            ProjectTask.assignee_id.in_(candidate_ids),
        )
        .order_by(ProjectTask.updated_at.desc(), ProjectTask.id.desc())
    )
    return task.assignee_id if task else None


def suggest_assignee(
    db: Session,
    *,
    task_input: str,
    project_id: int,
    extracted_actor: str | None = None,
) -> dict[str, Any]:
    text = _normalize(" ".join(part for part in [task_input, extracted_actor] if part))
    if not text:
        return {"suggested_person": None, "source": "none", "candidates": []}

    workers = list(
        db.scalars(
            select(Worker)
            .where(Worker.project_id == project_id)
            .order_by(Worker.created_at.desc(), Worker.id.desc())
        )
    )
    if not workers:
        return {"suggested_person": None, "source": "none", "candidates": []}

    for worker in workers:
        name = _normalize(worker.name)
        if name and name in text:
            person = _person(worker, 0.95)
            return {"suggested_person": person, "source": "name_match", "candidates": [person]}

    matched_role_text = ""
    matched_role_types: tuple[WorkerType, ...] = ()
    for role_text, role_types in ROLE_KEYWORDS.items():
        if role_text in text:
            matched_role_text = role_text
            matched_role_types = role_types
            break

    if not matched_role_types:
        return {"suggested_person": None, "source": "none", "candidates": []}

    candidates = [
        _person(worker, 0.7)
        for worker in workers
        if _candidate_matches_role(worker, matched_role_text, matched_role_types)
    ]
    if not candidates:
        return {"suggested_person": None, "source": "none", "candidates": []}

    if len(candidates) == 1:
        return {"suggested_person": candidates[0], "source": "role_match", "candidates": candidates}

    recent_id = _recent_confirmed_assignee(db, project_id, {int(candidate["id"]) for candidate in candidates})
    if recent_id is not None:
        recent = next((candidate for candidate in candidates if candidate["id"] == recent_id), None)
        if recent:
            return {
                "suggested_person": {**recent, "confidence": 0.75},
                "source": "recent_assignment",
                "candidates": candidates,
            }

    return {"suggested_person": None, "source": "role_match", "candidates": candidates}
