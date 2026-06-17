from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session

from app.broker import QueueMessage, broker
from app.config import get_settings
from app.database import SessionLocal
from app.models import Job
from app.services import due_scheduled_jobs

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("dtp.scheduler")


def schedule_once() -> int:
    session: Session = SessionLocal()
    try:
        jobs = due_scheduled_jobs(session)
        count = 0
        for job in jobs:
            job.status = "queued"
            session.add(job)
            session.commit()
            broker.publish(QueueMessage(job_id=job.id), queue_name=job.queue_name)
            count += 1
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

