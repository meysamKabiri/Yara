import logging
import time
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)

_engine = None
_SessionLocal = None


def _ensure_engine():
    global _engine
    if _engine is not None:
        try:
            with _engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return _engine
        except Exception:
            logger.warning("Existing DB connection lost, reconnecting...")
            _engine = None

    attempt = 0
    while True:
        try:
            engine = create_engine(
                settings.database_url,
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=10,
                pool_recycle=3600,
            )
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            _engine = engine
            logger.info("Database connection established")
            return engine
        except Exception as e:
            attempt += 1
            delay = min(0.5 * (2**attempt), 30.0)
            logger.warning(
                "Database unavailable (attempt %d): %s. Retrying in %.1fs...",
                attempt,
                e,
                delay,
            )
            time.sleep(delay)


def _ensure_session_local():
    global _SessionLocal
    if _SessionLocal is None or _engine is None:
        _SessionLocal = sessionmaker(
            bind=_ensure_engine(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
    return _SessionLocal


def SessionLocal() -> Session:
    return _ensure_session_local()()


def engine():
    return _ensure_engine()


def get_db_session() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
