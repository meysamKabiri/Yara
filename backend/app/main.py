from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.projects import router as projects_router
from app.core.config import settings


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, debug=settings.debug)
    app.include_router(health_router)
    app.include_router(projects_router)
    return app


app = create_app()
