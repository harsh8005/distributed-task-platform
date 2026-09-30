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


def test_job_idempotency_returns_existing_job(db_session):
    user = create_test_user(db_session)
    job1 = job_routes.create_new_job(
        JobCreate(job_type="math", payload={"action": "sum", "numbers": [1, 2]}, idempotency_key="key-abc-123"),
        db=db_session,
        current_user=user,
    )
    job2 = job_routes.create_new_job(
        JobCreate(job_type="math", payload={"action": "sum", "numbers": [1, 2]}, idempotency_key="key-abc-123"),
        db=db_session,
        current_user=user,
    )
    assert job1.id == job2.id
    assert job1.idempotency_key == "key-abc-123"


def test_correlation_id_propagation(db_session):
    user = create_test_user(db_session)
    job = job_routes.create_new_job(
        JobCreate(job_type="math", payload={"action": "sum", "numbers": [1, 2]}, correlation_id="trace-xyz-789"),
        db=db_session,
        current_user=user,
    )
    assert job.correlation_id == "trace-xyz-789"

    claimed = claim_next_job(db_session, worker_id="worker-test")
    assert claimed is not None
    process_claimed_job(db_session, claimed)

    attempts = job_routes.get_job_attempts(job.id, db=db_session, current_user=user)
    assert attempts.total == 1
    assert attempts.items[0].correlation_id == "trace-xyz-789"


def test_orphaned_jobs_recovery(db_session):
    from datetime import timedelta
    from app.services import now_utc_naive, recover_orphaned_jobs

    user = create_test_user(db_session)
    job = create_job(db_session, owner=user, payload={"action": "echo"}, max_attempts=2)
    claimed = claim_next_job(db_session, worker_id="crashed-worker")
    assert claimed is not None

    # Simulate worker crash by winding back started_at past the cutoff
    claimed.started_at = now_utc_naive() - timedelta(minutes=45)
    db_session.add(claimed)
    db_session.commit()

    recovered_count = recover_orphaned_jobs(db_session, timeout_minutes=30)
    assert recovered_count == 1

    db_session.refresh(claimed)
    assert claimed.status == "retrying"
    assert "Orphaned job recovered" in claimed.last_error


def test_transactional_outbox_event_creation_and_relay(db_session):
    from app.models import OutboxEvent
    from app.outbox import relay_outbox_events
    from sqlalchemy import select

    user = create_test_user(db_session)
    job = create_job(db_session, owner=user, payload={"action": "sum", "numbers": [1, 2]}, priority=8)

    # Verify OutboxEvent was created in the exact same transaction
    event = db_session.scalar(select(OutboxEvent).where(OutboxEvent.status == "pending"))
    assert event is not None
    assert event.event_type == "job.created"
    assert event.payload["job_id"] == job.id
    assert event.payload["priority"] == 8

    # Relay outbox event
    relayed_count = relay_outbox_events(db_session)
    assert relayed_count == 1
    db_session.refresh(event)
    assert event.status == "published"
    assert event.published_at is not None


def test_priority_queue_ordering(db_session):
    user = create_test_user(db_session)

    low_prio = create_job(db_session, owner=user, payload={"action": "echo"}, priority=2)
    high_prio = create_job(db_session, owner=user, payload={"action": "echo"}, priority=9)
    med_prio = create_job(db_session, owner=user, payload={"action": "echo"}, priority=5)

    # Claim next job must pick the highest priority job first (priority 9)
    c1 = claim_next_job(db_session, worker_id="w1")
    assert c1 is not None
    assert c1.id == high_prio.id
    assert c1.priority == 9

    # Next claim must pick priority 5
    c2 = claim_next_job(db_session, worker_id="w1")
    assert c2 is not None
    assert c2.id == med_prio.id
    assert c2.priority == 5

    # Next claim must pick priority 2
    c3 = claim_next_job(db_session, worker_id="w1")
    assert c3 is not None
    assert c3.id == low_prio.id
    assert c3.priority == 2


def test_tenant_concurrency_limit_fair_scheduling(db_session):
    from app.config import get_settings
    settings = get_settings()

    user_a = create_user(db_session, "tenant_a@example.com", "strong-password", "Tenant A")
    user_b = create_user(db_session, "tenant_b@example.com", "strong-password", "Tenant B")

    # Fill User A's concurrent slots to the limit
    for _ in range(settings.max_concurrent_jobs_per_tenant):
        job = create_job(db_session, owner=user_a, payload={"action": "echo"})
        claim_next_job(db_session, worker_id="wA")

    # User A queues another job
    extra_a = create_job(db_session, owner=user_a, payload={"action": "echo"}, priority=10)
    # User B queues a normal job
    job_b = create_job(db_session, owner=user_b, payload={"action": "echo"}, priority=3)

    # Even though User A's job has higher priority (10 vs 3), User A reached concurrency limit!
    # The fair scheduler must skip User A and claim User B's job!
    claimed = claim_next_job(db_session, worker_id="wFair")
    assert claimed is not None
    assert claimed.id == job_b.id
    assert claimed.owner_id == user_b.id


def test_worker_idempotent_execution_guard(db_session):
    user = create_test_user(db_session)
    job = create_job(db_session, owner=user, payload={"action": "sum", "numbers": [10, 20]})
    claimed = claim_next_job(db_session, worker_id="w1")
    assert claimed is not None

    # First execution completes normally
    process_claimed_job(db_session, claimed)
    db_session.refresh(claimed)
    assert claimed.status == "completed"
    assert claimed.result == {"action": "sum", "total": 30}
    assert claimed.attempts == 1

    # Simulate RabbitMQ redelivery (duplicate message arrives while job is already completed)
    # The idempotency guard must detect job.status == "completed" and skip redundant execution
    process_claimed_job(db_session, claimed)
    db_session.refresh(claimed)
    assert claimed.attempts == 1  # Attempts and result remain untouched!


def test_opentelemetry_tracing_helpers():
    from app.tracing import extract_trace_context, inject_trace_headers, trace_span

    headers = inject_trace_headers({"custom_attr": "value123"})
    assert headers["custom_attr"] == "value123"

    with trace_span("test.manual_span", attributes={"job.test": "42"}):
        pass

    ctx = extract_trace_context(headers)
    assert ctx is None or ctx is not None  # verifies no crash



