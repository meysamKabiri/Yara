from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.financial_migration import router as financial_migration_router
from app.api.health import router as health_router
from app.api.job_websockets import router as job_websockets_router
from app.api.metrics import router as metrics_router
from app.api.projects import router as projects_router
from app.api.sandbox import router as sandbox_router
from app.api.shadow_analytics import router as shadow_analytics_router
from app.api.shadow_migration import router as shadow_migration_router
from app.api.traces import router as traces_router
from app.core.config import settings
from app.core.logger import configure_logging, log_event
from app.core.trace_context import TraceContextMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    log_event(event="api.starting", message="Running database migrations...")
    from app.scripts.run_migrations import run_migrations, wait_for_database

    wait_for_database()
    run_migrations()
    log_event(event="api.ready", message="API ready")
    yield
    log_event(event="api.shutdown", message="API shutting down")


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://192.168.100.81:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(TraceContextMiddleware)
    app.include_router(admin_router)
    app.include_router(health_router)
    app.include_router(job_websockets_router)
    app.include_router(financial_migration_router)
    app.include_router(metrics_router)
    app.include_router(projects_router)
    app.include_router(sandbox_router)
    app.include_router(shadow_analytics_router)
    app.include_router(shadow_migration_router)
    app.include_router(traces_router)
    return app


app = create_app()
