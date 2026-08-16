from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from ..persistence.repositories import list_history

HISTORY_POLICY_VERSION = "recent-v1"


def build_history(conversation_id, before_sequence: int, max_messages: int = 20, max_estimated_tokens: int = 6000) -> tuple[list, dict]:
    rows = list_history(conversation_id, before_sequence, max_messages, max_estimated_tokens)
    messages = []
    for row in rows:
        role = row["role"]
        if role == "user":
            messages.append(HumanMessage(content=row["content"]))
        elif role == "assistant":
            messages.append(AIMessage(content=row["content"]))
        elif role == "tool":
            messages.append(ToolMessage(content=row["content"], tool_call_id="history"))
        elif role == "system":
            messages.append(SystemMessage(content=row["content"]))
    return messages, {
        "history_policy_version": HISTORY_POLICY_VERSION,
        "history_used_messages": len(messages),
        "history_estimated_tokens": sum(max(1, (len(str(m.content)) + 3) // 4) for m in messages),
    }
