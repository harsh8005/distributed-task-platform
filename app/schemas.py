from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: str
    typ: str
    exp: int


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str | None = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    full_name: str | None
    role: str
    created_at: datetime


class JobCreate(BaseModel):
    job_type: str = "generic"
    payload: dict[str, Any] = Field(default_factory=dict)
    run_at: datetime | None = None
    queue_name: str | None = None
    max_attempts: int | None = None


class JobRetryRequest(BaseModel):
    delay_seconds: int | None = None


class JobAttemptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: str
    attempt_number: int
    status: str
    error_message: str | None
    worker_id: str | None
    started_at: datetime
    finished_at: datetime | None


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_id: str
    queue_name: str
    job_type: str
    status: str
    payload: dict[str, Any]
    result: dict[str, Any] | None = None
    attempts: int
    max_attempts: int
    run_at: datetime | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    last_error: str | None
    worker_id: str | None


class JobListResponse(BaseModel):
    items: list[JobRead]
    total: int


class JobAttemptListResponse(BaseModel):
    items: list[JobAttemptRead]
    total: int


class DashboardStats(BaseModel):
    total_jobs: int
    queued_jobs: int
    running_jobs: int
    completed_jobs: int
    failed_jobs: int
    retrying_jobs: int
    dead_letter_jobs: int
    scheduled_jobs: int
    active_workers: int
    queue_length: int
