from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import ShadowInterpretationLog
from app.services.compare_legacy_vs_shadow import compare_legacy_vs_shadow
from app.services.persian_money_engine import normalize_text
from app.services.shadow_conflict_analyzer import analyze_shadow_conflict

SHADOW_SCORE_WEIGHTS = {
    "intent": 0.30,
    "entity": 0.30,
    "financial": 0.25,
    "work": 0.15,
}
INTENT_CATEGORIES = ["FINANCIAL", "SETUP", "WORK", "NOTE"]
HIGH_CONFIDENCE_THRESHOLD = 0.8


class ShadowAnalyticsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def summary(self) -> dict[str, Any]:
        rows = self._records()
        total = len(rows)
        if total == 0:
            return _empty_summary()

        metrics = [self._entry_metrics(row) for row in rows]
        accuracy = {
            "intent": _ratio(metrics, "intent_accuracy"),
            "entity": _ratio(metrics, "entity_accuracy"),
            "financial": _ratio(metrics, "financial_accuracy"),
            "work": _ratio(metrics, "work_accuracy"),
        }
        category_breakdown = self.category_breakdown(metrics)
        return {
            "total_samples": total,
            "accuracy": accuracy,
            "summary": self._win_summary(metrics),
            "confidence_analysis": self._confidence_analysis(metrics),
            "category_breakdown": category_breakdown,
            "overall_shadow_score": _overall_shadow_score(accuracy),
        }

    def conflicts(self) -> list[dict[str, Any]]:
        conflicts: list[dict[str, Any]] = []
        for row in self._records():
            metrics = self._entry_metrics(row)
            if metrics["all_match"]:
                continue
            conflicts.append(
                {
                    "id": row.id,
                    "project_id": row.project_id,
                    "input_text": row.input_text,
                    "diff_json": metrics["diff"],
                    "legacy_json": row.legacy_json,
                    "shadow_json": row.shadow_json,
                    "conflict_types": analyze_shadow_conflict(
                        row.legacy_json,
                        row.shadow_json,
                        metrics["diff"],
                    ),
                }
            )
        return conflicts

    def category_breakdown(
        self,
        metrics: list[dict[str, Any]] | None = None,
    ) -> dict[str, dict[str, int]]:
        rows = (
            metrics
            if metrics is not None
            else [self._entry_metrics(row) for row in self._records()]
        )
        breakdown = {
            category: {"shadow_better": 0, "legacy_better": 0, "ties": 0}
            for category in INTENT_CATEGORIES
        }
        for item in rows:
            category = item["category"]
            if category not in breakdown:
                breakdown[category] = {"shadow_better": 0, "legacy_better": 0, "ties": 0}
            if item["winner"] == "shadow":
                breakdown[category]["shadow_better"] += 1
            elif item["winner"] == "legacy":
                breakdown[category]["legacy_better"] += 1
            else:
                breakdown[category]["ties"] += 1
        return breakdown

    def _records(self) -> list[ShadowInterpretationLog]:
        return list(
            self.db.scalars(
                select(ShadowInterpretationLog).order_by(ShadowInterpretationLog.created_at)
            )
        )

    def _entry_metrics(self, row: ShadowInterpretationLog) -> dict[str, Any]:
        legacy = _first_legacy_item(row.legacy_json)
        shadow = row.shadow_json if isinstance(row.shadow_json, dict) else {}
        diff = _complete_diff(row.diff_json, row.legacy_json, shadow)
        intent_accuracy = bool(diff["intent_match"])
        entity_accuracy = bool(diff["entity_match"])
        amount_accuracy = bool(diff["amount_match"])
        direction_accuracy = bool(diff["direction_match"])
        financial_accuracy = amount_accuracy and direction_accuracy
        work_accuracy = _work_matches(legacy, shadow)
        all_match = intent_accuracy and entity_accuracy and financial_accuracy and work_accuracy

        return {
            "intent_accuracy": intent_accuracy,
            "entity_accuracy": entity_accuracy,
            "financial_accuracy": financial_accuracy,
            "work_accuracy": work_accuracy,
            "all_match": all_match,
            "diff": {
                **diff,
                "financial_match": financial_accuracy,
                "work_match": work_accuracy,
            },
            "winner": _winner(legacy, shadow, all_match),
            "category": _category(legacy, shadow),
            "legacy_confidence": _confidence(legacy),
            "shadow_confidence": _confidence(shadow),
        }

    def _win_summary(self, metrics: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "legacy_wins": sum(1 for item in metrics if item["winner"] == "legacy"),
            "shadow_wins": sum(1 for item in metrics if item["winner"] == "shadow"),
            "ties": sum(1 for item in metrics if item["winner"] == "tie"),
        }

    def _confidence_analysis(self, metrics: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "high_confidence_wrong_shadow": sum(
                1
                for item in metrics
                if not item["all_match"] and item["shadow_confidence"] >= HIGH_CONFIDENCE_THRESHOLD
            ),
            "high_confidence_wrong_legacy": sum(
                1
                for item in metrics
                if not item["all_match"] and item["legacy_confidence"] >= HIGH_CONFIDENCE_THRESHOLD
            ),
        }


def _empty_summary() -> dict[str, Any]:
    accuracy = {"intent": 0.0, "entity": 0.0, "financial": 0.0, "work": 0.0}
    return {
        "total_samples": 0,
        "accuracy": accuracy,
        "summary": {"legacy_wins": 0, "shadow_wins": 0, "ties": 0},
        "confidence_analysis": {
            "high_confidence_wrong_shadow": 0,
            "high_confidence_wrong_legacy": 0,
        },
        "category_breakdown": {
            category: {"shadow_better": 0, "legacy_better": 0, "ties": 0}
            for category in INTENT_CATEGORIES
        },
        "overall_shadow_score": 0.0,
    }


def _ratio(metrics: list[dict[str, Any]], key: str) -> float:
    if not metrics:
        return 0.0
    return sum(1 for item in metrics if item[key]) / len(metrics)


def _overall_shadow_score(accuracy: dict[str, float]) -> float:
    return sum(accuracy[key] * weight for key, weight in SHADOW_SCORE_WEIGHTS.items())


def _complete_diff(
    diff_json: Any,
    legacy_json: dict[str, Any] | list[dict[str, Any]],
    shadow_json: dict[str, Any],
) -> dict[str, bool]:
    computed = compare_legacy_vs_shadow(legacy_json, shadow_json)
    if not isinstance(diff_json, dict):
        return computed
    return {
        "intent_match": bool(diff_json.get("intent_match", computed["intent_match"])),
        "entity_match": bool(diff_json.get("entity_match", computed["entity_match"])),
        "amount_match": bool(diff_json.get("amount_match", computed["amount_match"])),
        "direction_match": bool(diff_json.get("direction_match", computed["direction_match"])),
    }


def _first_legacy_item(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        return value[0] if value and isinstance(value[0], dict) else {}
    if isinstance(value, dict) and isinstance(value.get("interpretations"), list):
        interpretations = value["interpretations"]
        if interpretations and isinstance(interpretations[0], dict):
            return interpretations[0]
        return {}
    return value if isinstance(value, dict) else {}


def _work_matches(legacy: dict[str, Any], shadow: dict[str, Any]) -> bool:
    shadow_work = shadow.get("work") if isinstance(shadow.get("work"), dict) else {}
    return _number(legacy.get("extracted_quantity") or legacy.get("quantity")) == _number(
        shadow_work.get("quantity")
    ) and _unit(legacy) == _unit(shadow_work)


def _winner(legacy: dict[str, Any], shadow: dict[str, Any], all_match: bool) -> str:
    if all_match:
        return "tie"
    legacy_presence = _presence_score(legacy, is_shadow=False)
    shadow_presence = _presence_score(shadow, is_shadow=True)
    if shadow_presence > legacy_presence:
        return "shadow"
    if legacy_presence > shadow_presence:
        return "legacy"
    return "tie"


def _presence_score(value: dict[str, Any], *, is_shadow: bool) -> int:
    if is_shadow:
        financial = value.get("financial") if isinstance(value.get("financial"), dict) else {}
        work = value.get("work") if isinstance(value.get("work"), dict) else {}
        return sum(
            [
                _intent(value) is not None,
                bool(_entity_names(value)),
                financial.get("amount") is not None,
                financial.get("direction") in {"IN", "OUT"},
                work.get("quantity") is not None,
                work.get("unit") is not None,
            ]
        )
    return sum(
        [
            _intent(value) is not None,
            bool(_entity_names(value)),
            value.get("extracted_amount") is not None,
            value.get("financial_direction") is not None,
            value.get("extracted_quantity") is not None,
            value.get("unit") is not None,
        ]
    )


def _category(legacy: dict[str, Any], shadow: dict[str, Any]) -> str:
    return _intent(legacy) or _intent(shadow) or "NOTE"


def _intent(value: dict[str, Any]) -> str | None:
    raw_intent = value.get("canonical_event_type") or value.get("intent") or value.get("type")
    mapping = {
        "SETUP_EVENT": "SETUP",
        "WORK_EVENT": "WORK",
        "FINANCIAL_EVENT": "FINANCIAL",
        "NOTE_EVENT": "NOTE",
    }
    if raw_intent is None:
        return None
    return mapping.get(str(raw_intent), str(raw_intent))


def _entity_names(value: dict[str, Any]) -> list[str]:
    entities = value.get("entities") or value.get("extracted_entities") or []
    names: list[str] = []
    if isinstance(entities, list):
        for entity in entities:
            if isinstance(entity, dict) and isinstance(entity.get("name"), str):
                names.append(_normalize_name(entity["name"]))
    return sorted(name for name in names if name)


def _normalize_name(value: str) -> str:
    normalized = normalize_text(value).replace("\u200c", " ").strip()
    return " ".join(normalized.split())


def _number(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _unit(value: dict[str, Any]) -> str | None:
    unit = value.get("unit")
    if unit in {"day", "meter", "item"}:
        return str(unit)
    return None


def _confidence(value: dict[str, Any]) -> float:
    confidence = value.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, int | float):
        return 0.0
    return float(confidence)
