import logging

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import settings
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
        from redis import Redis

        conn = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
        conn.ping()
        conn.close()
        return "ok"
    except Exception as e:
        logger.debug("Health check — redis unavailable: %s", e)
        return "unavailable"


def _check_worker() -> str:
    try:
        from redis import Redis
        from rq import Worker

        conn = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
        workers = Worker.all(connection=conn)
        conn.close()
        return "ok" if workers else "unavailable"
    except Exception as e:
        logger.debug("Health check — worker unavailable: %s", e)
        return "unavailable"


def _check_ollama() -> str:
    try:
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
    worker_status = _check_worker()
    ollama_status = _check_ollama()
    overall = (
        "ok"
        if db_status == "ok" and redis_status == "ok" and worker_status == "ok"
        else "degraded"
    )
    return HealthCheck(
        status=overall,
        database=db_status,
        redis=redis_status,
        worker=worker_status,
        ollama=ollama_status,
    )
