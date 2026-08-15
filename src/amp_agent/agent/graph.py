from langgraph.graph import END, START, StateGraph

from .nodes import (
    fast_node,
    route_by_profile,
    router_node,
    should_use_tool,
    smart_node,
    tool_node,
)
from .state import AgentState


def build_graph(checkpointer=None):
    builder = StateGraph(AgentState)
    builder.add_node("router", router_node)
    builder.add_node("fast", fast_node)
    builder.add_node("smart", smart_node)
    builder.add_node("tools", tool_node)
    builder.add_edge(START, "router")
    builder.add_conditional_edges(
        "router",
        route_by_profile,
        {"fast": "fast", "smart": "smart"},
    )
    builder.add_conditional_edges(
        "fast",
        should_use_tool,
        {"tools": "tools", "end": END},
    )
    builder.add_edge("tools", "fast")
    builder.add_edge("smart", END)
    return builder.compile(checkpointer=checkpointer)


# CLI/local compatibility: no database is required outside the worker.
graph = build_graph()
