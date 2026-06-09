from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Job, JobAttempt, User
from app.observability import jobs_created_total
from app.security import hash_password, verify_password

settings = get_settings()


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


