# ADR 0001 — Princípios fundamentais da Agent Managed Platform

- Status: accepted
- Data: 2026-08-18
- Decisores: AMP maintainers

## Contexto

O runtime legado cresceu como uma aplicação única ligada ao laboratório doméstico. A nova AMP
precisa permitir evolução independente dos planos de controle, execução, modelos e ferramentas.

## Decisão

Adotamos um monorepo de microserviços com quatro princípios obrigatórios:

1. **Self-hosted por padrão:** componentes críticos e dados rodam na infraestrutura controlada.
2. **LangGraph-native:** agentes usam grafos, checkpoints, Store, streaming e HITL nativos.
3. **Ollama-first:** modelos locais são a rota padrão; APIs externas são opcionais e governadas.
4. **Provider-agnostic:** agentes recebem abstrações de modelos, tools, state e runtime; nunca
   credenciais ou infraestrutura de providers diretamente.

Control Plane e Data Plane são separados. Model Gateway e MCP Gateway são fronteiras obrigatórias.
Versões publicadas são imutáveis e side effects são auditáveis e idempotentes.

## Consequências

- O layout `src/amp_agent` e o Compose legado não são a base do novo sistema.
- Serviços e agentes podem ser testados e implantados de forma independente.
- Há custo inicial de contratos, registries e operação distribuída, aceito em troca de governança.
