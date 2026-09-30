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
        
        jobs = due_scheduled_jobs(session)
        if not jobs:
            return 0
        job_ids = [job.id for job in jobs]
        stmt = (
            update(Job)
            .where(Job.id.in_(job_ids))
            .where(Job.status.in_(['scheduled', 'retrying']))
            .values(status='queued')
            .returning(Job.id, Job.queue_name)
        )
        result = session.execute(stmt).all()
        session.commit()
        
        count = 0
        for row in result:
            broker.publish(QueueMessage(job_id=row[0]), queue_name=row[1])
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

