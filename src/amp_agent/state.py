from typing import Annotated, Literal

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


ModelProfile = Literal["fast", "smart"]


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    profile: ModelProfile