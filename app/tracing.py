from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger("dtp.tracing")

_TRACING_INITIALIZED = False


def setup_telemetry(service_name: str | None = None) -> None:
    global _TRACING_INITIALIZED
    if _TRACING_INITIALIZED or not settings.enable_otel:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        svc_name = service_name or settings.app_name
        resource = Resource.create({"service.name": svc_name, "environment": settings.environment})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=settings.otlp_endpoint)
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
        _TRACING_INITIALIZED = True
        logger.info("OpenTelemetry initialized for service '%s' pointing to %s", svc_name, settings.otlp_endpoint)
    except Exception as exc:
        logger.warning("Failed to initialize OpenTelemetry: %s", exc)


def instrument_fastapi_app(app) -> None:
    if not settings.enable_otel:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
        logger.info("FastAPI OpenTelemetry instrumentation active")
    except Exception as exc:
        logger.warning("Failed to instrument FastAPI with OpenTelemetry: %s", exc)


def get_tracer(name: str = "dtp.tracer"):
    from opentelemetry import trace
    return trace.get_tracer(name)


def inject_trace_headers(headers: dict[str, str] | None = None) -> dict[str, str]:
    """Injects current W3C trace context into headers dictionary for cross-service propagation."""
    out = dict(headers or {})
    if not settings.enable_otel:
        return out
    try:
        from opentelemetry import trace
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

        TraceContextTextMapPropagator().inject(out)
    except Exception:
        pass
    return out


def extract_trace_context(headers: dict[str, str] | None = None):
    """Extracts W3C trace context from headers dictionary."""
    if not headers or not settings.enable_otel:
        return None
    try:
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

        return TraceContextTextMapPropagator().extract(headers)
    except Exception:
        return None


@contextmanager
def trace_span(name: str, attributes: dict | None = None, parent_context=None) -> Generator:
    """Convenience context manager for creating an OpenTelemetry trace span."""
    if not settings.enable_otel:
        yield None
        return

    try:
        from opentelemetry import trace

        tracer = get_tracer()
        with tracer.start_as_current_span(name, context=parent_context, attributes=attributes or {}) as span:
            yield span
    except Exception:
        yield None
