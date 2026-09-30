from __future__ import annotations

from datetime import timedelta
import pytest

from app.broker import broker
from app.config import get_settings
from app.models import OutboxEvent, User
from app.outbox import relay_outbox_events
from app.services import (
    claim_next_job,
    create_job,
    create_user,
    get_job,
    now_utc_naive,
    recover_orphaned_jobs,
)
from autoscaler import autoscale_step, compute_desired_workers
from worker import process_claimed_job

settings = get_settings()


def create_test_tenant(db_session, email_prefix: str) -> User:
    return create_user(db_session, f"{email_prefix}@test.com", "strong-password", f"Tenant {email_prefix}")


def test_chaos_crashed_worker_orphan_recovery(db_session):
    """Chaos Test: Worker process dies mid-execution; system automatically recovers the job."""
    tenant = create_test_tenant(db_session, "chaos_worker")
    job = create_job(db_session, owner=tenant, payload={"action": "sleep", "seconds": 60}, max_attempts=2)

    # Worker 1 claims job
    claimed = claim_next_job(db_session, worker_id="worker-pod-crash-1")
    assert claimed is not None
    assert claimed.status == "running"

    # Simulate worker node abruptly crashing (SIGKILL) - started_at is aged past timeout
    claimed.started_at = now_utc_naive() - timedelta(minutes=45)
    db_session.add(claimed)
    db_session.commit()

    # Self-healing recovery runs
    recovered = recover_orphaned_jobs(db_session, timeout_minutes=30)
    assert recovered == 1

    db_session.refresh(claimed)
    assert claimed.status == "retrying"
    assert "Orphaned job recovered" in claimed.last_error

    # Simulate retry delay having elapsed so job is immediately claimable
    claimed.run_at = now_utc_naive() - timedelta(seconds=1)
    db_session.add(claimed)
    db_session.commit()

    # Worker 2 picks up recovered job and finishes it
    recovered_job = claim_next_job(db_session, worker_id="worker-pod-healthy-2")
    assert recovered_job is not None
    assert recovered_job.id == job.id


def test_chaos_broker_outage_buffered_by_outbox(db_session):
    """Chaos Test: Message broker completely goes down; Outbox buffers events without data loss."""
    tenant = create_test_tenant(db_session, "chaos_broker")

    prev_enable_rmq = settings.enable_rabbitmq
    settings.enable_rabbitmq = True
    orig_publish = broker.publish
    # Step 1: Broker publish fails (e.g. connection dropped)
    broker.publish = lambda *args, **kwargs: False
    try:
        # Client creates job during broker outage
        job = create_job(db_session, owner=tenant, payload={"action": "sum", "numbers": [10, 20]}, priority=7)
        assert job.status == "queued"

        # Outbox event is safely persisted in DB
        event = db_session.query(OutboxEvent).filter(OutboxEvent.status == "pending").first()
        assert event is not None
        assert event.payload["job_id"] == job.id

        # Relay attempt during outage fails safely without losing the event
        relayed = relay_outbox_events(db_session)
        assert relayed == 0
        db_session.refresh(event)
        assert event.status == "pending"

        # Step 2: Broker recovers!
        broker.publish = lambda *args, **kwargs: True
        relayed_after_recovery = relay_outbox_events(db_session)
        assert relayed_after_recovery == 1
        db_session.refresh(event)
        assert event.status == "published"
    finally:
        settings.enable_rabbitmq = prev_enable_rmq
        broker.publish = orig_publish


def test_chaos_poison_pill_payload_isolation(db_session):
    """Chaos Test: Toxic/poison pill payload is submitted; worker isolates error and moves to DLQ."""
    tenant = create_test_tenant(db_session, "chaos_poison")
    job = create_job(db_session, owner=tenant, payload={"action": "fail", "message": "fatal memory explosion"}, max_attempts=1)

    claimed = claim_next_job(db_session, worker_id="worker-resilient")
    assert claimed is not None

    # Worker processes toxic job; must handle exception cleanly without crashing
    process_claimed_job(db_session, claimed)

    db_session.refresh(claimed)
    assert claimed.status == "dead_letter"
    assert "fatal memory explosion" in claimed.last_error

    # Ensure worker can immediately process a subsequent healthy job
    healthy_job = create_job(db_session, owner=tenant, payload={"action": "sum", "numbers": [1, 2]})
    claimed_healthy = claim_next_job(db_session, worker_id="worker-resilient")
    assert claimed_healthy is not None
    process_claimed_job(db_session, claimed_healthy)
    db_session.refresh(claimed_healthy)
    assert claimed_healthy.status == "completed"


def test_chaos_noisy_neighbor_concurrency_isolation(db_session):
    """Chaos Test: Noisy neighbor floods queue; tenant concurrency limits protect other users."""
    tenant_flooder = create_test_tenant(db_session, "flooder")
    tenant_normal = create_test_tenant(db_session, "normal")

    # Flooder submits 10 jobs (more than limit of 5)
    for _ in range(10):
        create_job(db_session, owner=tenant_flooder, payload={"action": "echo"}, priority=10)

    # Normal tenant submits 1 job with lower priority
    normal_job = create_job(db_session, owner=tenant_normal, payload={"action": "echo"}, priority=2)

    # Worker pool claims up to limit for flooder
    for _ in range(settings.max_concurrent_jobs_per_tenant):
        claimed = claim_next_job(db_session, worker_id="pool-worker")
        assert claimed is not None
        assert claimed.owner_id == tenant_flooder.id

    # The 6th claim must NOT give flooder another slot; it must give normal tenant their slot!
    fair_claim = claim_next_job(db_session, worker_id="pool-worker")
    assert fair_claim is not None
    assert fair_claim.id == normal_job.id
    assert fair_claim.owner_id == tenant_normal.id


def test_autoscaler_dynamic_scale_computation(db_session):
    """Chaos Test: Queue surges with 40 tasks; Autoscaler computes proportional scale-up."""
    # Scale up calculation
    scale_up = compute_desired_workers(queue_backlog=40, min_workers=1, max_workers=10, jobs_per_worker=5)
    assert scale_up == 8  # 40 / 5 = 8 workers

    # Saturation clamp to max_workers
    saturated = compute_desired_workers(queue_backlog=200, min_workers=1, max_workers=10, jobs_per_worker=5)
    assert saturated == 10

    # Scale down to min_workers on empty queue
    scale_down = compute_desired_workers(queue_backlog=0, min_workers=1, max_workers=10, jobs_per_worker=5)
    assert scale_down == 1

    # Live DB step evaluation
    backlog, desired = autoscale_step(db_session)
    assert desired >= 1
