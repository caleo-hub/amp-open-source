from typing import Literal

from langchain.agents import AgentState as LangChainAgentState
from typing_extensions import TypedDict


ModelProfile = Literal["fast", "smart"]


class AgentState(LangChainAgentState, total=False):
    profile: ModelProfile
    state_version: int
    execution_id: str
    conversation_id: str
    workspace_id: str
    input_message_id: str
    graph_version: str
    channel: str
    tool_policy: frozenset[str]
