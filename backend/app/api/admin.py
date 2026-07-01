from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.core.auth import authenticated_user_id, get_current_user
from app.dependencies.database import DbSession
from app.models.core import DeadLetterJob, Project
from app.services.feedback_intelligence_service import analyze_feedback_intelligence
from app.services.financial_reconciliation_service import (
    latest_reconciliation_report,
    reconcile_project,
    recover_stuck_confirming_interpretations,
    safety_metrics,
)


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(get_current_user)])


@router.get("/dlq-jobs")
def list_dlq_jobs(db: DbSession) -> list[dict[str, Any]]:
    owned_project_ids = _owned_project_ids(db)
    jobs = db.scalars(
        select(DeadLetterJob)
        .where(DeadLetterJob.project_id.in_(owned_project_ids))
        .order_by(DeadLetterJob.created_at.desc(), DeadLetterJob.id.desc())
    )
    return [
        {
            "id": job.id,
            "job_id": job.job_id,
            "project_id": job.project_id,
            "payload": job.payload,
            "error_trace": job.error_trace,
            "retry_count": job.retry_count,
            "source": job.source,
            "created_at": job.created_at.isoformat(),
        }
        for job in jobs
    ]


@router.get("/reconciliation-report/{project_id}")
def reconciliation_report(project_id: int, db: DbSession) -> dict[str, Any]:
    _require_owned_project(db, project_id)
    try:
        return latest_reconciliation_report(db, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/reconciliation-report/{project_id}/run")
def run_reconciliation(project_id: int, db: DbSession) -> dict[str, Any]:
    _require_owned_project(db, project_id)
    try:
        return reconcile_project(db, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/recover-confirming")
def recover_confirming(db: DbSession, max_age_minutes: int = 15) -> dict[str, int]:
    recovered = recover_stuck_confirming_interpretations(
        db,
        max_age_minutes=max_age_minutes,
        project_ids=_owned_project_ids(db),
    )
    return {"recovered": recovered}


@router.get("/safety-metrics")
def read_safety_metrics(db: DbSession) -> dict[str, int]:
    return safety_metrics(db, project_ids=_owned_project_ids(db))


@router.get("/feedback/intelligence")
def feedback_intelligence(
    project_id: int,
    db: DbSession,
    days: int = 7,
) -> dict[str, Any]:
    _require_owned_project(db, project_id)
    return analyze_feedback_intelligence(db, project_id=project_id, days=days)


def _require_owned_project(db: DbSession, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.owner_id != authenticated_user_id():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Project access forbidden")
    return project


def _owned_project_ids(db: DbSession) -> set[int]:
    return set(db.scalars(select(Project.id).where(Project.owner_id == authenticated_user_id())))
