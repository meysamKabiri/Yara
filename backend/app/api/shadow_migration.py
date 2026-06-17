from typing import Any

from fastapi import APIRouter

from app.dependencies.database import DbSession
from app.services.shadow_migration_decision_engine import MigrationDecisionEngine

router = APIRouter(prefix="/shadow", tags=["shadow-migration"])


@router.get("/migration-recommendation")
def get_shadow_migration_recommendation(db: DbSession) -> dict[str, Any]:
    return MigrationDecisionEngine(db).recommendation()
