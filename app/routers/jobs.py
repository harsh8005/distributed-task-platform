from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.broker import QueueMessage, broker
from app.cache import cache
from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import Job
from app.observability import queue_length_gauge
from app.schemas import DashboardStats, JobAttemptListResponse, JobAttemptRead, JobCreate, JobListResponse, JobRead, JobRetryRequest
from app.services import build_dashboard_stats, create_job, get_job, list_job_attempts, list_jobs, retry_job

settings = get_settings()
router = APIRouter(prefix="/jobs", tags=["jobs"])


def to_job_read(job: Job) -> JobRead:
    return JobRead(
        id=job.id,
        owner_id=job.owner_id,
        queue_name=job.queue_name,
        job_type=job.job_type,
        status=job.status,
        payload=job.payload,
        result=job.result,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        run_at=job.run_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        last_error=job.last_error,
        worker_id=job.worker_id,
        idempotency_key=job.idempotency_key,
        correlation_id=job.correlation_id,
        priority=job.priority,
    )


def to_job_attempt_read(attempt) -> JobAttemptRead:
    return JobAttemptRead(
        id=attempt.id,
        job_id=attempt.job_id,
        attempt_number=attempt.attempt_number,
        status=attempt.status,
        error_message=attempt.error_message,
        worker_id=attempt.worker_id,
        correlation_id=attempt.correlation_id,
        started_at=attempt.started_at,
        finished_at=attempt.finished_at,
    )


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def create_new_job(
    payload: JobCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> JobRead:
    job = create_job(
        db,
        owner=current_user,
        payload=payload.payload,
        job_type=payload.job_type,
        run_at=payload.run_at,
        queue_name=payload.queue_name,
        max_attempts=payload.max_attempts,
        idempotency_key=payload.idempotency_key,
        correlation_id=payload.correlation_id,
        priority=payload.priority,
    )
    if job.status == "queued":
        from app.outbox import relay_outbox_events
        relay_outbox_events(db)
    cache.delete("dashboard:stats")
    return to_job_read(job)


@router.get("", response_model=JobListResponse)
def get_jobs(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> JobListResponse:
    jobs, total = list_jobs(db, owner=current_user, status=status_filter, limit=limit, offset=offset)
    return JobListResponse(items=[to_job_read(job) for job in jobs], total=total)


@router.get("/{job_id}", response_model=JobRead)
def get_single_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> JobRead:
    job = get_job(db, job_id, owner=current_user)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return to_job_read(job)


@router.post("/{job_id}/retry", response_model=JobRead)
def retry_single_job(
    job_id: str,
    retry_request: JobRetryRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> JobRead:
    job = get_job(db, job_id, owner=current_user)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    try:
        job = retry_job(db, job, delay_seconds=retry_request.delay_seconds)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if job.status == "queued":
        broker.publish(QueueMessage(job_id=job.id), queue_name=job.queue_name)
    cache.delete("dashboard:stats")
    return to_job_read(job)


@router.get("/{job_id}/attempts", response_model=JobAttemptListResponse)
def get_job_attempts(
    job_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> JobAttemptListResponse:
    job = get_job(db, job_id, owner=current_user)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    attempts = list_job_attempts(db, job, owner=current_user)
    return JobAttemptListResponse(items=[to_job_attempt_read(attempt) for attempt in attempts], total=len(attempts))


@router.get("/dashboard/stats", response_model=DashboardStats)
def dashboard_stats(db: Session = Depends(get_db)) -> DashboardStats:
    cached = cache.get_json("dashboard:stats")
    if isinstance(cached, dict):
        return DashboardStats(**cached)
    stats = build_dashboard_stats(db)
    cache.set_json("dashboard:stats", stats, ttl_seconds=15)
    queue_length_gauge.set(stats["queue_length"])
    return DashboardStats(**stats)
