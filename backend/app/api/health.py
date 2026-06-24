import logging

from fastapi import APIRouter
from sqlalchemy import text

from app.schemas.health import HealthCheck

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


def _check_database() -> str:
    try:
        from app.db.session import SessionLocal

        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return "ok"
    except Exception as e:
        logger.debug("Health check — database unavailable: %s", e)
        return "unavailable"


def _check_redis() -> str:
    try:
        from app.core.queue import get_redis_connection

        get_redis_connection().ping()
        return "ok"
    except Exception as e:
        logger.debug("Health check — redis unavailable: %s", e)
        return "unavailable"


def _check_ollama() -> str:
    try:
        import json
        import urllib.request

        from app.services.llm_v2_interpreter import OLLAMA_BASE_URL

        url = f"{OLLAMA_BASE_URL}/api/tags"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                return "ok"
            return "unavailable"
    except Exception as e:
        logger.debug("Health check — ollama unavailable: %s", e)
        return "unavailable"


@router.get("/health", response_model=HealthCheck)
def health_check() -> HealthCheck:
    db_status = _check_database()
    redis_status = _check_redis()
    ollama_status = _check_ollama()
    overall = "ok" if db_status == "ok" else "degraded"
    return HealthCheck(
        status=overall,
        database=db_status,
        redis=redis_status,
        ollama=ollama_status,
    )
