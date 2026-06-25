from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.models import User
from app.routers import auth as auth_routes
from app.routers import jobs as job_routes
from app.schemas import JobCreate, JobRetryRequest, UserCreate, UserLogin
from app.services import claim_next_job, create_job, create_user, get_job, list_job_attempts
from worker import process_claimed_job


def create_test_user(db_session) -> User:
    return create_user(db_session, "engineer@example.com", "strong-password", "Backend Engineer")


def test_auth_registration_and_login_round_trip(db_session):
    payload = UserCreate(email="engineer@example.com", password="strong-password", full_name="Backend Engineer")

    user = auth_routes.register(payload, db=db_session)
    assert user.email == "engineer@example.com"
    assert user.full_name == "Backend Engineer"

    token = auth_routes.login(UserLogin(email="engineer@example.com", password="strong-password"), db=db_session)
    assert token.token_type == "bearer"
    assert token.access_token
    assert token.refresh_token

    me = auth_routes.me(user=user)
    assert me.id == user.id
    assert me.email == user.email


def test_job_lifecycle_records_attempts_and_supports_history(db_session):
    user = create_test_user(db_session)

    created = job_routes.create_new_job(
        JobCreate(job_type="math", payload={"action": "sum", "numbers": [1, 2, 3]}, max_attempts=1),
        db=db_session,
        current_user=user,
    )
    assert created.status == "queued"
    assert created.attempts == 0

    claimed = claim_next_job(db_session, worker_id="worker-1")
    assert claimed is not None
    assert claimed.id == created.id
    assert claimed.status == "running"
    assert claimed.attempts == 1

    claimed.payload_json = '{"action":"fail","message":"boom"}'
    db_session.add(claimed)
    db_session.commit()
    db_session.refresh(claimed)

    process_claimed_job(db_session, claimed)

    refreshed = get_job(db_session, created.id, owner=user)
    assert refreshed is not None
    assert refreshed.status == "dead_letter"
    assert refreshed.last_error == "boom"
    assert refreshed.completed_at is not None

    attempts = job_routes.get_job_attempts(created.id, db=db_session, current_user=user)
    assert attempts.total == 1
    assert attempts.items[0].attempt_number == 1
    assert attempts.items[0].status == "failed"
    assert attempts.items[0].worker_id == "worker-1"


def test_retry_rejects_active_jobs(db_session):
    user = create_test_user(db_session)

    created = create_job(
        db_session,
        owner=user,
        payload={"action": "sum", "numbers": [1, 2, 3]},
        max_attempts=2,
    )
    claim_next_job(db_session, worker_id="worker-2")

    with pytest.raises(HTTPException) as exc_info:
        job_routes.retry_single_job(created.id, JobRetryRequest(delay_seconds=5), db=db_session, current_user=user)

    assert exc_info.value.status_code == 409


def test_retry_and_schedule_flow_clears_previous_result(db_session):
    user = create_test_user(db_session)

    created = create_job(
        db_session,
        owner=user,
        payload={"action": "fail", "message": "needs retry"},
        max_attempts=1,
    )
    claimed = claim_next_job(db_session, worker_id="worker-3")
    assert claimed is not None
    process_claimed_job(db_session, claimed)

    retry_payload = JobRetryRequest(delay_seconds=10)
    retried = job_routes.retry_single_job(created.id, retry_payload, db=db_session, current_user=user)

    assert retried.status == "scheduled"
    assert retried.last_error is None
    assert retried.result is None
    assert retried.run_at is not None
    assert retried.run_at >= datetime.now(timezone.utc).replace(tzinfo=None)

    attempts = list_job_attempts(db_session, retried, owner=user)
    assert len(attempts) == 1
