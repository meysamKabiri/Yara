from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.dependencies.database import DbSession
from app.models.core import (
    ExtractedEvent,
    ExtractedEventStatus,
    ExtractedEventType,
    Project,
    RawEntry,
    RawEntryStatus,
)
from app.schemas.projects import (
    ExtractedEventCreate,
    ExtractedEventRead,
    ExtractedEventUpdate,
    ProjectCreate,
    ProjectDetail,
    ProjectRead,
    ProjectTotals,
    RawEntryCreate,
    RawEntryRead,
)
from app.services.extraction import extract_pending_events

router = APIRouter(tags=["projects"])


def _get_project(db: DbSession, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def _get_raw_entry(db: DbSession, project_id: int, raw_entry_id: int) -> RawEntry:
    raw_entry = db.get(RawEntry, raw_entry_id)
    if raw_entry is None or raw_entry.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Raw entry not found")
    return raw_entry


def _get_event(db: DbSession, event_id: int) -> ExtractedEvent:
    event = db.get(ExtractedEvent, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Extracted event not found",
        )
    return event


def _require_pending(event: ExtractedEvent) -> None:
    if event.status != ExtractedEventStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending extracted events can be changed",
        )


def _project_totals(db: DbSession, project_id: int) -> ProjectTotals:
    events = db.scalars(
        select(ExtractedEvent).where(
            ExtractedEvent.project_id == project_id,
            ExtractedEvent.status == ExtractedEventStatus.CONFIRMED,
        )
    )
    money_in = Decimal("0")
    money_out = Decimal("0")
    for event in events:
        if event.amount is None or event.type == ExtractedEventType.NOTE:
            continue
        if event.type == ExtractedEventType.MONEY_IN:
            money_in += event.amount
        elif event.type in {ExtractedEventType.MONEY_OUT, ExtractedEventType.PURCHASE}:
            money_out += event.amount
    return ProjectTotals(money_in=money_in, money_out=money_out, net=money_in - money_out)


@router.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: DbSession) -> Project:
    project = Project(name=payload.name)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/projects", response_model=list[ProjectRead])
def list_projects(db: DbSession) -> list[Project]:
    return list(db.scalars(select(Project).order_by(Project.created_at.desc(), Project.id.desc())))


@router.get("/projects/{project_id}", response_model=ProjectDetail)
def get_project(project_id: int, db: DbSession) -> ProjectDetail:
    project = _get_project(db, project_id)
    return ProjectDetail(
        **ProjectRead.model_validate(project).model_dump(),
        totals=_project_totals(db, project_id),
    )


@router.post(
    "/projects/{project_id}/raw-entries",
    response_model=RawEntryRead,
    status_code=status.HTTP_201_CREATED,
)
def create_raw_entry(project_id: int, payload: RawEntryCreate, db: DbSession) -> RawEntry:
    _get_project(db, project_id)
    raw_entry = RawEntry(project_id=project_id, text=payload.text)
    db.add(raw_entry)
    db.commit()
    db.refresh(raw_entry)
    return raw_entry


@router.get("/projects/{project_id}/raw-entries", response_model=list[RawEntryRead])
def list_raw_entries(project_id: int, db: DbSession) -> list[RawEntry]:
    _get_project(db, project_id)
    return list(
        db.scalars(
            select(RawEntry)
            .where(RawEntry.project_id == project_id)
            .order_by(RawEntry.created_at.desc(), RawEntry.id.desc())
        )
    )


@router.post(
    "/projects/{project_id}/raw-entries/{raw_entry_id}/extracted-events",
    response_model=list[ExtractedEventRead],
    status_code=status.HTTP_201_CREATED,
)
def create_extracted_events(
    project_id: int,
    raw_entry_id: int,
    payload: list[ExtractedEventCreate],
    db: DbSession,
) -> list[ExtractedEvent]:
    raw_entry = _get_raw_entry(db, project_id, raw_entry_id)
    events = [
        ExtractedEvent(
            project_id=project_id,
            raw_entry_id=raw_entry_id,
            status=ExtractedEventStatus.PENDING,
            **event.model_dump(),
        )
        for event in payload
    ]
    raw_entry.status = RawEntryStatus.PROCESSED
    db.add_all(events)
    db.commit()
    for event in events:
        db.refresh(event)
    return events


@router.post(
    "/projects/{project_id}/raw-entries/{raw_entry_id}/extract",
    response_model=list[ExtractedEventRead],
    status_code=status.HTTP_201_CREATED,
)
def extract_raw_entry_events(
    project_id: int,
    raw_entry_id: int,
    db: DbSession,
) -> list[ExtractedEvent]:
    raw_entry = _get_raw_entry(db, project_id, raw_entry_id)
    try:
        events = extract_pending_events(raw_entry.text)
        for event in events:
            event.project_id = project_id
            event.raw_entry_id = raw_entry_id
            event.status = ExtractedEventStatus.PENDING
        raw_entry.status = RawEntryStatus.PROCESSED
        db.add_all(events)
        db.commit()
    except Exception as exc:
        raw_entry.status = RawEntryStatus.FAILED
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Extraction failed",
        ) from exc

    for event in events:
        db.refresh(event)
    return events


@router.get(
    "/projects/{project_id}/extracted-events/pending",
    response_model=list[ExtractedEventRead],
)
def list_pending_events(project_id: int, db: DbSession) -> list[ExtractedEvent]:
    _get_project(db, project_id)
    return list(
        db.scalars(
            select(ExtractedEvent)
            .where(
                ExtractedEvent.project_id == project_id,
                ExtractedEvent.status == ExtractedEventStatus.PENDING,
            )
            .order_by(ExtractedEvent.created_at.desc(), ExtractedEvent.id.desc())
        )
    )


@router.get(
    "/projects/{project_id}/extracted-events/confirmed",
    response_model=list[ExtractedEventRead],
)
def list_confirmed_events(project_id: int, db: DbSession) -> list[ExtractedEvent]:
    _get_project(db, project_id)
    return list(
        db.scalars(
            select(ExtractedEvent)
            .where(
                ExtractedEvent.project_id == project_id,
                ExtractedEvent.status == ExtractedEventStatus.CONFIRMED,
            )
            .order_by(ExtractedEvent.created_at.desc(), ExtractedEvent.id.desc())
        )
    )


@router.patch("/extracted-events/{event_id}", response_model=ExtractedEventRead)
def update_extracted_event(
    event_id: int,
    payload: ExtractedEventUpdate,
    db: DbSession,
) -> ExtractedEvent:
    event = _get_event(db, event_id)
    _require_pending(event)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(event, field, value)
    db.commit()
    db.refresh(event)
    return event


@router.post("/extracted-events/{event_id}/confirm", response_model=ExtractedEventRead)
def confirm_extracted_event(event_id: int, db: DbSession) -> ExtractedEvent:
    event = _get_event(db, event_id)
    _require_pending(event)
    event.status = ExtractedEventStatus.CONFIRMED
    db.commit()
    db.refresh(event)
    return event


@router.post("/extracted-events/{event_id}/discard", response_model=ExtractedEventRead)
def discard_extracted_event(event_id: int, db: DbSession) -> ExtractedEvent:
    event = _get_event(db, event_id)
    _require_pending(event)
    event.status = ExtractedEventStatus.DISCARDED
    db.commit()
    db.refresh(event)
    return event
