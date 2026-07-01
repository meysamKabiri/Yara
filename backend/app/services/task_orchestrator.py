from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import Worker
from app.services.domain_router_service import DomainRouterService
from app.services.task_assignment_suggester import suggest_assignee
from app.services.time_extraction_service import extract_due_date


class TaskOrchestrator:
    def __init__(
        self,
        time_service: Any = None,
        assignment_service: Any = None,
        domain_router: Any = None,
        entity_service: Any = None,
        llm_interpreter: Any = None,
    ) -> None:
        self.time_service = time_service or extract_due_date
        self.assignment_service = assignment_service or suggest_assignee
        self.domain_router = domain_router or DomainRouterService()
        self.entity_service = entity_service
        self.llm_interpreter = llm_interpreter

    def build_task(self, text: str, project_context: dict[str, Any]) -> dict[str, Any]:
        safe_text = (text or "").strip()
        domain_result = self._safe_domain(safe_text)
        time_result = self._safe_time(safe_text, project_context)
        entities = self._safe_entities(safe_text, project_context)
        assignment = self._safe_assignment(safe_text, project_context)
        llm_result = self._safe_llm(safe_text, domain_result, time_result, assignment)

        context = {
            "text": safe_text,
            "base_date": project_context.get("base_date"),
            "domain": domain_result,
            "time": time_result,
            "assignment": assignment,
            "entities": entities,
            "llm": llm_result,
        }
        return self._resolve_final_task(context)

    def _safe_domain(self, text: str) -> dict[str, Any]:
        try:
            routed = self._call_route(text)
            return {
                "domain": str(routed.get("domain") or "UNKNOWN"),
                "confidence": self._clamp(float(routed.get("confidence") or 0.0)),
                "raw": routed,
            }
        except Exception as exc:
            return {"domain": "UNKNOWN", "confidence": 0.0, "error": str(exc)}

    def _safe_time(self, text: str, project_context: dict[str, Any]) -> dict[str, Any]:
        if "due_date_override" in project_context:
            override = project_context.get("due_date_override")
            return {
                "due_date": override.isoformat() if isinstance(override, date) else override,
                "confidence": 1.0 if override else 0.0,
                "source": "user_edit",
            }
        try:
            base_date = project_context.get("base_date") or datetime.now(UTC)
            result = self._call_time(text, base_date)
            due_date = self._normalize_due_date_from_time_result(text, result, base_date)
            return {
                "due_date": due_date,
                "hint": result.get("hint"),
                "confidence": self._clamp(float(result.get("confidence") or 0.0)),
                "source": result.get("source") or "deterministic_rule",
            }
        except Exception as exc:
            return {"due_date": None, "confidence": 0.0, "source": "failed", "error": str(exc)}

    def _safe_entities(self, text: str, project_context: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            extractor = getattr(self.entity_service, "extract", None)
            if callable(extractor):
                extracted = extractor(text, project_context)
                return extracted if isinstance(extracted, list) else []
            db: Session | None = project_context.get("db")
            project_id = project_context.get("project_id")
            if db is None or not project_id:
                return []
            workers = list(db.scalars(select(Worker).where(Worker.project_id == project_id)))
            normalized = self._normalize(text)
            return [
                {"id": worker.id, "name": worker.name, "role": worker.type.value}
                for worker in workers
                if self._normalize(worker.name) and self._normalize(worker.name) in normalized
            ]
        except Exception:
            return []

    def _safe_assignment(self, text: str, project_context: dict[str, Any]) -> dict[str, Any]:
        try:
            suggested = self._call_assignment(text, project_context)
            person = suggested.get("suggested_person")
            candidates = suggested.get("candidates") if isinstance(suggested.get("candidates"), list) else []
            source = str(suggested.get("source") or "none")
            return {
                "suggested_person": person,
                "source": source,
                "candidates": candidates,
                "confidence": float(person.get("confidence") if isinstance(person, dict) else 0.0),
            }
        except Exception as exc:
            return {"suggested_person": None, "source": "none", "candidates": [], "confidence": 0.0, "error": str(exc)}

    def _safe_llm(
        self,
        text: str,
        domain_result: dict[str, Any],
        time_result: dict[str, Any],
        assignment: dict[str, Any],
    ) -> dict[str, Any] | None:
        if self.llm_interpreter is None:
            return None
        low_confidence = (
            float(domain_result.get("confidence") or 0.0) < 0.5
            or float(time_result.get("confidence") or 0.0) < 0.4
            or float(assignment.get("confidence") or 0.0) < 0.5
        )
        ambiguous = len(assignment.get("candidates") or []) > 1 and assignment.get("suggested_person") is None
        if not low_confidence and not ambiguous:
            return None
        try:
            interpret = getattr(self.llm_interpreter, "interpret", None)
            if callable(interpret):
                result = interpret(text)
                return result if isinstance(result, dict) else None
        except Exception as exc:
            return {"error": str(exc)}
        return None

    def _resolve_final_task(self, context: dict[str, Any]) -> dict[str, Any]:
        domain = self._resolve_domain(context)
        assignee = self._resolve_assignee(context)
        due_date = self._resolve_due_date(context)
        domain_confidence = float(context["domain"].get("confidence") or 0.0)
        assignment_confidence = float(assignee.get("confidence") or 0.0)
        time_confidence = float(due_date.get("confidence") or 0.0)
        final_confidence = self._clamp(
            (domain_confidence * 0.3)
            + (assignment_confidence * 0.4)
            + (time_confidence * 0.3)
        )
        ambiguous_assignment = len(context["assignment"].get("candidates") or []) > 1 and assignee.get("id") is None
        low_confidence_time = 0 < time_confidence < 0.7
        needs_confirmation = (
            final_confidence < 0.7
            or low_confidence_time
            or ambiguous_assignment
            or assignee.get("id") is None
        )
        final_task = {
            "title": context["text"],
            "description": context["text"],
            "domain": domain,
            "ui_mode": "TaskDashboard" if domain == "TASK" else None,
            "assignee": assignee,
            "due_date": due_date,
            "entities": context["entities"],
            "confidence": final_confidence,
            "flags": {
                "needs_user_confirmation": needs_confirmation,
                "low_confidence_time": low_confidence_time,
                "ambiguous_assignment": ambiguous_assignment,
            },
            "context": context,
        }
        self._force_due_date_from_matched_time_signals(final_task, context)
        return final_task

    def _resolve_domain(self, context: dict[str, Any]) -> str:
        return str(context["domain"].get("domain") or "UNKNOWN")

    def _resolve_assignee(self, context: dict[str, Any]) -> dict[str, Any]:
        assignment = context["assignment"]
        person = assignment.get("suggested_person")
        source = str(assignment.get("source") or "none")
        mapped_source = {
            "name_match": "exact_match",
            "role_match": "role_match",
            "recent_assignment": "role_match",
        }.get(source, "llm" if source == "llm" else "none")
        if isinstance(person, dict):
            return {
                "id": person.get("id"),
                "name": person.get("name"),
                "confidence": self._clamp(float(person.get("confidence") or 0.0)),
                "source": mapped_source,
            }
        llm_person = self._extract_llm_person(context.get("llm"))
        if llm_person is not None:
            return {
                "id": llm_person.get("id"),
                "name": llm_person.get("name"),
                "confidence": self._clamp(float(llm_person.get("confidence") or 0.0)),
                "source": "llm",
            }
        return {"id": None, "name": None, "confidence": 0.0, "source": "none"}

    def _resolve_due_date(self, context: dict[str, Any]) -> dict[str, Any]:
        time_result = context["time"]
        if not time_result.get("due_date"):
            llm_due_date = self._extract_llm_due_date(context.get("llm"))
            if llm_due_date is not None:
                return llm_due_date
        source = str(time_result.get("source") or "")
        mapped_source = "llm" if "llm" in source else "deterministic" if source else None
        return {
            "value": time_result.get("due_date"),
            "hint": time_result.get("hint"),
            "confidence": self._clamp(float(time_result.get("confidence") or 0.0)),
            "source": mapped_source,
        }

    def _normalize_due_date_from_time_result(
        self,
        text: str,
        result: dict[str, Any],
        base_date: datetime | date,
    ) -> str | None:
        for key in ("due_date", "normalized_date", "date"):
            coerced = self._coerce_date_value(result.get(key), base_date)
            if coerced is not None:
                return coerced

        for key in ("extracted_time", "time", "hint"):
            coerced = self._coerce_relative_date(result.get(key), base_date)
            if coerced is not None:
                return coerced

        return self._coerce_relative_date(text, base_date)

    def _coerce_date_value(self, value: Any, base_date: datetime | date) -> str | None:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            try:
                return date.fromisoformat(stripped).isoformat()
            except ValueError:
                return self._coerce_relative_date(stripped, base_date)
        return None

    def _coerce_relative_date(self, value: Any, base_date: datetime | date) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = self._normalize(value).lower()
        if not normalized:
            return None
        base_day = base_date.date() if isinstance(base_date, datetime) else base_date
        if "پس فردا" in normalized or "پسفردا" in normalized or "day_after_tomorrow" in normalized:
            return (base_day + timedelta(days=2)).isoformat()
        if "فردا" in normalized or "tomorrow" in normalized:
            return (base_day + timedelta(days=1)).isoformat()
        if "امروز" in normalized or "today" in normalized:
            return base_day.isoformat()
        return None

    def _force_due_date_from_matched_time_signals(
        self,
        final_task: dict[str, Any],
        context: dict[str, Any],
    ) -> None:
        time_result = context.get("time")
        if isinstance(time_result, dict) and time_result.get("source") == "user_edit":
            return
        base_date = context.get("base_date") or datetime.now(UTC)
        forced_value = self._matched_signal_due_date(context, base_date)
        if forced_value is None:
            return
        existing = final_task.get("due_date") if isinstance(final_task.get("due_date"), dict) else {}
        final_task["due_date"] = {
            **existing,
            "value": forced_value,
            "confidence": max(float(existing.get("confidence") or 0.0), 0.95),
            "source": "deterministic",
        }

    def _matched_signal_due_date(self, context: dict[str, Any], base_date: datetime | date) -> str | None:
        for signal in self._iter_time_signals(context):
            coerced = self._coerce_relative_date(signal, base_date)
            if coerced is not None:
                return coerced
        return None

    def _iter_time_signals(self, context: dict[str, Any]) -> list[str]:
        signals: list[str] = []

        def collect(value: Any) -> None:
            if isinstance(value, str):
                signals.append(value)
                return
            if isinstance(value, dict):
                semantic_explanation = value.get("semantic_explanation")
                if isinstance(semantic_explanation, dict):
                    collect(semantic_explanation.get("matched_signals"))
                if "matched_signals" in value:
                    collect(value.get("matched_signals"))
                for key in ("due_date", "normalized_date", "extracted_time", "time", "hint"):
                    collect(value.get(key))
                return
            if isinstance(value, list | tuple | set):
                for item in value:
                    collect(item)

        collect(context.get("text"))
        collect(context.get("time"))
        collect(context.get("llm"))
        collect(context.get("domain"))
        return signals

    def _call_route(self, text: str) -> dict[str, Any]:
        route = getattr(self.domain_router, "route", None)
        if callable(route):
            result = route(text)
            return result if isinstance(result, dict) else {}
        if callable(self.domain_router):
            result = self.domain_router(text)
            return result if isinstance(result, dict) else {}
        return {}

    def _call_time(self, text: str, base_date: datetime) -> dict[str, Any]:
        extractor = getattr(self.time_service, "extract_due_date", None)
        fn: Callable[..., Any] = extractor if callable(extractor) else self.time_service
        result = fn(text, base_date)
        return result if isinstance(result, dict) else {}

    def _call_assignment(self, text: str, project_context: dict[str, Any]) -> dict[str, Any]:
        suggester = getattr(self.assignment_service, "suggest", None)
        if callable(suggester):
            result = suggester(text, project_context)
        else:
            result = self.assignment_service(
                project_context["db"],
                task_input=text,
                project_id=int(project_context["project_id"]),
                extracted_actor=project_context.get("extracted_actor"),
            )
        return result if isinstance(result, dict) else {}

    def _extract_llm_person(self, llm_result: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(llm_result, dict):
            return None
        for key in ("assignee", "suggested_person", "assignment"):
            candidate = llm_result.get(key)
            if isinstance(candidate, dict) and candidate.get("name"):
                return candidate
        return None

    def _extract_llm_due_date(self, llm_result: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(llm_result, dict):
            return None
        candidate = llm_result.get("due_date")
        if isinstance(candidate, dict):
            value = candidate.get("value") or candidate.get("due_date")
            confidence = candidate.get("confidence")
            hint = candidate.get("hint")
        else:
            value = candidate
            confidence = llm_result.get("due_date_confidence")
            hint = llm_result.get("time_hint")
        if not value and not hint:
            return None
        return {
            "value": value,
            "hint": hint,
            "confidence": self._clamp(float(confidence or 0.4)),
            "source": "llm",
        }

    def _normalize(self, text: str | None) -> str:
        value = (text or "").strip().replace("ي", "ی").replace("ك", "ک")
        return " ".join(value.split())

    def _clamp(self, value: float) -> float:
        return max(0.0, min(1.0, value))
