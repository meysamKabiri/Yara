from fastapi import FastAPI

from app.api.financial_migration import router as financial_migration_router
from app.api.health import router as health_router
from app.api.job_websockets import router as job_websockets_router
from app.api.projects import router as projects_router
from app.api.sandbox import router as sandbox_router
from app.api.shadow_analytics import router as shadow_analytics_router
from app.api.shadow_migration import router as shadow_migration_router
from app.api.traces import router as traces_router
from app.core.config import settings
from app.core.trace_context import TraceContextMiddleware, configure_trace_logging


def create_app() -> FastAPI:
    configure_trace_logging()
    app = FastAPI(title=settings.app_name, debug=settings.debug)
    app.add_middleware(TraceContextMiddleware)
    app.include_router(health_router)
    app.include_router(job_websockets_router)
    app.include_router(financial_migration_router)
    app.include_router(projects_router)
    app.include_router(sandbox_router)
    app.include_router(shadow_analytics_router)
    app.include_router(shadow_migration_router)
    app.include_router(traces_router)
    return app


app = create_app()
