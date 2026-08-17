import json

from langchain_core.tools import tool
from langgraph.types import interrupt

from ..services.system import get_system_status
from ..services.searxng import search_web
from ..persistence.chat import list_notes, put_note
from ..persistence.repositories import get_default_workspace
try:
    from langchain.tools import ToolRuntime
except ImportError:
    ToolRuntime = object


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

@tool
def salvar_nota_local(note_key: str, content: str, runtime: ToolRuntime) -> str:
    """Salva uma nota local após aprovação humana."""
    note_key = " ".join(note_key.split())[:80]; content = content.strip()[:4000]
    if not note_key or not content: return "A nota precisa de uma chave e conteúdo não vazio."
    decision = interrupt({"type": "approval", "action": "salvar_nota_local", "tool": "salvar_nota_local", "arguments": {"note_key": note_key, "content": content}, "summary": f"Salvar a nota '{note_key}'?", "allowed_decisions": ["approve", "reject", "edit"]})
    decision = {"type": decision} if isinstance(decision, str) else (decision or {"type": "reject"})
    choice = decision.get("type", "reject")
    if choice == "reject": return "A gravação da nota foi rejeitada."
    if choice == "edit":
        edited = decision.get("arguments") or {}; note_key = " ".join(str(edited.get("note_key", note_key)).split())[:80]; content = str(edited.get("content", content)).strip()[:4000]
        if not note_key or not content: return "A edição foi rejeitada: chave e conteúdo são obrigatórios."
    state = getattr(runtime, "state", None); workspace_id = state.get("workspace_id") if isinstance(state, dict) else None
    workspace_id = workspace_id or (get_default_workspace() or {}).get("id")
    if not workspace_id: return "Workspace local indisponível."
    saved = put_note(workspace_id, note_key, content)
    return json.dumps({"saved": True, "note_key": saved["note_key"], "content": saved["content"]}, ensure_ascii=False)


@tool
def listar_notas_locais(runtime: ToolRuntime) -> str:
    """Lista notas locais salvas anteriormente neste workspace."""
    state = getattr(runtime, "state", None); workspace_id = state.get("workspace_id") if isinstance(state, dict) else None
    workspace_id = workspace_id or (get_default_workspace() or {}).get("id")
    if not workspace_id: return "Workspace local indisponível."
    return json.dumps(list_notes(workspace_id), ensure_ascii=False)
