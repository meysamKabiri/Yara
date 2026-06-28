from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.dependencies.database import DbSession
from app.models.core import DeadLetterJob
from app.services.financial_reconciliation_service import (
    latest_reconciliation_report,
    reconcile_project,
    recover_stuck_confirming_interpretations,
    safety_metrics,
)


router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/dlq-jobs")
def list_dlq_jobs(db: DbSession) -> list[dict[str, Any]]:
    jobs = db.scalars(select(DeadLetterJob).order_by(DeadLetterJob.created_at.desc(), DeadLetterJob.id.desc()))
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
    try:
        return latest_reconciliation_report(db, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/reconciliation-report/{project_id}/run")
def run_reconciliation(project_id: int, db: DbSession) -> dict[str, Any]:
    try:
        return reconcile_project(db, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/recover-confirming")
def recover_confirming(db: DbSession, max_age_minutes: int = 15) -> dict[str, int]:
    recovered = recover_stuck_confirming_interpretations(db, max_age_minutes=max_age_minutes)
    return {"recovered": recovered}


@router.get("/safety-metrics")
def read_safety_metrics(db: DbSession) -> dict[str, int]:
    return safety_metrics(db)
