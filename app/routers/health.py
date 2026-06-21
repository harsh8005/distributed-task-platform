from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.cache import cache
from app.config import get_settings
from app.database import get_db
from app.schemas import HealthResponse

settings = get_settings()
router = APIRouter(tags=["health"])


@router.get("/", response_model=dict[str, str])
def root() -> dict[str, str]:
    return {"message": "Distributed Task Platform API"}


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="api", environment=settings.environment)


@router.get("/ready", response_model=dict[str, bool])
def ready(db: Session = Depends(get_db)) -> dict[str, bool]:
    db.execute(text("SELECT 1"))
    redis_ready = cache.ping() if settings.enable_redis else True
    return {"database": True, "redis": redis_ready}
