from __future__ import annotations

import re
from enum import StrEnum
from time import perf_counter
from typing import Any
from sqlalchemy.orm import Session

from app.core.domain_fallback_policy import resolve_fallback
from app.core.observability_service import track_event, track_timed_event


_PROFILE_FIELD_KEYS = {"phone", "account_number", "accountNumber", "card_number", "cardNumber", "daily_rate", "dailyRate", "notes"}


def _field_updates_has_profile_keys(field_updates: dict) -> bool:
    return any(
        field_updates.get(key) not in (None, "")
        for key in _PROFILE_FIELD_KEYS
    )


class DomainType(StrEnum):
    TASK = "TASK"
    SETUP = "SETUP"
    FINANCIAL = "FINANCIAL"
    WORK = "WORK"
    MIXED = "MIXED"
    ENTITY_UPDATE = "ENTITY_UPDATE"
    NOTE = "NOTE"


class DomainRouterService:
    """Route interpreted user input to one product domain.

    This layer does not execute business behavior. It only chooses the UI schema
    and backend domain pipeline that should handle an already interpreted input.
    """

    SETUP_SCHEMA = "setup_confirmation"
    FINANCIAL_SCHEMA = "financial_confirmation"
    TASK_SCHEMA = "task_confirmation"
    WORK_SCHEMA = "work_log_confirmation"
    MIXED_SCHEMA = "split_confirmation"
    ENTITY_UPDATE_SCHEMA = "entity_update_confirmation"

    SETUP_UI = "SetupModal"
    FINANCIAL_UI = "FinancialModal"
    TASK_UI = "TaskDashboard"
    WORK_UI = "WorkLogModal"
    MIXED_UI = "SplitFlow"
    ENTITY_UPDATE_UI = "EntityUpdateModal"

    _SETUP_ACTIONS = {"ADD_ENTITY", "UPDATE_ENTITY", "ENTITY_UPDATE", "SET_ROLE", "SETUP"}
    _FINANCIAL_ACTIONS = {
        "PAYMENT",
        "PAYMENT_IN",
        "PAYMENT_OUT",
        "PAYMENT_RECEIVED",
        "PURCHASE_PAID",
        "PURCHASE_UNPAID",
        "DEBT_CREATED",
        "CHECK_PAYMENT",
    }
    _SETUP_PATTERNS = (
        "کارفرما",
        "کارگر",
        "استادکار",
        "فروشنده",
        "پیمانکار",
        "شماره تماس",
        "شماره موبایل",
        "شماره حساب",
        "اضافه",
        "به پروژه اضافه",
    )
    _FINANCIAL_PATTERNS = (
        "گرفتم",
        "گرفت",
        "پرداختم",
        "پرداخت کردم",
        "پرداخت کرد",
        "خریدم",
        "خرید کردم",
        "واریز",
        "پول داد",
        "چک دادم",
        "چک",
        "million",
        "milyon",
        "pardakht",
        "gereft",
        "kharid",
    )
    _TASK_ACTION_PATTERNS = (
        "بیاد",
        "بیا",
        "انجام بده",
        "انجام بدهد",
        "جمع کنه",
        "جمع کند",
        "جوش بده",
        "جوش بدهد",
        "کار کنه",
        "کمک کنه",
    )
    _TIME_HINT_PATTERNS = ("امروز", "فردا", "پس فردا")

    def route(self, raw_user_text: str, llm_interpretation: dict[str, Any] | None = None, db: Session | None = None) -> dict[str, Any]:
        if db is None:
            return self._route_impl(raw_user_text, llm_interpretation, db=None)
        return track_timed_event(
            db=db,
            event_name="domain_router.route",
            fn=lambda: self._route_impl(raw_user_text, llm_interpretation, db=db),
        )

    def _route_impl(self, raw_user_text: str, llm_interpretation: dict[str, Any] | None = None, db: Session | None = None) -> dict[str, Any]:
        start = perf_counter()
        text = self._normalize(raw_user_text)
        interpretation = llm_interpretation or {}
        has_profile_update = self._has_profile_update_fields(interpretation)
        setup_score = self._setup_score(text, interpretation)
        financial_score = self._financial_score(text, interpretation)
        financial_intent = self._has_financial_intent(interpretation)
        work_intent = self._has_work_intent(interpretation)

        if work_intent or self._has_task_execution_text(text):
            result = self._result(DomainType.TASK, 0.95)
            self._emit_route_event(db, start, raw_user_text, interpretation, result, setup_score, financial_score)
            return result
        if has_profile_update and financial_score == 0:
            result = self._result(DomainType.ENTITY_UPDATE, min(0.95, 0.75 + setup_score * 0.05))
            self._emit_route_event(db, start, raw_user_text, interpretation, result, setup_score, financial_score)
            return result
        if financial_intent and financial_score > 0 and not self._has_explicit_setup_declaration(text):
            result = self._result(DomainType.FINANCIAL, min(0.95, 0.75 + financial_score * 0.05))
            self._emit_route_event(db, start, raw_user_text, interpretation, result, setup_score, financial_score)
            return result
        if setup_score > 0 and financial_score > 0:
            result = self._result(DomainType.MIXED, 0.9)
            self._emit_route_event(db, start, raw_user_text, interpretation, result, setup_score, financial_score)
            return result
        if financial_score > 0:
            result = self._result(DomainType.FINANCIAL, min(0.95, 0.75 + financial_score * 0.05))
            self._emit_route_event(db, start, raw_user_text, interpretation, result, setup_score, financial_score)
            return result
        if setup_score > 0 and self._has_explicit_setup_declaration(text):
            result = self._result(DomainType.SETUP, min(0.95, 0.75 + setup_score * 0.05))
            self._emit_route_event(db, start, raw_user_text, interpretation, result, setup_score, financial_score)
            return result
        result = self._result(DomainType(resolve_fallback(context={"raw_text": raw_user_text, "interpretation": interpretation})), 0.5)
        self._emit_route_event(db, start, raw_user_text, interpretation, result, setup_score, financial_score)
        return result

    def _emit_route_event(
        self,
        db: Session | None,
        start: float,
        raw_user_text: str,
        interpretation: dict[str, Any],
        result: dict[str, Any],
        setup_score: int,
        financial_score: int,
    ) -> None:
        if db is None:
            return
        track_event(
            db=db,
            event_name="DOMAIN_ROUTED",
            duration_ms=round((perf_counter() - start) * 1000, 3),
            payload={
                **result,
                "stage": "ROUTER",
                "input_snapshot": raw_user_text,
                "output_snapshot": result,
                "detected_domain": interpretation.get("intent"),
                "final_domain": result.get("domain"),
                "llm_decision": {
                    "intent": interpretation.get("intent"),
                    "action": interpretation.get("action") or interpretation.get("semantic_action"),
                    "confidence": interpretation.get("confidence"),
                    "reasoning_summary": interpretation.get("reasoning_summary"),
                },
                "confidence": result.get("confidence"),
                "reasoning_summary": _route_reasoning(result, setup_score, financial_score),
                "metadata": {
                    "setup_score": setup_score,
                    "financial_score": financial_score,
                    "required_schema": result.get("required_schema"),
                    "ui_mode": result.get("ui_mode"),
                },
            },
        )

    def _setup_score(self, text: str, interpretation: dict[str, Any]) -> int:
        score = 0
        action = str(interpretation.get("action") or interpretation.get("semantic_action") or "").upper()
        intent = str(interpretation.get("intent") or "").upper()
        if action in self._SETUP_ACTIONS or intent in {"SETUP", "SET_ROLE", "ROLE_ASSIGNMENT", "PROFILE_UPDATE"}:
            score += 2
        if any(pattern in text for pattern in self._SETUP_PATTERNS):
            score += 1
        entities = interpretation.get("entities")
        if isinstance(entities, list):
            for entity in entities:
                if not isinstance(entity, dict):
                    continue
                field_updates = entity.get("field_updates")
                if (
                    (isinstance(field_updates, dict) and _field_updates_has_profile_keys(field_updates))
                    or entity.get("phone")
                    or entity.get("account_number")
                    or entity.get("daily_rate")
                ):
                    score += 2
                    break
        return score

    def _financial_score(self, text: str, interpretation: dict[str, Any]) -> int:
        score = 0
        action = str(interpretation.get("action") or interpretation.get("semantic_action") or "").upper()
        intent = str(interpretation.get("intent") or "").upper()
        if action in self._FINANCIAL_ACTIONS or intent in {"FINANCIAL", "PAYMENT", "PURCHASE"}:
            score += 2
        financial = interpretation.get("financial")
        if isinstance(financial, dict) and financial.get("amount") is not None:
            score += 2
        if any(pattern in text for pattern in self._FINANCIAL_PATTERNS):
            score += 1
        if (
            score > 0
            and re.search(r"\d|[۰-۹]", text)
            and any(unit in text for unit in ("میلیون", "تومان", "تومن", "هزار"))
        ):
            score += 1
        return score

    def _has_profile_update_fields(self, interpretation: dict[str, Any]) -> bool:
        for entity in (interpretation.get("entities") or interpretation.get("extracted_entities") or []):
            if not isinstance(entity, dict):
                continue
            field_updates = entity.get("field_updates")
            if isinstance(field_updates, dict) and _field_updates_has_profile_keys(field_updates):
                return True
            if any(
                entity.get(key) not in (None, "")
                for key in ("phone", "account_number", "card_number", "daily_rate", "notes")
            ):
                return True
        return False

    def _has_financial_intent(self, interpretation: dict[str, Any]) -> bool:
        action = str(interpretation.get("action") or interpretation.get("semantic_action") or "").upper()
        intent = str(interpretation.get("intent") or "").upper()
        if action in self._FINANCIAL_ACTIONS or intent in {"FINANCIAL", "PAYMENT", "PURCHASE"}:
            return True
        financial = interpretation.get("financial")
        return isinstance(financial, dict) and financial.get("amount") is not None

    def _has_work_intent(self, interpretation: dict[str, Any]) -> bool:
        action = str(interpretation.get("action") or interpretation.get("semantic_action") or "").upper()
        intent = str(interpretation.get("intent") or "").upper()
        event_type = str(
            interpretation.get("canonical_event_type")
            or interpretation.get("event_type")
            or interpretation.get("type")
            or ""
        ).upper()
        if action in {"WORK", "WORK_LOG", "DAILY_WORK", "REGISTER_WORK_LOG"}:
            return True
        if intent in {"WORK", "WORK_EVENT", "TASK"} or event_type == "WORK_EVENT":
            return True
        work = interpretation.get("work")
        return isinstance(work, dict) and work.get("quantity") is not None

    def _has_task_execution_text(self, text: str) -> bool:
        has_action = any(pattern in text for pattern in self._TASK_ACTION_PATTERNS)
        if has_action:
            return True
        return any(pattern in text for pattern in self._TIME_HINT_PATTERNS) and any(
            term in text for term in ("کار", "نخاله", "جمع", "جوش", "کمک", "بیاد")
        )

    def _has_explicit_setup_declaration(self, text: str) -> bool:
        declaration_terms = (
            "کارفرمای پروژه است",
            "کارفرما است",
            "کارگر پروژه است",
            "به پروژه اضافه",
            "اضافه",
            "اضافه شد",
            "به عنوان",
            "نقش",
            "تخصیص داده شد",
            "شماره تماس",
            "شماره موبایل",
            "شماره حساب",
            "دستمزد روزانه",
        )
        return any(term in text for term in declaration_terms)

    def _result(self, domain: DomainType, confidence: float) -> dict[str, Any]:
        if domain == DomainType.ENTITY_UPDATE:
            return {
                "domain": domain.value,
                "confidence": confidence,
                "required_schema": self.ENTITY_UPDATE_SCHEMA,
                "ui_mode": self.ENTITY_UPDATE_UI,
            }
        if domain == DomainType.FINANCIAL:
            return {
                "domain": domain.value,
                "confidence": confidence,
                "required_schema": self.FINANCIAL_SCHEMA,
                "ui_mode": self.FINANCIAL_UI,
            }
        if domain == DomainType.TASK:
            return {
                "domain": domain.value,
                "confidence": confidence,
                "required_schema": self.TASK_SCHEMA,
                "ui_mode": self.TASK_UI,
            }
        if domain == DomainType.WORK:
            return {
                "domain": domain.value,
                "confidence": confidence,
                "required_schema": self.WORK_SCHEMA,
                "ui_mode": self.WORK_UI,
            }
        if domain == DomainType.MIXED:
            return {
                "domain": domain.value,
                "confidence": confidence,
                "required_schema": self.MIXED_SCHEMA,
                "ui_mode": self.MIXED_UI,
            }
        if domain == DomainType.NOTE:
            return {
                "domain": domain.value,
                "confidence": confidence,
                "required_schema": "note_confirmation",
                "ui_mode": "NoteFallback",
            }
        return {
            "domain": domain.value,
            "confidence": confidence,
            "required_schema": self.SETUP_SCHEMA,
            "ui_mode": self.SETUP_UI,
        }

    def _normalize(self, text: str) -> str:
        return " ".join((text or "").replace("\u200c", " ").replace("ي", "ی").replace("ك", "ک").lower().split())


def _route_reasoning(result: dict[str, Any], setup_score: int, financial_score: int) -> str:
    return (
        f"Selected {result.get('domain')} with setup_score={setup_score} "
        f"and financial_score={financial_score}."
    )
