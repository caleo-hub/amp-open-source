from __future__ import annotations

import time
import uuid

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.prebuilt import ToolNode

from .models import get_fast_model, get_router_model, get_smart_model
from .prompts import FAST_SYSTEM_PROMPT, ROUTER_SYSTEM_PROMPT, SMART_SYSTEM_PROMPT
from .state import AgentState, ModelProfile
from ..observability.sanitize import safe_error
from ..persistence.runtime import assert_execution_active, consume_budget, record_event
from ..tools import pesquisar_web, system_status
from ..tools.policy import TOOL_REGISTRY, allowed_tool_names

router_model = get_router_model()
smart_model = get_smart_model()
tool_node = ToolNode([system_status, pesquisar_web])


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


def guarded_tool_node(state: AgentState):
    execution_id = _execution_id(state)
    span_id, started = _start_node(state, "tools")
    try:
        policy = state.get("tool_policy") or allowed_tool_names(state.get("channel"))
        calls = getattr(state["messages"][-1], "tool_calls", [])
        denied = [call for call in calls if call.get("name") not in policy]
        if denied:
            if execution_id:
                for call in denied:
                    record_event(execution_id, "tool.failed", metadata={"reason": "policy_denied"}, tool_name=call.get("name"), parent_span_id=span_id, outcome="failed", error_code="policy_denied", is_retryable=False)
            result = {"messages": [ToolMessage(content="Essa ferramenta não está disponível neste canal.", tool_call_id=call.get("id", "denied-tool")) for call in denied]}
        else:
            tool_starts = {}
            tool_events = {}
            for call in calls:
                if execution_id:
                    assert_execution_active(execution_id)
                    used = consume_budget(execution_id, "tool")
                    tool_starts[call.get("id", call.get("name"))] = time.monotonic()
                    tool_events[call.get("id", call.get("name"))] = record_event(execution_id, "tool.started", metadata={"used_tool_calls": used}, tool_name=call.get("name"), span_id=uuid.uuid4(), parent_span_id=span_id)
            result = tool_node.invoke(state)
            if execution_id:
                for call in calls:
                    started_tool = tool_starts.get(call.get("id", call.get("name")))
                    record_event(execution_id, "tool.succeeded", metadata={}, tool_name=call.get("name"), span_id=(tool_events.get(call.get("id", call.get("name"))) or {}).get("span_id"), parent_span_id=span_id, duration_ms=((time.monotonic() - started_tool) * 1000 if started_tool else None), outcome="succeeded")
        _finish_node(execution_id, "tools", started, span_id)
        return result
    except Exception as exc:
        info = safe_error(exc, "tools", "tool_timeout" if "timeout" in type(exc).__name__.lower() else "tool_error", True)
        _finish_node(execution_id, "tools", started, span_id, "failed", info)
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


def fast_node(state: AgentState):
    execution_id = _execution_id(state)
    span_id, started = _start_node(state, "fast")
    try:
        policy = state.get("tool_policy") or allowed_tool_names(state.get("channel"))
        model = get_fast_model().bind_tools([TOOL_REGISTRY[name] for name in policy if name in TOOL_REGISTRY])
        response = _invoke_model(model, [SystemMessage(content=FAST_SYSTEM_PROMPT), *state["messages"]], execution_id, "fast", span_id)
        _finish_node(execution_id, "fast", started, span_id)
        return {"messages": [response]}
    except Exception as exc:
        info = safe_error(exc, "fast", "model_error", True)
        _finish_node(execution_id, "fast", started, span_id, "failed", info)
        raise


def smart_node(state: AgentState):
    execution_id = _execution_id(state)
    span_id, started = _start_node(state, "smart")
    try:
        response = _invoke_model(smart_model, [SystemMessage(content=SMART_SYSTEM_PROMPT), *state["messages"]], execution_id, "smart", span_id)
        _finish_node(execution_id, "smart", started, span_id)
        return {"messages": [response]}
    except Exception as exc:
        info = safe_error(exc, "smart", "model_error", True)
        _finish_node(execution_id, "smart", started, span_id, "failed", info)
        raise


def route_by_profile(state: AgentState) -> ModelProfile:
    return state["profile"]


def should_use_tool(state: AgentState) -> str:
    return "tools" if getattr(state["messages"][-1], "tool_calls", None) else "end"
