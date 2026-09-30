from __future__ import annotations

import logging
import os
import socket
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager

from sqlalchemy.orm import Session

from app.broker import QueueMessage, broker
from app.config import get_settings
from app.database import SessionLocal
from app.models import Job
from app.observability import job_processing_seconds, worker_active_gauge
from app.services import claim_next_job, get_job, log_attempt, mark_job_running, update_job_status

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("dtp.worker")

WORKER_ID = os.getenv("WORKER_ID") or f"{socket.gethostname()}-{os.getpid()}"
SHUTDOWN_REQUESTED = False

def handle_shutdown(signum, frame):
    global SHUTDOWN_REQUESTED
    if not SHUTDOWN_REQUESTED:
        logger.info("Shutdown requested. Finishing active job and exiting...")
        SHUTDOWN_REQUESTED = True

signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


@contextmanager
def session_scope() -> Session:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def process_payload(payload: dict) -> dict:
    action = payload.get("action", "echo")
    if action == "sleep":
        duration = int(payload.get("seconds", 1))
        time.sleep(max(duration, 0))
        return {"action": action, "slept_seconds": duration}
    if action == "sum":
        numbers = payload.get("numbers", [])
        return {"action": action, "total": sum(numbers)}
    if action == "uppercase":
        return {"action": action, "value": str(payload.get("value", "")).upper()}
    if action == "fail":
        raise RuntimeError(payload.get("message", "Intentional failure"))
    return {"action": action, "echo": payload, "processed_at": datetime.now(timezone.utc).isoformat()}


def process_claimed_job(db: Session, job: Job) -> None:
    worker_id = job.worker_id or WORKER_ID
    started = time.perf_counter()
    logger.info("Processing job %s [correlation_id=%s]", job.id, job.correlation_id)
    try:
        result = process_payload(job.payload)
        update_job_status(db, job, "completed", result=result, worker_id=worker_id)
        log_attempt(db, job, job.attempts, "completed", worker_id=worker_id, correlation_id=job.correlation_id)
    except Exception as exc:
        error_message = str(exc)
        logger.error("Job %s failed: %s [correlation_id=%s]", job.id, error_message, job.correlation_id)
        log_attempt(db, job, job.attempts, "failed", error_message=error_message, worker_id=worker_id, correlation_id=job.correlation_id)
        if job.attempts < job.max_attempts:
            job.status = "retrying"
            job.last_error = error_message
            job.run_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=settings.retry_delay_seconds)
            db.add(job)
            db.commit()
        else:
            update_job_status(db, job, "dead_letter", error=error_message, worker_id=worker_id)
    finally:
        job_processing_seconds.observe(time.perf_counter() - started)


def consume_with_rabbitmq() -> None:
    def handler(message: QueueMessage) -> None:
        if SHUTDOWN_REQUESTED:
            return
            
        with session_scope() as db:
            job = get_job(db, message.job_id)
            if not job:
                return
            if job.status not in {"queued", "retrying", "scheduled"}:
                return
            job.correlation_id = message.correlation_id or job.correlation_id
            mark_job_running(db, job, worker_id=WORKER_ID)
            process_claimed_job(db, job)

    try:
        broker.consume(handler)
    except Exception as e:
        logger.error("RabbitMQ consumer exited: %s", e)


def poll_database() -> None:
    logger.info("Worker %s started in polling mode", WORKER_ID)
    worker_active_gauge.inc()
    try:
        while not SHUTDOWN_REQUESTED:
            with session_scope() as db:
                job = claim_next_job(db, worker_id=WORKER_ID)
                if job:
                    process_claimed_job(db, job)
                    continue
            time.sleep(settings.worker_poll_interval_seconds)
    finally:
        worker_active_gauge.dec()


def main() -> None:
    logger.info("Starting worker %s", WORKER_ID)
    if settings.enable_rabbitmq:
        try:
            worker_active_gauge.inc()
            consume_with_rabbitmq()
        finally:
            worker_active_gauge.dec()
    else:
        poll_database()


if __name__ == "__main__":
    main()
