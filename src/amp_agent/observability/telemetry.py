from __future__ import annotations

from contextlib import contextmanager
import os
from collections.abc import Iterator
from typing import Any

from opentelemetry import baggage, context, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import Span


_configured = False
_instrumented_clients = False


class LangfuseTraceAttributeProcessor(SpanProcessor):
    """Copy Langfuse trace attributes from baggage to every child span."""

    _keys = (
        "langfuse.session.id",
        "langfuse.trace.name",
        "langfuse.version",
        "langfuse.environment",
    )

    def on_start(self, span: ReadableSpan, parent_context=None) -> None:
        for key in self._keys:
            value = baggage.get_baggage(key, context=parent_context)
            if value is not None:
                span.set_attribute(key, value)

    def on_end(self, span: ReadableSpan) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


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
    provider.add_span_processor(LangfuseTraceAttributeProcessor())
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
    conversation_id: str | None = None,
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
    if conversation_id:
        attributes["langfuse.session.id"] = conversation_id
        attributes["langfuse.trace.name"] = "amp.execution"
    baggage_context = context.get_current()
    for key, value in (
        ("langfuse.session.id", conversation_id),
        ("langfuse.trace.name", "amp.execution"),
    ):
        if value:
            baggage_context = baggage.set_baggage(key, value, context=baggage_context)
    token = context.attach(baggage_context)
    try:
        with tracer.start_as_current_span(
            "amp.execution",
            attributes=attributes,
        ) as span:
            yield span
    finally:
        context.detach(token)
