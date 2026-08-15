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


def build_graph():
    """
    Constrói o primeiro agente LangGraph do AMP.

    Fluxo:

                     ┌── FAST ── tool? ──┐
                     │          │         │
    START -> router ─┤          └─ tools ─┘
                     │
                     └── SMART ───────────> END

    O caminho FAST pode executar ferramentas e retornar ao modelo
    para que ele interprete o resultado.
    """

    builder = StateGraph(
        AgentState
    )

    # ---------------------------------------------------------------
    # Nodes
    # ---------------------------------------------------------------

    builder.add_node(
        "router",
        router_node,
    )

    builder.add_node(
        "fast",
        fast_node,
    )

    builder.add_node(
        "smart",
        smart_node,
    )

    builder.add_node(
        "tools",
        tool_node,
    )

    # ---------------------------------------------------------------
    # START -> router
    # ---------------------------------------------------------------

    builder.add_edge(
        START,
        "router",
    )

    # ---------------------------------------------------------------
    # router -> FAST / SMART
    # ---------------------------------------------------------------

    builder.add_conditional_edges(
        "router",
        route_by_profile,
        {
            "fast": "fast",
            "smart": "smart",
        },
    )

    # ---------------------------------------------------------------
    # FAST -> tools ou END
    # ---------------------------------------------------------------

    builder.add_conditional_edges(
        "fast",
        should_use_tool,
        {
            "tools": "tools",
            "end": END,
        },
    )

    # ---------------------------------------------------------------
    # tools -> FAST
    #
    # O modelo recebe o ToolMessage gerado pelo ToolNode e produz
    # uma resposta humana interpretando os dados.
    # ---------------------------------------------------------------

    builder.add_edge(
        "tools",
        "fast",
    )

    # ---------------------------------------------------------------
    # SMART -> END
    # ---------------------------------------------------------------

    builder.add_edge(
        "smart",
        END,
    )

    return builder.compile()


graph = build_graph()