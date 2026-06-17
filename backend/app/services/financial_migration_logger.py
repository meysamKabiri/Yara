from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import FinancialMigrationLog
from app.services.compare_legacy_vs_shadow import compare_legacy_vs_shadow


def log_financial_migration_decision(
    db: Session,
    *,
    project_id: int,
    input_text: str,
    legacy_json: dict[str, Any] | list[dict[str, Any]],
    shadow_json: dict[str, Any],
    chosen_system: str,
    reason: str,
) -> FinancialMigrationLog:
    log = FinancialMigrationLog(
        project_id=project_id,
        input_text=input_text,
        legacy_json=jsonable_encoder(legacy_json),
        shadow_json=jsonable_encoder(shadow_json),
        chosen_system=chosen_system,
        reason=reason,
    )
    db.add(log)
    return log


def financial_migration_status(db: Session) -> dict[str, Any]:
    logs = list(db.scalars(select(FinancialMigrationLog)))
    total = len(logs)
    legacy_count = sum(1 for log in logs if log.chosen_system == "LEGACY")
    shadow_count = sum(1 for log in logs if log.chosen_system == "SHADOW")
    agreements = 0
    for log in logs:
        diff = compare_legacy_vs_shadow(log.legacy_json, log.shadow_json)
        if all(diff.values()):
            agreements += 1
    return {
        "usage": {"legacy": legacy_count, "shadow": shadow_count},
        "agreement_rate": agreements / total if total else 0.0,
        "conflict_rate": (total - agreements) / total if total else 0.0,
    }


def llm_authority_status(db: Session) -> dict[str, Any]:
    logs = list(db.scalars(select(FinancialMigrationLog)))
    total = len(logs)
    llm_primary_usage_count = sum(1 for log in logs if log.chosen_system == "SHADOW")
    legacy_fallback_count = sum(1 for log in logs if log.chosen_system == "LEGACY")
    mismatch_triggers = sum(1 for log in logs if "mismatch" in log.reason.lower())
    fallback_reasons: dict[str, int] = {}
    for log in logs:
        if log.chosen_system != "LEGACY":
            continue
        fallback_reasons[log.reason] = fallback_reasons.get(log.reason, 0) + 1

    legacy_fallback_rate = legacy_fallback_count / total if total else 0.0
    return {
        "llm_primary_usage_count": llm_primary_usage_count,
        "legacy_fallback_count": legacy_fallback_count,
        "mismatch_triggers": mismatch_triggers,
        "fallback_reasons": fallback_reasons,
        "llm_primary_rate": llm_primary_usage_count / total if total else 0.0,
        "legacy_fallback_rate": legacy_fallback_rate,
        "top_fallback_reasons": [
            reason
            for reason, _count in sorted(
                fallback_reasons.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:3]
        ],
        "risk_level": _risk_level(
            legacy_fallback_rate,
            mismatch_triggers / total if total else 0.0,
        ),
    }


def _risk_level(fallback_rate: float, mismatch_rate: float) -> str:
    risk = max(fallback_rate, mismatch_rate)
    if risk > 0.10:
        return "HIGH"
    if risk >= 0.05:
        return "MEDIUM"
    return "LOW"
