from langchain.agents import create_agent
from langgraph.graph import END, START, StateGraph

from .middleware import RuntimeAgentMiddleware
from .models import get_fast_model
from .prompts import FAST_SYSTEM_PROMPT
from .state import AgentState
from ..tools.policy import TOOL_REGISTRY


def build_graph(checkpointer=None, store=None):
    agent = create_agent(
        model=get_fast_model(),
        tools=list(TOOL_REGISTRY.values()),
        system_prompt=FAST_SYSTEM_PROMPT,
        middleware=[RuntimeAgentMiddleware()],
        state_schema=AgentState,
        name="amp_native_agent",
    )
    builder = StateGraph(AgentState)
    builder.add_node("agent", agent)
    builder.add_edge(START, "agent")
    builder.add_edge("agent", END)
    return builder.compile(checkpointer=checkpointer, store=store)


# CLI/local compatibility: no database is required outside the worker.
graph = build_graph()
