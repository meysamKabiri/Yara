import os

from sqlalchemy.engine.url import make_url

from app.core.config import settings
from app.db.base import Base
from app.db.session import engine
from app.models import *  # noqa: F403


def _assert_dev_database() -> None:
    url = make_url(settings.database_url)
    if os.environ.get("ENV") != "development":
        raise RuntimeError("Dev CLI blocked outside development environment")
    if url.host not in {"localhost", "127.0.0.1", None}:
        raise RuntimeError("Refusing to reset non-local database")
    if url.database not in {"yara", "yara_dev", "yara_test"}:
        raise RuntimeError("Refusing to reset unknown database name")


def reset_database(*, verbose: bool = True) -> None:
    _assert_dev_database()
    if verbose:
        print("[RESET] Dropping tables...")
    Base.metadata.drop_all(bind=engine())
    if verbose:
        print("[RESET] Recreating schema...")
    Base.metadata.create_all(bind=engine())
    if verbose:
        print("[OK] Reset complete")


if __name__ == "__main__":
    reset_database()
