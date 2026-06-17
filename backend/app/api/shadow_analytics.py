from typing import Any

from fastapi import APIRouter

from app.dependencies.database import DbSession
from app.services.shadow_analytics_service import ShadowAnalyticsService

router = APIRouter(prefix="/shadow", tags=["shadow-analytics"])


@router.get("/summary")
def get_shadow_summary(db: DbSession) -> dict[str, Any]:
    return ShadowAnalyticsService(db).summary()


@router.get("/conflicts")
def get_shadow_conflicts(db: DbSession) -> list[dict[str, Any]]:
    return ShadowAnalyticsService(db).conflicts()


@router.get("/category-breakdown")
def get_shadow_category_breakdown(db: DbSession) -> dict[str, dict[str, int]]:
    return ShadowAnalyticsService(db).category_breakdown()
