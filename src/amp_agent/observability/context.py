from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator


_context: ContextVar[dict[str, Any]] = ContextVar("amp_observability_context", default={})


def current_context() -> dict[str, Any]:
    """Return a copy of the correlation context for the current task or thread."""
    return dict(_context.get())


@contextmanager
def bind_context(**values: Any) -> Iterator[None]:
    """Temporarily add non-null correlation values to structured logs."""
    additions = {key: value for key, value in values.items() if value is not None}
    token = _context.set({**_context.get(), **additions})
    try:
        yield
    finally:
        _context.reset(token)
