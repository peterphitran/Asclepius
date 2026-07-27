from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.campaigns import router as campaigns_router
from app.api.dashboard import router as dashboard_router
from app.api.findings import router as findings_router
from app.api.health import router as health_router
from app.api.review import router as review_router
from app.api.sweeps import router as sweeps_router
from app.api.targets import router as targets_router
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(dashboard_router)
    app.include_router(targets_router)
    app.include_router(campaigns_router)
    app.include_router(sweeps_router)
    app.include_router(findings_router)
    app.include_router(review_router)
    return app


app = create_app()
