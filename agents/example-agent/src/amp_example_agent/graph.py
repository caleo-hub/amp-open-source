from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class AgentState(TypedDict):
    message: str


def echo(state: AgentState) -> AgentState:
    return {"message": state["message"]}


builder = StateGraph(AgentState)
builder.add_node("echo", echo)
builder.add_edge(START, "echo")
builder.add_edge("echo", END)
graph = builder.compile()
