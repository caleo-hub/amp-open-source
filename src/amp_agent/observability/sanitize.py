from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_SECRET_KEY = re.compile(r"(password|passwd|secret|token|api[_-]?key|authorization|cookie|dsn|private[_-]?key|credential)", re.I)
_URL_SECRET = re.compile(r"(https?://)([^/@\s]+):([^/@\s]+)@", re.I)
_MAX_STRING = 256
_MAX_METADATA_BYTES = 8 * 1024


def _sanitize(value: Any, key: str | None = None) -> Any:
    if key and _SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _sanitize(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return _URL_SECRET.sub(r"\1[REDACTED]@", value)[:_MAX_STRING]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:_MAX_STRING]


def sanitize_metadata(value: dict[str, Any] | None) -> dict[str, Any]:
    sanitized = _sanitize(value or {})
    if not isinstance(sanitized, dict):
        sanitized = {"value": sanitized}
    if len(json.dumps(sanitized, ensure_ascii=False, separators=(",", ":")).encode()) > _MAX_METADATA_BYTES:
        return {"metadata_truncated": True}
    return sanitized


def fingerprint_error(operation: str, error_code: str, exc: Exception | None = None) -> str:
    material = f"{operation}:{error_code}:{type(exc).__name__ if exc else 'unknown'}"
    return hashlib.sha256(material.encode()).hexdigest()[:24]


def safe_error(exc: Exception, operation: str, error_code: str, retryable: bool) -> dict[str, Any]:
    return {"error_code": error_code, "error_class": type(exc).__name__, "is_retryable": retryable, "fingerprint": fingerprint_error(operation, error_code, exc)}
