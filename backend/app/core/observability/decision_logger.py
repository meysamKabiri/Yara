from typing import Any

from sqlalchemy.orm import Session

from app.core.runtime.request_cache import RequestCache
from app.models.core import FinancialMigrationLog
from app.services.financial_migration_logger import log_financial_migration_decision
from app.services.shadow_logger import log_shadow_comparison


def log_shadow_decision(
    db: Session,
    project_id: int,
    input_text: str,
    legacy_result: dict[str, Any] | list[dict[str, Any]],
    shadow_result: dict[str, Any],
) -> dict[str, bool]:
    return log_shadow_comparison(project_id, input_text, legacy_result, shadow_result, db=db)


def log_financial_decision(
    db: Session,
    *,
    project_id: int,
    input_text: str,
    legacy_json: dict[str, Any] | list[dict[str, Any]],
    shadow_json: dict[str, Any],
    chosen_system: str,
    reason: str,
) -> FinancialMigrationLog:
    return log_financial_migration_decision(
        db,
        project_id=project_id,
        input_text=input_text,
        legacy_json=legacy_json,
        shadow_json=shadow_json,
        chosen_system=chosen_system,
        reason=reason,
    )


def queue_financial_decision(
    cache: RequestCache,
    *,
    project_id: int,
    input_text: str,
    legacy_json: dict[str, Any] | list[dict[str, Any]],
    shadow_json: dict[str, Any],
    chosen_system: str,
    reason: str,
) -> None:
    cache.add_decision_log(
        {
            "type": "financial",
            "project_id": project_id,
            "input_text": input_text,
            "legacy_json": legacy_json,
            "shadow_json": shadow_json,
            "chosen_system": chosen_system,
            "reason": reason,
        }
    )


def queue_shadow_decision(
    cache: RequestCache,
    *,
    project_id: int,
    input_text: str,
    legacy_result: dict[str, Any] | list[dict[str, Any]],
    shadow_result: dict[str, Any],
) -> None:
    cache.add_decision_log(
        {
            "type": "shadow",
            "project_id": project_id,
            "input_text": input_text,
            "legacy_result": legacy_result,
            "shadow_result": shadow_result,
        }
    )


def flush_decision_logs(db: Session, cache: RequestCache, *, log_type: str) -> None:
    pending = [item for item in cache.decision_logs if item["type"] == log_type]
    cache.decision_logs = [item for item in cache.decision_logs if item["type"] != log_type]
    for item in pending:
        if item["type"] == "financial":
            log_financial_decision(
                db,
                project_id=item["project_id"],
                input_text=item["input_text"],
                legacy_json=item["legacy_json"],
                shadow_json=item["shadow_json"],
                chosen_system=item["chosen_system"],
                reason=item["reason"],
            )
        elif item["type"] == "shadow":
            log_shadow_decision(
                db,
                item["project_id"],
                item["input_text"],
                item["legacy_result"],
                item["shadow_result"],
            )
