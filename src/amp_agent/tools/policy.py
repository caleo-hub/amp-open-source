"""Explicit tool access policy by ingress channel."""

from ..tools import listar_notas_locais, pesquisar_web, salvar_nota_local, system_status

TOOL_REGISTRY = {
    "system_status": system_status,
    "pesquisar_web": pesquisar_web,
    "salvar_nota_local": salvar_nota_local,
    "listar_notas_locais": listar_notas_locais,
}

CHANNEL_TOOL_POLICY = {
    "chat": frozenset(TOOL_REGISTRY),
    "ui": frozenset(TOOL_REGISTRY),
    "voice": frozenset({"system_status", "pesquisar_web"}),
}


def allowed_tool_names(channel: str | None) -> frozenset[str]:
    return CHANNEL_TOOL_POLICY.get(channel or "chat", frozenset())
