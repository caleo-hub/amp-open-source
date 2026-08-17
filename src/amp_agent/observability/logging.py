from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from opentelemetry import trace

from .context import current_context
from .sanitize import sanitize_metadata


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"timestamp": datetime.now(timezone.utc).isoformat(), "level": record.levelname.lower(), "service": record.name, "event": record.getMessage()}
        correlation = current_context()
        span = trace.get_current_span()
        span_context = span.get_span_context()
        if span_context.is_valid:
            correlation.setdefault("trace_id", format(span_context.trace_id, "032x"))
            correlation.setdefault("span_id", format(span_context.span_id, "016x"))
        context = getattr(record, "amp_context", None)
        if isinstance(context, dict):
            correlation.update(context)
        if correlation:
            payload.update(sanitize_metadata(correlation))
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

def configure_json_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger(); root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout); handler.setFormatter(JsonFormatter()); root.addHandler(handler)
    else:
        for handler in root.handlers: handler.setFormatter(JsonFormatter())

def log_event(logger: logging.Logger, event: str, **context: Any) -> None:
    logger.info(event, extra={"amp_context": context})
