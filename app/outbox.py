from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.broker import QueueMessage, broker
from app.config import get_settings
from app.database import SessionLocal
from app.models import OutboxEvent, utcnow
from app.observability import outbox_events_failed_total, outbox_events_relayed_total

settings = get_settings()
logger = logging.getLogger("dtp.outbox")


def create_outbox_event(db: Session, event_type: str, payload: dict[str, Any]) -> OutboxEvent:
    """Creates an outbox event within the caller's active database transaction."""
    event = OutboxEvent(
        event_type=event_type,
        payload_json=json.dumps(payload, separators=(",", ":"), sort_keys=True),
        status="pending",
        retry_count=0,
    )
    db.add(event)
    return event


def relay_outbox_events(db: Session, batch_size: int = 50) -> int:
    """Relays pending outbox events to the message broker with exactly-once / at-least-once guarantee."""
    query = (
        select(OutboxEvent)
        .where(OutboxEvent.status == "pending")
        .order_by(OutboxEvent.created_at.asc())
        .limit(batch_size)
    )

    dialect_name = db.get_bind().dialect.name if db.get_bind() else "sqlite"
    if dialect_name == "postgresql":
        query = query.with_for_update(skip_locked=True)
        events = db.scalars(query).all()
    else:
        events = db.scalars(query).all()

    if not events:
        return 0

    relayed_count = 0
    for event in events:
        try:
            payload = event.payload
            queue_name = payload.get("queue_name", settings.queue_name)
            priority = int(payload.get("priority", 5))
            correlation_id = payload.get("correlation_id")

            from app.tracing import inject_trace_headers, trace_span
            headers = inject_trace_headers({"correlation_id": correlation_id or ""})

            msg = QueueMessage(
                job_id=payload["job_id"],
                event=payload.get("event", "process"),
                correlation_id=correlation_id,
                priority=priority,
                headers=headers,
            )

            with trace_span("outbox.publish_event", attributes={"event.id": event.id, "job.id": payload["job_id"]}):
                if settings.enable_rabbitmq:
                    published = broker.publish(msg, queue_name=queue_name)
                    if published:
                        event.status = "published"
                        event.published_at = utcnow()
                        event.last_error = None
                        outbox_events_relayed_total.inc()
                        relayed_count += 1
                    else:
                        event.retry_count += 1
                        event.last_error = "Broker publish returned False"
                        if event.retry_count >= settings.outbox_max_retries:
                            event.status = "failed"
                            outbox_events_failed_total.inc()
                else:
                    event.status = "published"
                    event.published_at = utcnow()
                    event.last_error = None
                    outbox_events_relayed_total.inc()
                    relayed_count += 1
        except Exception as exc:
            event.retry_count += 1
            event.last_error = str(exc)
            if event.retry_count >= settings.outbox_max_retries:
                event.status = "failed"
                outbox_events_failed_total.inc()
            logger.error("Failed to relay outbox event %s: %s", event.id, exc)

        db.add(event)

    db.commit()
    return relayed_count


def process_outbox_once() -> int:
    with SessionLocal() as session:
        return relay_outbox_events(session)
