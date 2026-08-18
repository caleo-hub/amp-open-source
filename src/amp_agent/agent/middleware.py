from __future__ import annotations

import time
import uuid
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ToolCallRequest
from langchain_core.messages import SystemMessage

from .models import get_fast_model
from .prompts import FAST_SYSTEM_PROMPT
from .state import AgentState
from ..observability.sanitize import safe_error
from ..persistence.runtime import assert_execution_active, consume_budget, record_event
from ..tools.policy import allowed_tool_names


def _execution_id(state: dict[str, Any]) -> uuid.UUID | None:
    value = state.get("execution_id")
    return uuid.UUID(str(value)) if value else None


def _tool_name(tool: Any) -> str | None:
    if isinstance(tool, dict):
        return tool.get("name") or (tool.get("function") or {}).get("name")
    return getattr(tool, "name", None)


class RuntimeAgentMiddleware(AgentMiddleware):
    """Apply AMP runtime policy around the native LangChain agent loop."""

    state_schema = AgentState

    def __init__(self) -> None:
        super().__init__()
        self.fast_model = get_fast_model()

    def _prepare_model_request(self, request: ModelRequest):
        profile = "fast"
        model = self.fast_model
        prompt = FAST_SYSTEM_PROMPT
        allowed = allowed_tool_names(request.state.get("channel"))
        tools = [tool for tool in request.tools if _tool_name(tool) in allowed]
        return profile, request.override(
            model=model,
            system_message=SystemMessage(content=prompt),
            tools=tools,
        )

    def _start_model(self, state: dict[str, Any], profile: str):
        execution_id = _execution_id(state)
        if execution_id is None:
            return None
        assert_execution_active(execution_id)
        used = consume_budget(execution_id, "step")
        node_span = uuid.uuid4()
        model_span = uuid.uuid4()
        record_event(
            execution_id,
            "node.started",
            metadata={"node": "agent", "profile": profile, "used_steps": used},
            node_name="agent",
            span_id=node_span,
        )
        record_event(
            execution_id,
            "model.started",
            metadata={"profile": profile},
            model_name=profile,
            span_id=model_span,
            parent_span_id=node_span,
        )
        return execution_id, node_span, model_span, time.monotonic()

    @staticmethod
    def _finish_model(started, response=None, error: Exception | None = None) -> None:
        if started is None:
            return
        execution_id, node_span, model_span, began = started
        duration_ms = (time.monotonic() - began) * 1000
        if error is not None:
            info = safe_error(
                error,
                "agent",
                "model_timeout" if "timeout" in type(error).__name__.lower() else "model_error",
                True,
            )
            record_event(
                execution_id,
                "model.timed_out" if info["error_code"] == "model_timeout" else "model.failed",
                metadata={},
                model_name="agent",
                span_id=model_span,
                parent_span_id=node_span,
                duration_ms=duration_ms,
                outcome="failed",
                error_code=info["error_code"],
                is_retryable=True,
                error_fingerprint=info["fingerprint"],
            )
            record_event(
                execution_id,
                "node.failed",
                metadata={"node": "agent"},
                node_name="agent",
                span_id=node_span,
                parent_span_id=node_span,
                duration_ms=duration_ms,
                outcome="failed",
                error_code=info["error_code"],
            )
            return

        messages = getattr(response, "result", []) or []
        usage = getattr(messages[-1], "usage_metadata", {}) or {} if messages else {}
        record_event(
            execution_id,
            "model.succeeded",
            metadata={},
            model_name="agent",
            span_id=model_span,
            parent_span_id=node_span,
            duration_ms=duration_ms,
            outcome="succeeded",
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )
        record_event(
            execution_id,
            "node.succeeded",
            metadata={"node": "agent"},
            node_name="agent",
            span_id=node_span,
            parent_span_id=node_span,
            duration_ms=duration_ms,
            outcome="succeeded",
        )
        assert_execution_active(execution_id)

    def wrap_model_call(self, request: ModelRequest, handler):
        profile, prepared = self._prepare_model_request(request)
        started = self._start_model(request.state, profile)
        try:
            response = handler(prepared)
        except Exception as exc:
            self._finish_model(started, error=exc)
            raise
        self._finish_model(started, response=response)
        return response

    async def awrap_model_call(self, request: ModelRequest, handler):
        profile, prepared = self._prepare_model_request(request)
        started = self._start_model(request.state, profile)
        try:
            response = await handler(prepared)
        except Exception as exc:
            self._finish_model(started, error=exc)
            raise
        self._finish_model(started, response=response)
        return response

    @staticmethod
    def _start_tool(request: ToolCallRequest):
        execution_id = _execution_id(request.state)
        if execution_id is None:
            return None
        assert_execution_active(execution_id)
        used = consume_budget(execution_id, "tool")
        name = request.tool_call.get("name", "unknown")
        span_id = uuid.uuid4()
        record_event(
            execution_id,
            "tool.started",
            metadata={"used_tool_calls": used},
            tool_name=name,
            span_id=span_id,
        )
        return execution_id, name, span_id, time.monotonic()

    @staticmethod
    def _finish_tool(started, error: Exception | None = None) -> None:
        if started is None:
            return
        execution_id, name, span_id, began = started
        duration_ms = (time.monotonic() - began) * 1000
        if error is None:
            record_event(
                execution_id,
                "tool.succeeded",
                metadata={},
                tool_name=name,
                span_id=span_id,
                duration_ms=duration_ms,
                outcome="succeeded",
            )
            assert_execution_active(execution_id)
            return
        info = safe_error(
            error,
            name,
            "tool_timeout" if "timeout" in type(error).__name__.lower() else "tool_error",
            True,
        )
        record_event(
            execution_id,
            "tool.failed",
            metadata={},
            tool_name=name,
            span_id=span_id,
            duration_ms=duration_ms,
            outcome="failed",
            error_code=info["error_code"],
            is_retryable=True,
            error_fingerprint=info["fingerprint"],
        )

    def wrap_tool_call(self, request: ToolCallRequest, handler):
        started = self._start_tool(request)
        try:
            result = handler(request)
        except Exception as exc:
            self._finish_tool(started, error=exc)
            raise
        self._finish_tool(started)
        return result

    async def awrap_tool_call(self, request: ToolCallRequest, handler):
        started = self._start_tool(request)
        try:
            result = await handler(request)
        except Exception as exc:
            self._finish_tool(started, error=exc)
            raise
        self._finish_tool(started)
        return result
