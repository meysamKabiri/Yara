import time

from app.core.logger import log_event


def wait_for_database() -> None:
    from sqlalchemy import create_engine, text

    from app.core.config import settings

    attempt = 0
    while True:
        try:
            engine = create_engine(settings.database_url)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            log_event(event="migrate.db_connected", message="Database connection established")
            engine.dispose()
            return
        except Exception as e:
            attempt += 1
            delay = min(0.5 * (2**attempt), 30.0)
            log_event(
                event="migrate.db_unavailable",
                message="Database unavailable, retrying...",
                payload={"attempt": attempt, "delay": delay, "error": str(e)},
            )
            time.sleep(delay)


def run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    log_event(event="migrate.starting", message="Running database migrations...")
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    log_event(event="migrate.complete", message="Migrations complete")


def main() -> None:
    wait_for_database()
    run_migrations()


if __name__ == "__main__":
    main()
