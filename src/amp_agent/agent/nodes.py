from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import ToolNode

from .models import (
    get_fast_model,
    get_router_model,
    get_smart_model,
)
from .prompts import (
    FAST_SYSTEM_PROMPT,
    ROUTER_SYSTEM_PROMPT,
    SMART_SYSTEM_PROMPT,
)
from .state import AgentState, ModelProfile
from ..tools import pesquisar_web, system_status

# -------------------------------------------------------------------
# Modelos
# -------------------------------------------------------------------

router_model = get_router_model()

# FAST possui acesso às ferramentas.
fast_model = get_fast_model().bind_tools(
    [system_status, pesquisar_web]
)

# SMART, por enquanto, fica somente como modelo de análise.
smart_model = get_smart_model()


# -------------------------------------------------------------------
# Tool node
# -------------------------------------------------------------------

tool_node = ToolNode(
    [system_status, pesquisar_web]
)


# -------------------------------------------------------------------
# Router
# -------------------------------------------------------------------

def router_node(state: AgentState):
    """
    Decide se a solicitação deve utilizar FAST ou SMART.

    O router utiliza o próprio modelo FAST com uma geração muito curta.
    """

    user_message = state["messages"][-1]

    response = router_model.invoke(
        [
            SystemMessage(
                content=ROUTER_SYSTEM_PROMPT
            ),
            HumanMessage(
                content=str(user_message.content)
            ),
        ]
    )

    profile = str(response.content).strip().lower()

    if profile not in {"fast", "smart"}:
        print(
            f"[router] resposta inesperada: {profile!r}"
        )
        print("[router] fallback -> fast")

        profile = "fast"

    print(
        f"[router] perfil escolhido: {profile}"
    )

    return {
        "profile": profile,
    }


# -------------------------------------------------------------------
# FAST
# -------------------------------------------------------------------

def fast_node(state: AgentState):
    """
    Executa tarefas simples e pode chamar ferramentas.
    """

    print(
        "[model] FAST -> qwen3.5:2b-q4_K_M"
    )

    response = fast_model.invoke(
        [
            SystemMessage(
                content=FAST_SYSTEM_PROMPT
            ),
            *state["messages"],
        ]
    )

    return {
        "messages": [response],
    }


# -------------------------------------------------------------------
# SMART
# -------------------------------------------------------------------

def smart_node(state: AgentState):
    """
    Executa tarefas que exigem mais planejamento ou análise.
    """

    print(
        "[model] SMART -> qwen3.5:4b"
    )

    response = smart_model.invoke(
        [
            SystemMessage(
                content=SMART_SYSTEM_PROMPT
            ),
            *state["messages"],
        ]
    )

    return {
        "messages": [response],
    }


# -------------------------------------------------------------------
# Conditional edges
# -------------------------------------------------------------------

def route_by_profile(
    state: AgentState,
) -> ModelProfile:
    """
    Retorna o perfil escolhido pelo router.
    """

    return state["profile"]


def should_use_tool(
    state: AgentState,
) -> str:
    """
    Verifica se o último retorno do modelo contém uma chamada
    de ferramenta.

    FAST -> tool call -> tools
    FAST -> resposta normal -> END
    """

    last_message = state["messages"][-1]

    tool_calls = getattr(
        last_message,
        "tool_calls",
        None,
    )

    if tool_calls:
        print(
            f"[tool] chamadas solicitadas: "
            f"{len(tool_calls)}"
        )

        return "tools"

    return "end"