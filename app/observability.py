from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.responses import Response

from app.config import get_settings

settings = get_settings()

jobs_created_total = Counter(f"{settings.metrics_namespace}_jobs_created_total", "Jobs created")
jobs_completed_total = Counter(f"{settings.metrics_namespace}_jobs_completed_total", "Jobs completed")
jobs_failed_total = Counter(f"{settings.metrics_namespace}_jobs_failed_total", "Jobs failed")
jobs_retried_total = Counter(f"{settings.metrics_namespace}_jobs_retried_total", "Jobs retried")
worker_active_gauge = Gauge(f"{settings.metrics_namespace}_worker_active", "Active workers")
queue_length_gauge = Gauge(f"{settings.metrics_namespace}_queue_length", "Queue length")
job_processing_seconds = Histogram(
    f"{settings.metrics_namespace}_job_processing_seconds",
    "Job processing duration in seconds",
)


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

