import json

from langchain_core.tools import tool

from ..services.system import get_system_status
from ..services.searxng import search_web


@tool
def system_status() -> str:
    """
    Retorna o estado determinístico da API AMP e do Ollama.

    Use esta ferramenta para consultas de saúde do servidor AMP.
    Ela não fornece telemetria de RAM, disco ou GPU do host.
    """
    return json.dumps(
        get_system_status(),
        ensure_ascii=False,
        indent=2,
    )

@tool
def pesquisar_web(query: str) -> str:
    """
    Pesquisa informações atuais na web.

    Use quando a resposta depender de informações recentes,
    eventos atuais ou fatos que possam ter mudado.

    Retorna resultados com título, URL e resumo curto.
    """
    return json.dumps(
        search_web(query),
        ensure_ascii=False,
        indent=2,
    )