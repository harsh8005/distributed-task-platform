from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session
from sqlalchemy import update

from app.broker import QueueMessage, broker
from app.config import get_settings
from app.database import SessionLocal
from app.models import Job
from app.services import due_scheduled_jobs, recover_orphaned_jobs

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("dtp.scheduler")


def schedule_once() -> int:
    session: Session = SessionLocal()
    try:
        recovered = recover_orphaned_jobs(session)
        if recovered:
            logger.info("Recovered %s orphaned jobs", recovered)
        
        from app.outbox import create_outbox_event, relay_outbox_events
        relayed = relay_outbox_events(session)
        if relayed:
            logger.info("Relayed %s pending outbox events", relayed)

        jobs = due_scheduled_jobs(session)
        if not jobs:
            return 0

        count = 0
        for job in jobs:
            job.status = "queued"
            create_outbox_event(
                session,
                event_type="job.scheduled_release",
                payload={
                    "job_id": job.id,
                    "queue_name": job.queue_name,
                    "priority": job.priority,
                    "correlation_id": job.correlation_id,
                },
            )
            session.add(job)
            count += 1

        session.commit()
        relay_outbox_events(session)
        return count
    finally:
        session.close()


def main() -> None:
    logger.info("Scheduler started")
    while True:
        count = schedule_once()
        if count:
            logger.info("Released %s scheduled jobs", count)
        time.sleep(settings.scheduler_poll_interval_seconds)


if __name__ == "__main__":
    main()

