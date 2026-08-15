# Fase 8 — Persistência durável

A Fase 8 usa PostgreSQL como fonte de verdade do domínio AMP, fila, inbox, eventos e outbox. O histórico de produto vive em `amp.messages`; os checkpoints internos do LangGraph vivem em `langgraph`.

## Inicialização

Crie o secret local do PostgreSQL sem adicioná-lo ao Git:

```bash
(umask 077; openssl rand -hex 32 > secrets/postgres_password.txt)
```

Suba os serviços e deixe a migração explícita concluir:

```bash
docker compose up -d amp-db
docker compose run --rm amp-migrate
docker compose up -d amp-api amp-worker
```

## Contratos

A API canônica é:

- `POST /v1/conversations`;
- `POST /v1/conversations/{id}/messages`;
- `GET /v1/executions/{id}`;
- `GET /v1/conversations/{id}/messages`.

`/chat` e `/voice` continuam como adaptadores compatíveis. Timeouts retornam `pending`; não são gravados como estado de execução.

## Backup e restauração

```bash
scripts/backup-postgres.sh
scripts/restore-postgres.sh backups/amp-postgres-<timestamp>.dump
```

Depois de restaurar, valide a continuidade de uma conversa usando `/v1/executions/{id}` e o histórico em `/v1/conversations/{id}/messages`.
