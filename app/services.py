from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Job, JobAttempt, User
from app.observability import jobs_completed_total, jobs_created_total, jobs_failed_total, jobs_retried_total
from app.security import hash_password, verify_password

settings = get_settings()
CLAIMABLE_JOB_STATUSES = {"queued", "retrying", "scheduled"}
RETRYABLE_JOB_STATUSES = {"completed", "failed", "dead_letter"}


def now_utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def serialize_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def deserialize_payload(payload_json: str) -> dict[str, Any]:
    return json.loads(payload_json)


def create_user(db: Session, email: str, password: str, full_name: str | None = None) -> User:
    existing = db.scalar(select(User).where(User.email == email))
    if existing:
        raise ValueError("Email already registered")
    user = User(email=email.lower().strip(), password_hash=hash_password(password), full_name=full_name)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.email == email.lower().strip()))
    if not user or not verify_password(password, user.password_hash):
        return None
    return user


def create_job(
    db: Session,
    owner: User,
    payload: dict[str, Any],
    job_type: str = "generic",
    run_at: datetime | None = None,
    queue_name: str | None = None,
    max_attempts: int | None = None,
) -> Job:
    normalized_run_at = normalize_datetime(run_at)
    job = Job(
        owner_id=owner.id,
        job_type=job_type,
        payload_json=serialize_payload(payload),
        run_at=normalized_run_at,
        queue_name=queue_name if queue_name is not None else settings.queue_name,
        max_attempts=max_attempts if max_attempts is not None else settings.max_job_attempts,
        status="scheduled" if normalized_run_at and normalized_run_at > now_utc_naive() else "queued",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    jobs_created_total.inc()
    return job


def list_jobs(db: Session, owner: User | None = None, status: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[Job], int]:
    query = select(Job)
    count_query = select(func.count(Job.id))
    if owner:
        query = query.where(Job.owner_id == owner.id)
        count_query = count_query.where(Job.owner_id == owner.id)
    if status:
        query = query.where(Job.status == status)
        count_query = count_query.where(Job.status == status)
    total = db.scalar(count_query) or 0
    items = db.scalars(query.order_by(Job.created_at.desc()).offset(offset).limit(limit)).all()
    return items, total


def get_job(db: Session, job_id: str, owner: User | None = None) -> Job | None:
    query = select(Job).where(Job.id == job_id)
    if owner:
        query = query.where(Job.owner_id == owner.id)
    return db.scalar(query)


def list_job_attempts(db: Session, job: Job, owner: User | None = None) -> list[JobAttempt]:
    if owner is not None and job.owner_id != owner.id:
        return []
    query = select(JobAttempt).where(JobAttempt.job_id == job.id).order_by(JobAttempt.attempt_number.asc())
    return db.scalars(query).all()


def mark_job_running(db: Session, job: Job, worker_id: str | None = None) -> Job:
    if job.status not in CLAIMABLE_JOB_STATUSES:
        raise ValueError(f"Job {job.id} is not claimable from status {job.status}")
    job.status = "running"
    job.worker_id = worker_id
    job.started_at = job.started_at or now_utc_naive()
    job.attempts += 1
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def update_job_status(
    db: Session,
    job: Job,
    status: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    worker_id: str | None = None,
) -> Job:
    job.status = status
    if result is not None:
        job.result_json = json.dumps(result, separators=(",", ":"), sort_keys=True)
    if error is not None:
        job.last_error = error
    if worker_id is not None:
        job.worker_id = worker_id
    if status == "running" and job.started_at is None:
        job.started_at = now_utc_naive()
    if status in {"completed", "failed", "dead_letter"}:
        job.completed_at = now_utc_naive()
    db.add(job)
    db.commit()
    db.refresh(job)
    if status == "completed":
        jobs_completed_total.inc()
    elif status in {"failed", "dead_letter"}:
        jobs_failed_total.inc()
    return job


def log_attempt(db: Session, job: Job, attempt_number: int, status: str, error_message: str | None = None, worker_id: str | None = None) -> JobAttempt:
    attempt = JobAttempt(
        job_id=job.id,
        attempt_number=attempt_number,
        status=status,
        error_message=error_message,
        worker_id=worker_id,
        finished_at=now_utc_naive(),
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def claim_next_job(db: Session, worker_id: str | None = None) -> Job | None:
    now = now_utc_naive()
    query = (
        select(Job)
        .where(Job.status.in_(["queued", "retrying"]))
        .where((Job.run_at.is_(None)) | (Job.run_at <= now))
        .order_by(Job.created_at.asc())
    )
    job = db.scalars(query.limit(1)).first()
    if not job:
        return None
    return mark_job_running(db, job, worker_id=worker_id)


def due_scheduled_jobs(db: Session) -> list[Job]:
    now = now_utc_naive()
    query = (
        select(Job)
        .where(Job.status == "scheduled")
        .where(Job.run_at.is_not(None))
        .where(Job.run_at <= now)
        .order_by(Job.run_at.asc())
    )
    return db.scalars(query).all()


<<<<<<< HEAD
def build_dashboard_stats(db: Session, active_workers: int = 0, queue_length: int = 0) -> dict[str, int]:
    grouped = dict(db.execute(select(Job.status, func.count(Job.id)).group_by(Job.status)).all())
    calculated_queue_length = grouped.get("queued", 0) + grouped.get("retrying", 0)
    return {
        "total_jobs": sum(grouped.values()),
        "queued_jobs": grouped.get("queued", 0),
        "running_jobs": grouped.get("running", 0),
        "completed_jobs": grouped.get("completed", 0),
        "failed_jobs": grouped.get("failed", 0),
        "retrying_jobs": grouped.get("retrying", 0),
        "dead_letter_jobs": grouped.get("dead_letter", 0),
        "scheduled_jobs": grouped.get("scheduled", 0),
        "active_workers": active_workers,
        "queue_length": queue_length or calculated_queue_length,
    }
=======
def retry_job(db: Session, job: Job, delay_seconds: int | None = None) -> Job:
    if job.status not in RETRYABLE_JOB_STATUSES:
        raise ValueError(f"Job {job.id} cannot be retried from status {job.status}")
    if delay_seconds is not None and delay_seconds < 0:
        raise ValueError("delay_seconds must be greater than or equal to 0")

    now = now_utc_naive()
    job.status = "scheduled" if delay_seconds else "queued"
    job.run_at = now if not delay_seconds else now + timedelta(seconds=delay_seconds)
    job.last_error = None
    job.result_json = None
    job.started_at = None
    job.completed_at = None
    job.worker_id = None
    db.add(job)
    db.commit()
    db.refresh(job)
    jobs_retried_total.inc()
    return job
>>>>>>> fa3d0e8 (Add retry handling with configurable limits and per-attempt history)
