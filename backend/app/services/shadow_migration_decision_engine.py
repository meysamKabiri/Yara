from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import ShadowInterpretationLog
from app.services.shadow_analytics_service import ShadowAnalyticsService
from app.services.shadow_conflict_analyzer import analyze_shadow_conflict

DOMAINS = ["FINANCIAL", "WORK", "SETUP"]
FINAL_MIGRATE_ALL = "MIGRATE_ALL"
FINAL_MIGRATE_FINANCIAL_ONLY = "MIGRATE_FINANCIAL_ONLY"
FINAL_PARTIAL_MIGRATION = "PARTIAL_MIGRATION"
FINAL_DO_NOT_MIGRATE = "DO_NOT_MIGRATE"


class MigrationDecisionEngine:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.analytics = ShadowAnalyticsService(db)

    def recommendation(self) -> dict[str, Any]:
        logs = self._logs()
        if not logs:
            return _empty_recommendation()

        summary = self.analytics.summary()
        domain_metrics = self._domain_metrics(logs)
        conflicts = self._conflicts(logs)
        risk_areas = self._risk_areas(conflicts, len(logs))
        recommended = {
            "FINANCIAL": self._financial_recommendation(domain_metrics["FINANCIAL"], conflicts),
            "WORK": self._work_recommendation(domain_metrics["WORK"], conflicts),
            "SETUP": self._setup_recommendation(domain_metrics["SETUP"], conflicts),
        }
        final = self._final_recommendation(recommended, risk_areas)
        return {
            "overall_migration_readiness": _overall_readiness(recommended),
            "recommended_migrations": recommended,
            "risk_areas": risk_areas,
            "shadow_vs_legacy_summary": self._shadow_vs_legacy_summary(summary),
            "final_recommendation": final,
        }

    def _logs(self) -> list[ShadowInterpretationLog]:
        return list(
            self.db.scalars(
                select(ShadowInterpretationLog).order_by(ShadowInterpretationLog.created_at)
            )
        )

    def _domain_metrics(self, logs: list[ShadowInterpretationLog]) -> dict[str, dict[str, float]]:
        grouped: dict[str, list[ShadowInterpretationLog]] = {domain: [] for domain in DOMAINS}
        for log in logs:
            domain = _domain(log)
            if domain in grouped:
                grouped[domain].append(log)

        return {
            domain: {
                "samples": float(len(rows)),
                "intent_accuracy": _ratio(rows, _intent_matches),
                "entity_accuracy": _ratio(rows, _entity_matches),
                "financial_accuracy": _ratio(rows, _financial_matches),
                "amount_accuracy": _ratio(rows, _amount_matches),
                "direction_accuracy": _ratio(rows, _direction_matches),
                "work_accuracy": _ratio(rows, _work_matches),
            }
            for domain, rows in grouped.items()
        }

    def _conflicts(self, logs: list[ShadowInterpretationLog]) -> dict[str, Counter[str]]:
        conflicts: dict[str, Counter[str]] = {domain: Counter() for domain in DOMAINS}
        for log in logs:
            domain = _domain(log)
            if domain not in conflicts:
                continue
            for conflict_type in analyze_shadow_conflict(
                log.legacy_json,
                log.shadow_json,
                log.diff_json,
            ):
                conflicts[domain][conflict_type] += 1
        return conflicts

    def _financial_recommendation(
        self,
        metrics: dict[str, float],
        conflicts: dict[str, Counter[str]],
    ) -> dict[str, Any]:
        ready = (
            metrics["samples"] > 0
            and metrics["financial_accuracy"] > 0.92
            and metrics["amount_accuracy"] > 0.95
            and metrics["direction_accuracy"] > 0.90
        )
        confidence = _weighted_average(
            [
                (metrics["financial_accuracy"], 0.45),
                (metrics["amount_accuracy"], 0.35),
                (metrics["direction_accuracy"], 0.20),
            ]
        )
        return {
            "ready": ready,
            "confidence": confidence,
            "reason": _reason(
                "FINANCIAL",
                ready,
                metrics,
                conflicts["FINANCIAL"],
                [
                    "financial accuracy > 0.92",
                    "amount accuracy > 0.95",
                    "direction accuracy > 0.90",
                ],
            ),
        }

    def _work_recommendation(
        self,
        metrics: dict[str, float],
        conflicts: dict[str, Counter[str]],
    ) -> dict[str, Any]:
        ready = (
            metrics["samples"] > 0
            and metrics["work_accuracy"] > 0.90
            and metrics["entity_accuracy"] > 0.90
        )
        confidence = _weighted_average(
            [(metrics["work_accuracy"], 0.60), (metrics["entity_accuracy"], 0.40)]
        )
        return {
            "ready": ready,
            "confidence": confidence,
            "reason": _reason(
                "WORK",
                ready,
                metrics,
                conflicts["WORK"],
                ["work accuracy > 0.90", "entity accuracy > 0.90"],
            ),
        }

    def _setup_recommendation(
        self,
        metrics: dict[str, float],
        conflicts: dict[str, Counter[str]],
    ) -> dict[str, Any]:
        ready = metrics["samples"] > 0 and metrics["entity_accuracy"] > 0.92
        confidence = metrics["entity_accuracy"]
        return {
            "ready": ready,
            "confidence": confidence,
            "reason": _reason(
                "SETUP",
                ready,
                metrics,
                conflicts["SETUP"],
                ["entity resolution accuracy > 0.92"],
            ),
        }

    def _risk_areas(
        self,
        conflicts: dict[str, Counter[str]],
        total_samples: int,
    ) -> list[dict[str, str]]:
        risks: list[dict[str, str]] = []
        if total_samples <= 0:
            return risks
        risk_map = {
            "ENTITY_MISMATCH": "Entity mismatch frequency",
            "DIRECTION_ERROR": "Financial direction errors",
            "OVERCONFIDENCE_ERROR": "High-confidence wrong cases",
        }
        for domain, counts in conflicts.items():
            for conflict_type, issue in risk_map.items():
                count = counts.get(conflict_type, 0)
                if count <= 0:
                    continue
                rate = count / total_samples
                risks.append(
                    {
                        "domain": domain,
                        "issue": f"{issue}: {count}/{total_samples} samples",
                        "severity": _severity(rate),
                    }
                )
        return risks

    def _shadow_vs_legacy_summary(self, summary: dict[str, Any]) -> dict[str, list[str]]:
        breakdown = summary.get("category_breakdown", {})
        result = {
            "shadow_better_domains": [],
            "legacy_better_domains": [],
            "tie_domains": [],
        }
        for domain in DOMAINS:
            item = breakdown.get(domain, {})
            shadow_better = int(item.get("shadow_better", 0))
            legacy_better = int(item.get("legacy_better", 0))
            if shadow_better > legacy_better:
                result["shadow_better_domains"].append(domain)
            elif legacy_better > shadow_better:
                result["legacy_better_domains"].append(domain)
            else:
                result["tie_domains"].append(domain)
        return result

    def _final_recommendation(
        self,
        recommended: dict[str, dict[str, Any]],
        risk_areas: list[dict[str, str]],
    ) -> str:
        high_risk_count = sum(1 for risk in risk_areas if risk["severity"] == "HIGH")
        if high_risk_count >= 2:
            return FINAL_DO_NOT_MIGRATE

        safe_domains = {
            domain for domain, decision in recommended.items() if decision["ready"] is True
        }
        if safe_domains == set(DOMAINS):
            return FINAL_MIGRATE_ALL
        if safe_domains == {"FINANCIAL"}:
            return FINAL_MIGRATE_FINANCIAL_ONLY
        if safe_domains:
            return FINAL_PARTIAL_MIGRATION
        return FINAL_DO_NOT_MIGRATE


def _empty_recommendation() -> dict[str, Any]:
    recommended = {
        domain: {
            "ready": False,
            "confidence": 0.0,
            "reason": "No shadow samples are available, so migration is not data-supported.",
        }
        for domain in DOMAINS
    }
    return {
        "overall_migration_readiness": 0.0,
        "recommended_migrations": recommended,
        "risk_areas": [],
        "shadow_vs_legacy_summary": {
            "shadow_better_domains": [],
            "legacy_better_domains": [],
            "tie_domains": DOMAINS,
        },
        "final_recommendation": FINAL_DO_NOT_MIGRATE,
    }


def _domain(log: ShadowInterpretationLog) -> str:
    legacy = _legacy(log)
    shadow = log.shadow_json if isinstance(log.shadow_json, dict) else {}
    return _intent(legacy) or _intent(shadow) or "NOTE"


def _legacy(log: ShadowInterpretationLog) -> dict[str, Any]:
    value = log.legacy_json
    if isinstance(value, list):
        return value[0] if value and isinstance(value[0], dict) else {}
    if isinstance(value, dict):
        interpretations = value.get("interpretations")
        if isinstance(interpretations, list):
            if interpretations and isinstance(interpretations[0], dict):
                return interpretations[0]
            return {}
        return value
    return {}


def _intent(value: dict[str, Any]) -> str | None:
    raw_intent = value.get("canonical_event_type") or value.get("intent") or value.get("type")
    mapping = {
        "SETUP_EVENT": "SETUP",
        "WORK_EVENT": "WORK",
        "FINANCIAL_EVENT": "FINANCIAL",
        "NOTE_EVENT": "NOTE",
    }
    return mapping.get(str(raw_intent), str(raw_intent)) if raw_intent is not None else None


def _ratio(rows: list[ShadowInterpretationLog], predicate: Any) -> float:
    if not rows:
        return 0.0
    return sum(1 for row in rows if predicate(row)) / len(rows)


def _diff(log: ShadowInterpretationLog, key: str) -> bool:
    return bool(log.diff_json.get(key)) if isinstance(log.diff_json, dict) else False


def _intent_matches(log: ShadowInterpretationLog) -> bool:
    return _diff(log, "intent_match")


def _entity_matches(log: ShadowInterpretationLog) -> bool:
    return _diff(log, "entity_match")


def _amount_matches(log: ShadowInterpretationLog) -> bool:
    return _diff(log, "amount_match")


def _direction_matches(log: ShadowInterpretationLog) -> bool:
    return _diff(log, "direction_match")


def _financial_matches(log: ShadowInterpretationLog) -> bool:
    return _amount_matches(log) and _direction_matches(log)


def _work_matches(log: ShadowInterpretationLog) -> bool:
    legacy = _legacy(log)
    shadow = log.shadow_json if isinstance(log.shadow_json, dict) else {}
    shadow_work = shadow.get("work") if isinstance(shadow.get("work"), dict) else {}
    return _number(legacy.get("extracted_quantity") or legacy.get("quantity")) == _number(
        shadow_work.get("quantity")
    ) and _unit(legacy) == _unit(shadow_work)


def _number(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _unit(value: dict[str, Any]) -> str | None:
    unit = value.get("unit")
    return str(unit) if unit in {"day", "meter", "item"} else None


def _weighted_average(values: list[tuple[float, float]]) -> float:
    return sum(value * weight for value, weight in values)


def _overall_readiness(recommended: dict[str, dict[str, Any]]) -> float:
    return sum(decision["confidence"] for decision in recommended.values()) / len(recommended)


def _reason(
    domain: str,
    ready: bool,
    metrics: dict[str, float],
    conflicts: Counter[str],
    thresholds: list[str],
) -> str:
    samples = int(metrics["samples"])
    top_failures = _top_failures(conflicts)
    status = "ready" if ready else "not ready"
    failure_text = ", ".join(top_failures) if top_failures else "no dominant failure pattern"
    return (
        f"{domain} is {status} based on {samples} shadow samples. "
        f"Metrics: entity={metrics['entity_accuracy']:.2f}, "
        f"financial={metrics['financial_accuracy']:.2f}, "
        f"amount={metrics['amount_accuracy']:.2f}, "
        f"direction={metrics['direction_accuracy']:.2f}, "
        f"work={metrics['work_accuracy']:.2f}. "
        f"Required thresholds: {', '.join(thresholds)}. "
        f"Top failure patterns: {failure_text}. "
        "Confidence reflects only stored shadow-vs-legacy structured comparisons."
    )


def _top_failures(conflicts: Counter[str]) -> list[str]:
    return [name for name, _count in conflicts.most_common(3)]


def _severity(error_rate: float) -> str:
    if error_rate > 0.10:
        return "HIGH"
    if error_rate >= 0.05:
        return "MEDIUM"
    return "LOW"
