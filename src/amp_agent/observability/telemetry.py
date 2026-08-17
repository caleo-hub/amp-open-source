from __future__ import annotations

from contextlib import contextmanager
import os
from collections.abc import Iterator
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import Span


_configured = False
_instrumented_clients = False


def _enabled() -> bool:
    return os.getenv("OTEL_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def configure_telemetry(service_name: str) -> bool:
    """Configure one process once; return whether OTLP export is active."""
    global _configured, _instrumented_clients
    if _configured:
        return _enabled()
    _configured = True
    if not _enabled():
        return False

    resource = Resource.create(
        {
            "service.name": os.getenv("OTEL_SERVICE_NAME", service_name),
            "service.version": os.getenv("AMP_AGENT_VERSION", "0.1.0"),
            "deployment.environment": os.getenv("AMP_ENVIRONMENT", "local"),
        }
    )
    try:
        sampling_ratio = min(
            1.0,
            max(0.0, float(os.getenv("OTEL_TRACE_SAMPLING_RATIO", "1"))),
        )
    except ValueError:
        sampling_ratio = 1.0
    provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(TraceIdRatioBased(sampling_ratio)),
    )
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    exporter = OTLPSpanExporter(endpoint=endpoint) if endpoint else OTLPSpanExporter()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    if not _instrumented_clients:
        HTTPXClientInstrumentor().instrument()
        PsycopgInstrumentor().instrument()
        _instrumented_clients = True
    return True


def instrument_fastapi(app: Any) -> None:
    """Instrument a FastAPI application after its routes are registered."""
    if not _enabled():
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor().instrument_app(app)


@contextmanager
def execution_span(
    execution_id: str,
    job_id: str,
    attempt: int | None = None,
) -> Iterator[Span]:
    """Create a safe root span for one worker execution.

    Only stable identifiers and control-plane metadata are attached. Prompt,
    response, tool arguments and tool results remain outside telemetry.
    """
    tracer = trace.get_tracer("amp-agent.runtime")
    attributes = {
        "amp.execution_id": execution_id,
        "amp.job_id": job_id,
    }
    if attempt is not None:
        attributes["amp.attempt"] = attempt
    with tracer.start_as_current_span(
        "amp.execution",
        attributes=attributes,
    ) as span:
        yield span
