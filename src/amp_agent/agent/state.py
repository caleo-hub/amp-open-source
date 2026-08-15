from typing import Annotated, Literal

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


ModelProfile = Literal["fast", "smart"]


class AgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    profile: ModelProfile
    state_version: int
    execution_id: str
    conversation_id: str
    input_message_id: str
    graph_version: str
    channel: str
    tool_policy: frozenset[str]
