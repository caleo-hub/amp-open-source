# Plano de implementação — AMP Agent Managed Platform

> **Reset do projeto:** 2026-08-18  
> **Arquitetura canônica:** [`docs/architecture/agent-managed-platform-self-hosted-langgraph-ollama.md`](architecture/agent-managed-platform-self-hosted-langgraph-ollama.md)  
> **Roadmap executável:** [`docs/roadmap-agentic-workspace.md`](roadmap-agentic-workspace.md)

## Objetivo

Reconstruir a AMP do zero como uma **Agent Managed Platform self-hosted em microserviços**, usando LangGraph/LangChain como runtime nativo, Ollama como provider principal e LLM APIs externas apenas como capacidade opcional governada por política.

A nova implementação separa:

- **Control Plane** — agents, versions, prompts, models, MCPs, policies, deployments e evaluations;
- **Agent Data Plane** — threads, runs, workers, checkpoints, streaming e Human-in-the-Loop;
- **Model Plane** — Model Gateway, Ollama Router, Ollama pools e providers externos opcionais;
- **Tool Plane** — MCP Registry, MCP Gateway e MCP servers;
- **State & Data Plane** — PostgreSQL, Redis/Valkey, MinIO, vector store e event bus;
- **Observability Plane** — OpenTelemetry, Langfuse, Prometheus/Grafana, Loki e Tempo.

## Decisões fundamentais

1. **Self-hosted por padrão.** O caminho principal deve funcionar sem LLM cloud.
2. **Ollama-first.** O agente não instancia providers diretamente; recebe um modelo resolvido pelo Model Gateway.
3. **LangGraph-native.** `StateGraph`, `create_agent`, checkpointers, Store, subgraphs, `interrupt()` e streaming são primitivas do runtime.
4. **Microserviços por responsabilidade.** Control Plane, runtime, modelos, tools, conhecimento, approvals e observabilidade evoluem separadamente.
5. **Versionamento imutável.** AgentVersion publicada referencia commit, digest OCI, prompt version, model policy, tool policy e schemas.
6. **MCP como fronteira de capabilities.** Agentes não recebem acesso genérico a rede, banco ou filesystem.
7. **Persistência durável.** PostgreSQL é a fonte de verdade para estado crítico; Redis/Valkey é apoio efêmero.
8. **Segurança por capability e identidade.** Keycloak + RBAC/ABAC + deny-by-default + approvals para side effects.
9. **Observabilidade não é runtime.** Langfuse e OpenTelemetry observam; não são dependências para o grafo existir.
10. **Produção por artifacts OCI.** Git -> CI -> tests/evals -> OCI -> registry -> deployment controller -> Kubernetes.

## Plano de execução

O trabalho oficial está dividido nas seguintes fases:

- [Fase 0 — Reset do projeto e monorepo da AMP (#35)](https://github.com/caleo-hub/amp-open-source/issues/35)
- [Fase 1 — Fundação de infraestrutura, dados e contratos (#36)](https://github.com/caleo-hub/amp-open-source/issues/36)
- [Fase 2 — Model Plane Ollama-first e LLM APIs opcionais (#37)](https://github.com/caleo-hub/amp-open-source/issues/37)
- [Fase 3 — Runtime LangGraph e execução durável (#38)](https://github.com/caleo-hub/amp-open-source/issues/38)
- [Fase 4 — Run Gateway, scheduler e protocolo de execução (#39)](https://github.com/caleo-hub/amp-open-source/issues/39)
- [Fase 5 — Control Plane, Agent Registry e configuração versionada (#40)](https://github.com/caleo-hub/amp-open-source/issues/40)
- [Fase 6 — Tool Plane com MCP Registry e MCP Gateway (#41)](https://github.com/caleo-hub/amp-open-source/issues/41)
- [Fase 7 — Identidade, políticas, HITL, secrets e auditoria (#42)](https://github.com/caleo-hub/amp-open-source/issues/42)
- [Fase 8 — Knowledge Service, RAG e memória (#43)](https://github.com/caleo-hub/amp-open-source/issues/43)
- [Fase 9 — Web Console, playground e SDKs da plataforma (#44)](https://github.com/caleo-hub/amp-open-source/issues/44)
- [Fase 10 — Observabilidade, avaliação e promotion gates (#45)](https://github.com/caleo-hub/amp-open-source/issues/45)
- [Fase 11 — Kubernetes, CI/CD, HA, autoscaling e operação enterprise (#46)](https://github.com/caleo-hub/amp-open-source/issues/46)

## Estratégia de desenvolvimento

### Primeiro: ambiente local reproduzível

A implementação começa com microserviços executáveis localmente via Docker Compose. Isso permite desenvolver e testar os contratos sem exigir Kubernetes desde o primeiro commit.

### Depois: vertical slice do runtime

Antes de construir todo o painel, a plataforma precisa provar este fluxo:

```text
Client
  -> Run Gateway
  -> Scheduler
  -> LangGraph Runtime
  -> Model Gateway
  -> Ollama
  -> PostgreSQL checkpoint/store
  -> SSE response
```

O primeiro gate real é um agente que:

- cria/retoma uma thread;
- chama Ollama por meio do Model Gateway;
- usa structured output;
- persiste checkpoints;
- emite streaming;
- sobrevive a restart.

### Depois: management plane

Com o runtime estável, entram:

- Agent Registry;
- Prompt Config Service;
- Model Registry;
- MCP Registry;
- políticas;
- approvals;
- knowledge;
- console web.

### Por fim: produção Kubernetes

Somente depois que os contratos estiverem estáveis o target de produção passa a incluir:

- Helm;
- Argo CD;
- Harbor;
- Deployment Controller;
- NetworkPolicies;
- GPU/Ollama pools;
- HPA/KEDA;
- canary/rollback;
- HA;
- multi-tenancy;
- disaster recovery;
- air-gapped release bundle.

## Estrutura alvo do repositório

```text
amp-open-source/
├── apps/
│   └── web-console/
├── services/
│   ├── platform-api/
│   ├── agent-registry/
│   ├── prompt-config-service/
│   ├── deployment-controller/
│   ├── run-gateway/
│   ├── run-scheduler/
│   ├── model-registry/
│   ├── model-gateway/
│   ├── ollama-router/
│   ├── mcp-registry/
│   ├── mcp-gateway/
│   ├── knowledge-service/
│   ├── approval-service/
│   ├── evaluation-service/
│   └── audit-service/
├── agents/
├── mcp-servers/
├── packages/
│   ├── amp-agent-sdk/
│   ├── amp-model-runtime/
│   ├── amp-mcp-sdk/
│   ├── amp-observability/
│   ├── amp-security/
│   └── amp-contracts/
├── deploy/
│   ├── helm/
│   ├── argocd/
│   ├── keycloak/
│   ├── observability/
│   └── policies/
└── docs/
    └── architecture/
```

## Stack de referência

### Aplicação

- Python 3.12+
- FastAPI
- LangGraph
- LangChain
- `langchain-ollama`
- `langchain-mcp-adapters`
- Pydantic

### Dados

- PostgreSQL
- Redis/Valkey
- MinIO
- pgvector inicialmente; Qdrant opcional depois
- NATS JetStream quando a distribuição/eventos exigirem

### Segurança

- Keycloak
- OpenBao/Vault-compatible
- OPA opcional
- NetworkPolicy deny-by-default

### Observabilidade

- OpenTelemetry Collector
- Langfuse self-hosted
- Prometheus
- Grafana
- Loki
- Tempo

### Produção

- Kubernetes
- Helm
- Argo CD
- Harbor

## Regra para novos issues

Novos issues devem nascer como subproblemas das fases #35–#46, e não como uma segunda sequência paralela de roadmap. Cada issue deve possuir:

- objetivo;
- tarefas verificáveis;
- entregável;
- critério de pronto;
- dependências;
- referência arquitetural quando relevante.

## Histórico anterior

O roadmap anterior foi descontinuado. Issues antigos permanecem fechados no GitHub apenas para preservar histórico; não devem ser usados para guiar a nova implementação.
