import re
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import Worker, WorkerType
from app.services.persian_role_extractor import PersianRoleExtractor


class EntityRegistryService:
    def __init__(self, db: Session, project_id: int) -> None:
        self.db = db
        self.project_id = project_id
        self.role_extractor = PersianRoleExtractor()

    def apply_setup(self, entities: list[dict[str, Any]]) -> list[Worker]:
        updated_entities: list[Worker] = []
        for entity in entities:
            name = entity.get("name")
            if not isinstance(name, str) or not name.strip():
                continue

            worker = self._get_or_create_entity(name.strip(), self._entity_type(entity.get("type")))
            self._update_if_present(worker, "phone", entity.get("phone"))
            self._update_if_present(worker, "account_number", entity.get("account_number"))
            self._update_if_present(worker, "role_detail", entity.get("role_detail"))
            self._update_decimal_if_present(worker, "daily_rate", entity.get("daily_rate"))
            self._update_if_present(worker, "notes", entity.get("notes"))
            updated_entities.append(worker)

        return updated_entities
    
    def apply_setup_from_text(self, text: str) -> list[Worker]:
        """
        Apply setup using deterministic role-phrase extraction.
        
        This method uses the PersianRoleExtractor to extract entity names
        and types directly from Persian text, without relying on LLM output.
        """
        extracted_role = self.role_extractor.extract(text)
        if not extracted_role:
            return []
        
        worker = self._get_or_create_entity(
            extracted_role.name,
            extracted_role.worker_type,
        )
        
        return [worker]

    def update_entities(self, entities: list[dict[str, Any]]) -> list[Worker]:
        updated_entities: list[Worker] = []
        for entity in entities:
            name = entity.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            worker = self.find_by_partial_match(name)
            if worker is None:
                continue
            updates = (
                entity.get("field_updates")
                if isinstance(entity.get("field_updates"), dict)
                else entity
            )
            self._update_if_present(worker, "phone", updates.get("phone"))
            self._update_if_present(worker, "account_number", updates.get("account_number"))
            self._update_if_present(worker, "role_detail", updates.get("role_detail"))
            self._update_decimal_if_present(worker, "daily_rate", updates.get("daily_rate"))
            self._update_if_present(worker, "notes", updates.get("notes"))
            self._update_type_if_explicit(worker, entity, updates)
            updated_entities.append(worker)
        return updated_entities

    def update_entity_by_id(self, worker_id: int, entity: dict[str, Any]) -> list[Worker]:
        worker = self.db.get(Worker, worker_id)
        if worker is None or worker.project_id != self.project_id:
            return []
        updates = (
            entity.get("field_updates")
            if isinstance(entity.get("field_updates"), dict)
            else entity
        )
        self._update_if_present(worker, "phone", updates.get("phone"))
        self._update_if_present(worker, "account_number", updates.get("account_number"))
        self._update_if_present(worker, "role_detail", updates.get("role_detail"))
        self._update_decimal_if_present(worker, "daily_rate", updates.get("daily_rate"))
        self._update_if_present(worker, "notes", updates.get("notes"))
        self._update_type_if_explicit(worker, entity, updates)
        return [worker]

    def update_entity_by_partial_match(self, text: str) -> list[Worker]:
        worker = self.find_by_partial_match(text)
        if worker is None:
            return []
        phone = self._extract_phone(text)
        account_number = self._extract_account_number(text)
        if phone is None and account_number is None:
            return []
        self._update_if_present(worker, "phone", phone)
        self._update_if_present(worker, "account_number", account_number)
        return [worker]

    def find_by_partial_match(self, text: str) -> Worker | None:
        normalized_text = self._normalize_name(text)
        compact_text = self._compact_name(text)
        if not normalized_text:
            return None
        workers = list(self.db.scalars(select(Worker).where(Worker.project_id == self.project_id)))
        buckets: list[list[Worker]] = [
            [worker for worker in workers if self._normalize_name(worker.name) == normalized_text],
            [worker for worker in workers if self._compact_name(worker.name) == compact_text],
            [worker for worker in workers if self._normalize_name(worker.name).startswith(normalized_text)],
            [worker for worker in workers if self._compact_name(worker.name).startswith(compact_text)],
            [worker for worker in workers if normalized_text in self._normalize_name(worker.name).split()],
            [worker for worker in workers if normalized_text in self._normalize_name(worker.name)],
            [worker for worker in workers if self._normalize_name(worker.name) in normalized_text],
            [worker for worker in workers if self._compact_name(worker.name) in compact_text],
        ]
        for matches in buckets:
            unique = {worker.id: worker for worker in matches}
            if len(unique) == 1:
                return next(iter(unique.values()))
            if len(unique) > 1:
                return None
        return None

    def detect_duplicate_entities(self) -> list[list[Worker]]:
        groups: dict[str, list[Worker]] = {}
        workers = self.db.scalars(select(Worker).where(Worker.project_id == self.project_id))
        for worker in workers:
            groups.setdefault(self._normalize_name(worker.name), []).append(worker)
        return [group for group in groups.values() if len(group) > 1]

    def merge_entities(self, keep: Worker, duplicate: Worker) -> Worker:
        self._update_if_present(keep, "phone", keep.phone or duplicate.phone)
        self._update_if_present(
            keep,
            "account_number",
            keep.account_number or duplicate.account_number,
        )
        self._update_if_present(keep, "role_detail", keep.role_detail or duplicate.role_detail)
        self.db.delete(duplicate)
        self.db.flush()
        return keep

    def _get_or_create_entity(self, name: str, entity_type: WorkerType) -> Worker:
        worker = self.db.scalar(
            select(Worker).where(Worker.project_id == self.project_id, Worker.name == name)
        )
        if worker is not None:
            if worker.type != entity_type:
                worker.type = entity_type
            return worker

        if not self._has_disambiguating_role_qualifier(name):
            duplicate_match = self.find_by_partial_match(name)
            if duplicate_match is not None:
                return duplicate_match

        worker = Worker(project_id=self.project_id, name=name, type=entity_type)
        self.db.add(worker)
        self.db.flush()
        return worker

    def _has_disambiguating_role_qualifier(self, name: str) -> bool:
        normalized = self._normalize_name(name)
        qualifiers = {
            "تاسیساتی",
        }
        return any(qualifier in normalized for qualifier in qualifiers)

    def _entity_type(self, value: Any) -> WorkerType:
        if value == "CLIENT":
            return WorkerType.CLIENT
        if value == "VENDOR":
            return WorkerType.VENDOR
        if value in {"SKILLED", "SKILLED_WORKER"}:
            return WorkerType.SKILLED_WORKER
        if value in {"WORKER", "DAILY_WORKER"}:
            return WorkerType.DAILY_WORKER
        if value == "OTHER":
            return WorkerType.OTHER
        return WorkerType.OTHER

    def _update_if_present(self, worker: Worker, field: str, value: Any) -> None:
        if isinstance(value, str) and value.strip():
            setattr(worker, field, value.strip())

    def _update_decimal_if_present(self, worker: Worker, field: str, value: Any) -> None:
        if value is None or value == "":
            return
        try:
            setattr(worker, field, Decimal(str(value)))
        except (InvalidOperation, ValueError):
            return

    def _update_type_if_explicit(self, worker: Worker, entity: dict[str, Any], updates: dict[str, Any]) -> None:
        if not isinstance(entity.get("field_updates"), dict):
            return
        value = updates.get("type") or updates.get("project_role")
        if value is not None:
            worker.type = self._entity_type(value)

    def _normalize_name(self, value: str) -> str:
        normalized = value.replace("\u200c", " ").strip()
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = re.sub(r"^(مش|آقای|اقای|خانم)\s+", "", normalized)
        return normalized

    def _compact_name(self, value: str) -> str:
        return self._normalize_name(value).replace(" ", "")

    def _extract_phone(self, text: str) -> str | None:
        match = re.search(r"09\d{9}", text.replace(" ", ""))
        return match.group() if match is not None else None

    def _extract_account_number(self, text: str) -> str | None:
        if "حساب" not in text and "کارت" not in text and "شبا" not in text:
            return None
        match = re.search(r"\d{8,26}", text.replace(" ", ""))
        return match.group() if match is not None else None
