from __future__ import annotations

import logging
import math
import os
import signal
import sys
import time
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import Job
from app.observability import autoscaler_desired_workers, worker_active_gauge

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("dtp.autoscaler")

STOP_REQUESTED = False


def handle_stop(signum, frame):
    global STOP_REQUESTED
    logger.info("Autoscaler received stop signal. Exiting gracefully...")
    STOP_REQUESTED = True


signal.signal(signal.SIGINT, handle_stop)
signal.signal(signal.SIGTERM, handle_stop)


def compute_desired_workers(
    queue_backlog: int,
    min_workers: int = settings.autoscaler_min_workers,
    max_workers: int = settings.autoscaler_max_workers,
    jobs_per_worker: int = settings.autoscaler_jobs_per_worker,
) -> int:
    """Calculates target worker capacity based on queue lag and saturation threshold."""
    if queue_backlog <= 0:
        return min_workers
    needed = math.ceil(queue_backlog / max(jobs_per_worker, 1))
    return max(min_workers, min(needed, max_workers))


def get_queue_backlog(db: Session) -> int:
    """Queries pending queued and retrying task volume."""
    query = (
        select(func.count(Job.id))
        .where(Job.status.in_(["queued", "retrying"]))
    )
    return db.scalar(query) or 0


def autoscale_step(db: Session) -> tuple[int, int]:
    """Evaluates queue lag and applies scaling adjustment."""
    backlog = get_queue_backlog(db)
    desired = compute_desired_workers(backlog)
    autoscaler_desired_workers.set(desired)

    logger.info(
        "Autoscaler evaluation: queue_backlog=%d | desired_workers=%d (min=%d, max=%d, threshold=%d jobs/worker)",
        backlog,
        desired,
        settings.autoscaler_min_workers,
        settings.autoscaler_max_workers,
        settings.autoscaler_jobs_per_worker,
    )
    return backlog, desired


def run_autoscaler(poll_interval: float = 5.0) -> None:
    logger.info("Worker Autoscaler started (interval=%.1fs)", poll_interval)
    while not STOP_REQUESTED:
        try:
            with SessionLocal() as session:
                autoscale_step(session)
        except Exception as exc:
            logger.error("Error during autoscaler evaluation: %s", exc)
        time.sleep(poll_interval)


if __name__ == "__main__":
    run_autoscaler()
