# Convenções do monorepo AMP

## Layout e ownership

- `apps/`: interfaces para usuários e operadores.
- `services/`: microserviços do Control Plane e Data Plane.
- `agents/`: grafos LangGraph versionados e imutáveis quando publicados.
- `mcp-servers/`: capabilities expostas pelo protocolo MCP.
- `packages/`: contratos e bibliotecas compartilhadas, sem lógica de produto oculta.
- `deploy/`: containers, Kubernetes, Helm e GitOps.
- `docs/`: arquitetura, ADRs, contratos e operação.

O arquivo `.github/CODEOWNERS` define os responsáveis. Todo componente novo deve ter README,
manifesto de dependências, testes, health check quando for serviço e owner explícito antes do merge.

## Nomes

- Diretórios e containers: `kebab-case`.
- Pacotes Python: `amp_<nome>_<tipo>` em `snake_case`.
- Distribuições Python: `amp-<nome>-<tipo>`.
- Pacotes TypeScript: namespace `@amp/`.
- Serviços Kubernetes: `amp-<plane>-<capability>`.
- Variáveis de ambiente: prefixo `AMP_`; referências de providers preservam o nome oficial.

## Versões

Componentes usam SemVer. Uma `AgentVersion` publicada referencia commit Git, digest OCI, schema,
prompt, model policy e tool policy imutáveis. Mudança incompatível exige major; funcionalidade
compatível exige minor; correção compatível exige patch.

## Toolchain

- Python 3.12+, `uv`, Ruff, mypy estrito e pytest.
- TypeScript estrito, React, ESLint e Prettier.
- Execute `make bootstrap` uma vez e `make check` antes de abrir PR.

## Criar componentes

```bash
uv run python tools/scaffold.py service billing
uv run python tools/scaffold.py agent research
```

Os geradores recusam sobrescrita e nomes fora de `kebab-case`. Revise ownership, contratos,
dependências e Dockerfile antes de registrar o componente na plataforma.
