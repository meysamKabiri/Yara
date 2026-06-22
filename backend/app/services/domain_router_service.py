from __future__ import annotations

import re
from enum import StrEnum
from time import perf_counter
from typing import Any

from app.core.trace_events import TraceEvent, trace_event


class DomainType(StrEnum):
    SETUP = "SETUP"
    FINANCIAL = "FINANCIAL"
    MIXED = "MIXED"


class DomainRouterService:
    """Route interpreted user input to one product domain.

    This layer does not execute business behavior. It only chooses the UI schema
    and backend domain pipeline that should handle an already interpreted input.
    """

    SETUP_SCHEMA = "setup_confirmation"
    FINANCIAL_SCHEMA = "financial_confirmation"
    MIXED_SCHEMA = "split_confirmation"

    SETUP_UI = "SetupModal"
    FINANCIAL_UI = "FinancialModal"
    MIXED_UI = "SplitFlow"

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

    def route(self, raw_user_text: str, llm_interpretation: dict[str, Any] | None = None) -> dict[str, Any]:
        start = perf_counter()
        text = self._normalize(raw_user_text)
        interpretation = llm_interpretation or {}
        setup_score = self._setup_score(text, interpretation)
        financial_score = self._financial_score(text, interpretation)

        if setup_score > 0 and financial_score > 0:
            result = self._result(DomainType.MIXED, 0.9)
            trace_event(TraceEvent.DOMAIN_ROUTED, result, start_time=start)
            return result
        if financial_score > 0:
            result = self._result(DomainType.FINANCIAL, min(0.95, 0.75 + financial_score * 0.05))
            trace_event(TraceEvent.DOMAIN_ROUTED, result, start_time=start)
            return result
        result = self._result(DomainType.SETUP, min(0.95, 0.75 + max(setup_score, 1) * 0.05))
        trace_event(TraceEvent.DOMAIN_ROUTED, result, start_time=start)
        return result

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
                if isinstance(entity, dict) and (
                    entity.get("field_updates")
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

    def _result(self, domain: DomainType, confidence: float) -> dict[str, Any]:
        if domain == DomainType.FINANCIAL:
            return {
                "domain": domain.value,
                "confidence": confidence,
                "required_schema": self.FINANCIAL_SCHEMA,
                "ui_mode": self.FINANCIAL_UI,
            }
        if domain == DomainType.MIXED:
            return {
                "domain": domain.value,
                "confidence": confidence,
                "required_schema": self.MIXED_SCHEMA,
                "ui_mode": self.MIXED_UI,
            }
        return {
            "domain": domain.value,
            "confidence": confidence,
            "required_schema": self.SETUP_SCHEMA,
            "ui_mode": self.SETUP_UI,
        }

    def _normalize(self, text: str) -> str:
        return " ".join((text or "").replace("\u200c", " ").lower().split())
