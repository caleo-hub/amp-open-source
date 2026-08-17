from __future__ import annotations

import time
import uuid

from langchain_core.messages import HumanMessage, SystemMessage

from .models import get_router_model
from .prompts import ROUTER_SYSTEM_PROMPT
from .state import AgentState
from ..observability.sanitize import safe_error
from ..persistence.runtime import assert_execution_active, consume_budget, record_event

router_model = get_router_model()


def _execution_id(state: AgentState):
    value = state.get("execution_id")
    return uuid.UUID(str(value)) if value else None


def _start_node(state: AgentState, name: str):
    execution_id = _execution_id(state)
    if not execution_id:
        return None, None
    assert_execution_active(execution_id)
    used = consume_budget(execution_id, "step")
    event = record_event(execution_id, "node.started", metadata={"node": name, "used_steps": used}, node_name=name, span_id=uuid.uuid4())
    return event["span_id"], time.monotonic()


def _finish_node(execution_id, name: str, started: float | None, span_id, outcome: str = "succeeded", error: dict | None = None):
    if not execution_id:
        return
    metadata = {"node": name}
    if error:
        metadata.update(error)
    record_event(execution_id, f"node.{outcome}", metadata=metadata, node_name=name, span_id=span_id, parent_span_id=span_id, duration_ms=((time.monotonic() - started) * 1000 if started else None), outcome=outcome, error_code=(error or {}).get("error_code"))


def _invoke_model(model, messages, execution_id, model_name: str, parent_span_id=None):
    if not execution_id:
        return model.invoke(messages)
    assert_execution_active(execution_id)
    started = time.monotonic()
    start_event = record_event(execution_id, "model.started", metadata={}, model_name=model_name, span_id=uuid.uuid4(), parent_span_id=parent_span_id)
    try:
        response = model.invoke(messages)
        usage = getattr(response, "usage_metadata", {}) or {}
        record_event(execution_id, "model.succeeded", metadata={}, model_name=model_name, span_id=start_event["span_id"], parent_span_id=start_event["span_id"], duration_ms=(time.monotonic() - started) * 1000, outcome="succeeded", input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"))
        assert_execution_active(execution_id)
        return response
    except Exception as exc:
        info = safe_error(exc, model_name, "model_timeout" if "timeout" in type(exc).__name__.lower() else "model_error", True)
        record_event(execution_id, "model.timed_out" if info["error_code"] == "model_timeout" else "model.failed", metadata={}, model_name=model_name, span_id=start_event["span_id"], parent_span_id=start_event["span_id"], duration_ms=(time.monotonic() - started) * 1000, outcome="failed", error_code=info["error_code"], is_retryable=True, error_fingerprint=info["fingerprint"])
        raise


def router_node(state: AgentState):
    execution_id = _execution_id(state)
    span_id, started = _start_node(state, "router")
    try:
        user_message = state["messages"][-1]
        response = _invoke_model(router_model, [SystemMessage(content=ROUTER_SYSTEM_PROMPT), HumanMessage(content=str(user_message.content))], execution_id, "router", span_id)
        profile = str(response.content).strip().lower()
        if profile not in {"fast", "smart"}:
            profile = "fast"
        _finish_node(execution_id, "router", started, span_id)
        return {"profile": profile}
    except Exception as exc:
        info = safe_error(exc, "router", "model_error", True)
        _finish_node(execution_id, "router", started, span_id, "failed", info)
        raise
