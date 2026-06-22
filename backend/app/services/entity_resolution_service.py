from typing import Any
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.trace_events import TraceEvent, trace_event
from app.models.core import Worker, WorkerType
from app.services.identity_key import generate_identity_key


class EntityResolutionService:
    def __init__(self, db: Session, project_id: int) -> None:
        if project_id is None or project_id <= 0:
            raise ValueError("Project must be explicitly resolved")
        self.db = db
        self.project_id = project_id

    def resolve(
        self,
        *,
        entity_id: int | None = None,
        name: str | None = None,
        role: str | WorkerType | None = None,
        role_detail: str | None = None,
        create_new: bool = False,
    ) -> dict[str, Any]:
        start = perf_counter()
        is_new = False
        worker_type = self._worker_type(role)
        worker = self._by_id(entity_id) if entity_id is not None else None
        if worker is None and name:
            worker = self._by_name(name, worker_type)
        if worker is None and create_new:
            worker = self._create(name, role, role_detail)
            is_new = True
        if worker is None:
            raise ValueError("Entity must be resolved before execution")
        result = {
            "entity_id": worker.id,
            "is_new": is_new,
            "name": worker.name,
            "role": worker.type.value,
            "status": "RESOLVED",
        }
        trace_event(
            TraceEvent.ENTITY_RESOLVED,
            {
                "entity_id": result["entity_id"],
                "is_new": result["is_new"],
                "project_id": self.project_id,
                "role": result["role"],
            },
            start_time=start,
        )
        return result

    def _by_id(self, entity_id: int | None) -> Worker | None:
        if entity_id is None:
            return None
        worker = self.db.get(Worker, entity_id)
        if worker is None or worker.project_id != self.project_id:
            return None
        return worker

    def _by_name(self, name: str, role: WorkerType) -> Worker | None:
        stripped = name.strip()
        if not stripped:
            return None
        exact_role_match = self.db.scalar(
            select(Worker).where(
                Worker.project_id == self.project_id,
                Worker.name == stripped,
                Worker.type == role,
            )
        )
        if exact_role_match is not None:
            return exact_role_match
        if role == WorkerType.OTHER:
            return self.db.scalar(
                select(Worker).where(
                    Worker.project_id == self.project_id,
                    Worker.name == stripped,
                )
            )
        return None

    def _create(
        self,
        name: str | None,
        role: str | WorkerType | None,
        role_detail: str | None = None,
    ) -> Worker:
        stripped = name.strip() if isinstance(name, str) else ""
        if not stripped:
            raise ValueError("Entity resolution requires a name")
        worker_type = self._worker_type(role)
        identity_key = generate_identity_key(stripped, None)
        worker = Worker(
            project_id=self.project_id,
            name=stripped,
            type=worker_type,
            identity_key=identity_key,
            role_detail=role_detail.strip() if isinstance(role_detail, str) and role_detail.strip() else None,
        )
        self.db.add(worker)
        self.db.flush()
        return worker

    def _worker_type(self, role: str | WorkerType | None) -> WorkerType:
        value = role.value if isinstance(role, WorkerType) else role
        if value == "CLIENT":
            return WorkerType.CLIENT
        if value == "VENDOR":
            return WorkerType.VENDOR
        if value in {"SKILLED", "SKILLED_WORKER"}:
            return WorkerType.SKILLED_WORKER
        if value in {"WORKER", "DAILY_WORKER"}:
            return WorkerType.DAILY_WORKER
        return WorkerType.OTHER
