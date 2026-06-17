import os
import re
from dataclasses import dataclass, field, replace
from decimal import Decimal
from enum import StrEnum
from typing import Any

from app.core.semantic_rules.conflict_detector import ConflictDetectorService
from app.core.semantic_rules.explainability import RuleTrace, SemanticExplainabilityService
from app.models.core import Worker
from app.services.persian_money_engine import normalize_text
from app.services.persian_role_extractor import PersianRoleExtractor


class CanonicalEventType(StrEnum):
    SETUP = "SETUP_EVENT"
    WORK = "WORK_EVENT"
    FINANCIAL = "FINANCIAL_EVENT"
    NOTE = "NOTE_EVENT"


@dataclass(frozen=True)
class CanonicalEvent:
    type: CanonicalEventType
    entity_id: int | None
    entity_name: str | None
    action: str
    delta: Decimal | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuleValidationResult:
    valid: bool
    reason: str
    expected_type: CanonicalEventType | None = None


EVENT_RULES: dict[str, dict[str, Any]] = {
    "SETUP_EVENT": {
        "rule_id": "SETUP_RULE_01",
        "event_type": "SETUP_EVENT",
        "triggers": {
            "keywords": [
                "کارفرما",
                "کارگر",
                "کارگرها",
                "کارگرهای پروژه",
                "کارگر ساده",
                "به عنوان کارگر ساده",
                "فروشنده",
                "پیمانکار",
                "جوشکار",
                "برقکار",
                "پروژه",
                "شماره",
                "تماس",
                "حساب",
                "کارت",
                "شبا",
            ],
            "patterns": ["role_declaration", "entity_update"],
        },
        "actions": {
            "ENTITY_UPDATE": ["شماره", "تماس", "حساب", "کارت", "شبا"],
            "SETUP": [],
        },
        "declarations": ["است", "هست", "هستند"],
        "validation": {"requires_entity": False, "forbidden_fallback": ["NOTE_EVENT"]},
        "allowed_contexts": ["entity_declaration", "entity_update", "role_assignment"],
        "forbidden_contexts": ["financial"],
        "priority": 1,
        "fallback": "NOTE_EVENT",
    },
    "FINANCIAL_EVENT": {
        "rule_id": "FINANCIAL_RULE_01",
        "event_type": "FINANCIAL_EVENT",
        "triggers": {
            "keywords": [
                "دادم",
                "پرداخت",
                "خرید",
                "خرید کردم",
                "فاکتور",
                "بدهی",
                "حساب شد",
                "نسیه",
                "چک",
                "تسویه",
                "گرفتم",
                "واریز",
                "پول",
                "میلیون",
                "ملیون",
                "تومان",
            ],
            "patterns": ["money", "cash_movement", "settlement"],
        },
        "actions": {
            "PURCHASE_PAID": ["خرید", "خرید کردم"],
            "DEBT_CREATED": ["فاکتور", "بدهی", "حساب شد", "نسیه", "ندادم"],
            "CHECK_PAYMENT": ["چک"],
            "DEFERRED_PAYMENT": ["تاریخ", "ماه دیگه", "برای"],
            "PAYMENT": ["دادم", "پرداخت", "واریز", "تسویه"],
        },
        "validation": {"requires_entity": False, "forbidden_fallback": ["NOTE_EVENT"]},
        "allowed_contexts": ["financial"],
        "forbidden_contexts": ["work"],
        "priority": 2,
        "fallback": "NOTE_EVENT",
    },
    "WORK_EVENT": {
        "rule_id": "WORK_RULE_01",
        "event_type": "WORK_EVENT",
        "triggers": {
            "keywords": [
                "کار کرد",
                "جوش داد",
                "جوش زد",
                "اومد سر کار",
                "آمد سر کار",
                "کارکرد",
                "روز کار",
                "متر",
            ],
            "patterns": ["work_progress", "implicit_work"],
            "implicit_context": ["امروز", "دیروز", "سر کار", "کار"],
        },
        "validation": {"requires_entity": True, "forbidden_fallback": ["NOTE_EVENT"]},
        "allowed_contexts": ["work"],
        "forbidden_contexts": ["financial"],
        "priority": 3,
        "fallback": "NOTE_EVENT",
    },
    "NOTE_EVENT": {
        "rule_id": "NOTE_RULE_01",
        "event_type": "NOTE_EVENT",
        "triggers": {"keywords": [], "patterns": ["no_action"]},
        "validation": {"requires_entity": False, "forbidden_fallback": []},
        "allowed_contexts": ["ambiguous"],
        "forbidden_contexts": ["entity_exists", "financial", "work", "setup"],
        "priority": 4,
        "fallback": None,
    },
}


class SemanticRuleEngine:
    """
    DEPRECATED: Will be removed after full LLM migration.
    Kept for backward compatibility only.
    """

    def __init__(
        self,
        explainability: SemanticExplainabilityService | None = None,
        conflict_detector: ConflictDetectorService | None = None,
    ) -> None:
        self.explainability = explainability or SemanticExplainabilityService()
        self.conflict_detector = conflict_detector or ConflictDetectorService()
        self.role_extractor = PersianRoleExtractor()

    def classify(
        self,
        llm_output: dict[str, Any],
        text: str,
        context: list[Worker],
    ) -> CanonicalEvent:
        static_conflict_report = self.conflict_detector.validate_or_raise(EVENT_RULES)
        normalized = self._normalize(text)
        entity = self.resolve_entity(llm_output, text, context)
        rule_traces = self._matching_rule_traces(normalized, entity, llm_output)
        event_type = self.resolve_conflicts(
            [CanonicalEventType(trace.event_type) for trace in rule_traces]
        )
        confidence = self._confidence(llm_output)
        action = self.action_for(event_type, normalized)
        delta = Decimal("1") if event_type == CanonicalEventType.WORK else None
        rejected_rules = self._rejected_rules(
            normalized,
            [trace.event_type for trace in rule_traces],
        )
        explanation = self.explainability.explain(
            event_type=event_type.value,
            confidence=confidence,
            rule_traces=rule_traces,
            rejected_rules=rejected_rules,
            semantic_action=action,
            reasoning_notes=self._reasoning_notes(event_type, action, normalized),
        )
        runtime_conflict_report = self.conflict_detector.audit_text(
            text,
            [
                {
                    "rule_id": trace.rule_id,
                    "event_type": trace.event_type,
                    "confidence": trace.confidence,
                }
                for trace in rule_traces
            ],
        )
        conflict_warnings = [
            *static_conflict_report["conflicts"],
            *runtime_conflict_report["conflicts"],
        ]
        metadata = self.explainability.attach_to_event_metadata(
            {"confidence": confidence, "source_text": text},
            explanation,
            conflict_warnings,
        )
        if os.environ.get("YARA_DEBUG_SEMANTICS") == "1":
            self._print_debug(rule_traces, explanation, conflict_warnings)

        return CanonicalEvent(
            type=event_type,
            entity_id=entity.id if entity is not None else None,
            entity_name=entity.name if entity is not None else self._llm_entity_name(llm_output),
            action=action,
            delta=delta,
            metadata=metadata,
        )

    def validate(
        self,
        event: CanonicalEvent,
        text: str,
        context: list[Worker],
        llm_output: dict[str, Any] | None = None,
    ) -> RuleValidationResult:
        entity = self.resolve_entity(llm_output or {}, text, context)
        normalized = self._normalize(text)
        expected_type = self.resolve_conflicts(self._matching_event_types(normalized, entity))
        if "semantic_explanation" not in event.metadata:
            return RuleValidationResult(
                False,
                "semantic explanation metadata missing",
                expected_type,
            )
        if event.type != expected_type:
            return RuleValidationResult(
                False,
                "semantic event does not match rule engine",
                expected_type,
            )
        if event.type == CanonicalEventType.NOTE and not self.note_allowed(text, context):
            return RuleValidationResult(
                False,
                "NOTE_EVENT blocked by semantic rules",
                expected_type,
            )
        return RuleValidationResult(True, "semantic event accepted", expected_type)

    def resolve_conflicts(self, event_types: list[CanonicalEventType]) -> CanonicalEventType:
        if not event_types:
            return CanonicalEventType.NOTE
        return min(event_types, key=lambda item: EVENT_RULES[item.value]["priority"])

    def reclassify(
        self,
        event: CanonicalEvent,
        event_type: CanonicalEventType,
        text: str,
        context: list[Worker],
        llm_output: dict[str, Any] | None = None,
    ) -> CanonicalEvent:
        entity = self.resolve_entity(llm_output or {}, text, context)
        normalized = self._normalize(text)
        confidence = self._confidence(llm_output or {})
        rule_traces = self._matching_rule_traces(normalized, entity, llm_output or {})
        action = self.action_for(event_type, normalized)
        explanation = self.explainability.explain(
            event_type=event_type.value,
            confidence=confidence,
            rule_traces=rule_traces,
            rejected_rules=self._rejected_rules(
                normalized,
                [trace.event_type for trace in rule_traces],
            ),
            semantic_action=action,
            reasoning_notes=self._reasoning_notes(
                event_type,
                action,
                normalized,
            ),
        )
        conflict_report = self.conflict_detector.audit_text(
            text,
            [
                {
                    "rule_id": trace.rule_id,
                    "event_type": trace.event_type,
                    "confidence": trace.confidence,
                }
                for trace in rule_traces
            ],
        )
        return replace(
            event,
            type=event_type,
            entity_id=entity.id if entity is not None else event.entity_id,
            entity_name=entity.name if entity is not None else event.entity_name,
            action=action,
            delta=Decimal("1") if event_type == CanonicalEventType.WORK else None,
            metadata=self.explainability.attach_to_event_metadata(
                event.metadata,
                explanation,
                conflict_report["conflicts"],
            ),
        )

    def action_for(self, event_type: CanonicalEventType, normalized_text: str) -> str:
        if event_type == CanonicalEventType.SETUP:
            return "ENTITY_UPDATE" if self.has_entity_update_meaning(normalized_text) else "SETUP"
        if event_type == CanonicalEventType.FINANCIAL:
            if self.has_check_payment_meaning(normalized_text):
                return "CHECK_PAYMENT"
            if self.has_debt_meaning(normalized_text):
                return "DEBT_CREATED"
            if self.has_paid_purchase_meaning(normalized_text):
                return "PURCHASE_PAID"
            return "PAYMENT"
        if event_type == CanonicalEventType.WORK:
            return "INCREMENT"
        return "NOTE"

    def note_allowed(self, text: str, context: list[Worker]) -> bool:
        normalized = self._normalize(text)
        entity = self.resolve_entity({}, text, context)
        matches = self._matching_event_types(normalized, entity)
        return entity is None and not matches

    def resolve_entity(
        self,
        llm_output: dict[str, Any],
        text: str,
        context: list[Worker],
    ) -> Worker | None:
        # First, try deterministic role-phrase extraction
        extracted_role = self.role_extractor.extract(text)
        if extracted_role:
            # Match by exact name first
            for entity in context:
                if self._normalize(entity.name) == self._normalize(extracted_role.name):
                    return entity
            # If no exact match and this is a CLIENT role phrase, match any CLIENT
            if extracted_role.worker_type.value == "CLIENT":
                for entity in context:
                    if entity.type.value == "CLIENT":
                        return entity
        
        # Fallback to existing logic
        normalized_text = self._normalize(text)
        if "کارفرما" in normalized_text:
            for entity in context:
                if entity.type.value == "CLIENT":
                    return entity
        candidates = self._entity_names(llm_output)
        for entity in context:
            normalized_name = self._normalize(entity.name)
            if any(self._normalize(candidate) == normalized_name for candidate in candidates):
                return entity
            if normalized_name and normalized_name in normalized_text:
                return entity
            name_parts = normalized_name.split()
            if name_parts and name_parts[-1] in normalized_text:
                return entity
        return None

    def has_entity_update_meaning(self, normalized_text: str) -> bool:
        return self._contains_any(
            normalized_text,
            set(EVENT_RULES[CanonicalEventType.SETUP.value]["actions"]["ENTITY_UPDATE"]),
        )

    def has_invoice_meaning(self, normalized_text: str) -> bool:
        return self.has_debt_meaning(normalized_text)

    def has_debt_meaning(self, normalized_text: str) -> bool:
        return self._contains_any(
            normalized_text,
            set(EVENT_RULES[CanonicalEventType.FINANCIAL.value]["actions"]["DEBT_CREATED"]),
        ) or self._contains_phrase(normalized_text, ["پرداخت نکردم", "هنوز ندادم", "پولش را ندادم"])

    def has_check_payment_meaning(self, normalized_text: str) -> bool:
        return "چک" in normalized_text

    def has_paid_purchase_meaning(self, normalized_text: str) -> bool:
        return self._has_purchase_meaning(normalized_text) and self._has_money_amount(
            normalized_text
        )

    def _matching_event_types(
        self,
        normalized_text: str,
        entity: Worker | None,
    ) -> list[CanonicalEventType]:
        matches: list[CanonicalEventType] = []
        if self._has_setup_meaning(normalized_text):
            matches.append(CanonicalEventType.SETUP)
        if self._has_financial_meaning(normalized_text):
            matches.append(CanonicalEventType.FINANCIAL)
        if self._has_work_meaning(normalized_text):
            matches.append(CanonicalEventType.WORK)
        if entity is not None:
            if self.has_entity_update_meaning(normalized_text):
                matches.append(CanonicalEventType.SETUP)
            if self._has_implicit_work_context(normalized_text):
                matches.append(CanonicalEventType.WORK)
        return matches

    def _matching_rule_traces(
        self,
        normalized_text: str,
        entity: Worker | None,
        llm_output: dict[str, Any],
    ) -> list[RuleTrace]:
        traces: list[RuleTrace] = []
        confidence = self._confidence(llm_output)
        for event_type in self._matching_event_types(normalized_text, entity):
            rule = EVENT_RULES[event_type.value]
            signals = self._matched_signals(normalized_text, event_type, entity)
            traces.append(
                RuleTrace(
                    rule_id=rule["rule_id"],
                    event_type=event_type.value,
                    priority=rule["priority"],
                    matched_signals=signals,
                    confidence=confidence,
                )
            )
        return traces

    def _matched_signals(
        self,
        normalized_text: str,
        event_type: CanonicalEventType,
        entity: Worker | None,
    ) -> list[str]:
        rule = EVENT_RULES[event_type.value]
        signals = [
            keyword
            for keyword in rule.get("triggers", {}).get("keywords", [])
            if keyword in normalized_text
        ]
        if event_type == CanonicalEventType.SETUP:
            signals.extend(
                declaration
                for declaration in rule.get("declarations", [])
                if declaration in normalized_text
            )
        if event_type == CanonicalEventType.WORK and entity is not None:
            signals.extend(
                keyword
                for keyword in rule.get("triggers", {}).get("implicit_context", [])
                if keyword in normalized_text
            )
        return list(dict.fromkeys(signals))

    def _rejected_rules(
        self,
        normalized_text: str,
        matched_event_types: list[str],
    ) -> list[dict[str, str]]:
        rejected: list[dict[str, str]] = []
        for event_type, rule in EVENT_RULES.items():
            if event_type == CanonicalEventType.NOTE.value or event_type in matched_event_types:
                continue
            keywords = rule.get("triggers", {}).get("keywords", [])
            if not any(keyword in normalized_text for keyword in keywords):
                reason = f"no {event_type.lower().replace('_event', '')} keywords detected"
            else:
                reason = "rule conditions not satisfied"
            rejected.append({"rule": rule["rule_id"], "reason": reason})
        return rejected

    def _print_debug(
        self,
        rule_traces: list[RuleTrace],
        explanation: dict[str, Any],
        conflict_warnings: list[dict[str, Any]],
    ) -> None:
        print("[SEMANTICS] rule matches:", [trace.__dict__ for trace in rule_traces])
        print("[SEMANTICS] decision path:", explanation["decision_path"])
        print("[SEMANTICS] conflicts detected:", conflict_warnings)
        print("[SEMANTICS] explainability output:", explanation)

    def _has_setup_meaning(self, normalized_text: str) -> bool:
        rule = EVENT_RULES[CanonicalEventType.SETUP.value]
        if self._contains_phrase(
            normalized_text,
            [
                "به عنوان کارگر ساده",
                "کارگر ساده",
                "کارگرهای پروژه",
                "در پروژه کار میکنند",
                "در پروژه کار می کنند",
                "در پروژه کار می‌کنند",
            ],
        ):
            return True
        return self._contains_any(
            normalized_text,
            set(rule["triggers"]["keywords"]),
        ) and self._contains_any(normalized_text, set(rule["declarations"]))

    def _has_financial_meaning(self, normalized_text: str) -> bool:
        if self._contains_any(normalized_text, {"تسویه"}):
            return True
        has_money = self._has_money_amount(normalized_text)
        if not has_money:
            return False
        return self._contains_any(
            normalized_text,
            {
                "دادم",
                "پرداخت",
                "خرید",
                "فاکتور",
                "بدهی",
                "حساب شد",
                "نسیه",
                "چک",
                "واریز",
                "پول",
            },
        )

    def _has_work_meaning(self, normalized_text: str) -> bool:
        if self._has_setup_meaning(normalized_text):
            return False
        if self._has_purchase_meaning(normalized_text) and not self._has_money_amount(
            normalized_text
        ):
            work_keywords = set(EVENT_RULES[CanonicalEventType.WORK.value]["triggers"]["keywords"])
            return self._contains_any(normalized_text, work_keywords - {"متر"})
        return self._contains_any(
            normalized_text,
            set(EVENT_RULES[CanonicalEventType.WORK.value]["triggers"]["keywords"]),
        )

    def _has_implicit_work_context(self, normalized_text: str) -> bool:
        return self._contains_any(
            normalized_text,
            set(EVENT_RULES[CanonicalEventType.WORK.value]["triggers"]["implicit_context"]),
        )

    def _contains_any(self, normalized_text: str, keywords: set[str]) -> bool:
        return any(keyword in normalized_text for keyword in keywords)

    def _contains_phrase(self, normalized_text: str, phrases: list[str]) -> bool:
        return any(phrase in normalized_text for phrase in phrases)

    def _has_purchase_meaning(self, normalized_text: str) -> bool:
        return self._contains_phrase(normalized_text, ["خرید", "خریدم", "خرید کردم"])

    def _has_money_amount(self, normalized_text: str) -> bool:
        return bool(
            re.search(
                r"\d+(?:\.\d+)?\s*(میلیون|میلیونی|میلیارد|میلیاردی|هزار|تومان)",
                normalized_text,
            )
        )

    def _reasoning_notes(
        self,
        event_type: CanonicalEventType,
        action: str,
        normalized_text: str,
    ) -> list[str]:
        if event_type != CanonicalEventType.FINANCIAL:
            return []
        if action == "PURCHASE_PAID":
            return ["money amount + purchase phrase implies paid purchase by default"]
        if action in {"DEBT_CREATED", "CHECK_PAYMENT", "DEFERRED_PAYMENT"}:
            return ["unpaid/debt/check terms override paid purchase"]
        if self._has_purchase_meaning(normalized_text) and not self._has_money_amount(
            normalized_text
        ):
            return ["purchase phrase without money amount is not treated as payment or debt"]
        return []

    def _entity_names(self, llm_output: dict[str, Any]) -> list[str]:
        names: list[str] = []
        entity = llm_output.get("entity")
        if isinstance(entity, str) and entity.strip():
            names.append(entity.strip())
        raw_entity = llm_output.get("raw_entity")
        if isinstance(raw_entity, str) and raw_entity.strip():
            names.append(raw_entity.strip())
        entities = llm_output.get("entities")
        if isinstance(entities, list):
            for item in entities:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    names.append(item["name"].strip())
        return names

    def _llm_entity_name(self, llm_output: dict[str, Any]) -> str | None:
        names = self._entity_names(llm_output)
        return names[0] if names else None

    def _confidence(self, llm_output: dict[str, Any]) -> float:
        confidence = llm_output.get("confidence")
        if isinstance(confidence, int | float) and not isinstance(confidence, bool):
            return max(0.0, min(float(confidence), 1.0))
        return 0.3

    def _normalize(self, value: str) -> str:
        return normalize_text(value).replace("\u200c", " ").strip()
