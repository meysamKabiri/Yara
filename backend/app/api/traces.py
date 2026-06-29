from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import authenticated_user_id, get_current_user
from app.core.event_tracker import get_trace_anomalies, get_trace_events, list_recent_traces
from app.dependencies.database import DbSession
from app.models.core import Project

router = APIRouter(tags=["traces"], dependencies=[Depends(get_current_user)])


@router.get("/traces")
def list_traces(
    db: DbSession,
    project_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    if project_id is not None:
        _ensure_project_access(db, project_id)
    return {
        "project_id": project_id,
        "traces": list_recent_traces(db=db, project_id=project_id, limit=limit),
    }


@router.get("/traces/anomalies")
def read_trace_anomalies(
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    return get_trace_anomalies(db=db, limit=limit)


@router.get("/traces/{trace_id}")
def read_trace(trace_id: str, db: DbSession) -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "events": get_trace_events(trace_id, db=db),
    }


def _ensure_project_access(db: DbSession, project_id: int) -> None:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.owner_id != authenticated_user_id():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Project access forbidden",
        )
