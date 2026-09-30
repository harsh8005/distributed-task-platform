from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import Base, engine
from app.models import Job, JobAttempt, User  # noqa: F401
from app.observability import metrics_response
from app.routers.auth import router as auth_router
from app.routers.health import router as health_router
from app.routers.jobs import router as jobs_router

settings = get_settings()

app = FastAPI(title=settings.app_name, version="1.0.0")

from app.tracing import instrument_fastapi_app, setup_telemetry
setup_telemetry(service_name="dtp-api")
instrument_fastapi_app(app)

if settings.allow_all_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.on_event("startup")
def on_startup() -> None:
    if settings.auto_create_tables:
        Base.metadata.create_all(bind=engine)


app.include_router(health_router)
app.include_router(auth_router)
app.include_router(jobs_router)


@app.get("/metrics")
def metrics():
    return metrics_response()

