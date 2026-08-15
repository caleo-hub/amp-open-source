import json

from langchain_core.tools import tool

from .system import get_system_status


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
