from typing import Any

from fastapi import APIRouter

from app.core.feature_flags import get_financial_migration_mode
from app.dependencies.database import DbSession
from app.services.financial_migration_logger import financial_migration_status, llm_authority_status

router = APIRouter(prefix="/shadow", tags=["financial-migration"])


@router.get("/financial-migration-status")
def get_financial_migration_status(db: DbSession) -> dict[str, Any]:
    status = financial_migration_status(db)
    return {"mode": get_financial_migration_mode().value, **status}


@router.get("/llm-authority-status")
def get_llm_authority_status(db: DbSession) -> dict[str, Any]:
    status = llm_authority_status(db)
    return {
        "llm_primary_rate": status["llm_primary_rate"],
        "legacy_fallback_rate": status["legacy_fallback_rate"],
        "top_fallback_reasons": status["top_fallback_reasons"],
        "risk_level": status["risk_level"],
    }
