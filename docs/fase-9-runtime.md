# Fase 9 — Runtime observável, limitado e controlável

## Fronteiras

`Workspace` é a fronteira superior da instalação. A Fase 9 cria somente o
workspace bootstrap `local`; `Space` será o contexto de trabalho da Fase 12.
`Agent` é uma identidade estável e cada configuração executável é uma versão
imutável.

## Estados

Execuções usam `queued`, `running`, `waiting_approval` (reservado), `succeeded`,
`failed` e `cancelled`. Jobs usam `queued`, `running`, `retry`,
`waiting_approval` (reservado), `succeeded`, `dead` e `cancelled`.
Cancelamento é ortogonal ao estado: `cancel_requested_at`,
`cancel_effective_at`, `cancel_reason` e `cancel_requested_by`.

Toda transição passa pelo repositório de estados, bloqueando execução, job e,
quando necessário, conversa nessa ordem. A transição e o evento de lifecycle
são uma única transação. Estados terminais são irreversíveis; um lease perdido
impede qualquer escrita posterior do worker antigo.

## Eventos v1

Eventos são append-only, ordenados por `sequence_no` dentro da execução e
possuem `schema_version`, `category`, timestamps, span/causalidade, tentativa,
resultado, erro seguro, tokens e metadata sanitizada. O span da execução é a
raiz; nós, modelos e ferramentas são filhos. Conteúdo de prompts, respostas,
argumentos e resultados nunca entra na telemetria.

Logs JSON recebem automaticamente o contexto corrente por `ContextVar`.
OpenTelemetry é opcional e no-op por padrão. Quando `OTEL_ENABLED=true`, API e
worker exportam spans OTLP para `OTEL_EXPORTER_OTLP_ENDPOINT`; FastAPI, HTTPX e
Psycopg são instrumentados automaticamente. Logs incluem `trace_id` e `span_id`
somente quando há span válido, e o exportador nunca recebe conteúdo de prompts,
respostas, argumentos ou resultados de ferramentas.
`OTEL_TRACE_SAMPLING_RATIO` controla a amostragem entre `0` e `1` e mantém a
decisão do span pai.

Para ativar um backend OTLP, defina `OTEL_ENABLED=true`,
`OTEL_EXPORTER_OTLP_ENDPOINT` e, quando necessário, os cabeçalhos em
`OTEL_EXPORTER_OTLP_HEADERS` (por exemplo, a autorização Basic do Langfuse).
O endpoint e os cabeçalhos são injetados tanto no `amp-api` quanto no
`amp-worker`; segredos devem ficar no `.env` local e nunca no repositório.
O projeto não sobe o Langfuse automaticamente: a instalação self-hosted deve
ser escolhida e provisionada separadamente, e então os dois serviços apontam
para o endpoint OTLP dela.
Requisições usam `X-Request-ID` recebido ou gerado pela API; o mesmo valor volta
no response header. O worker vincula `execution_id`, `thread_id`, `run_id`,
`assistant_id`, `job_id` e `worker_id` enquanto processa o job. Contextos são
restaurados ao terminar cada request/job para impedir correlação acidental entre
execuções concorrentes.

Catálogo inicial: `execution.queued`, `execution.started`,
`execution.succeeded`, `execution.failed`, `execution.cancel_requested`,
`execution.cancelled`, `execution.limit_exceeded`, `node.*`, `model.*`,
`tool.*`, `job.retry_scheduled`, `job.lease_expired` e `worker.lease_lost`.

O worker executa o grafo por `graph.stream_events(..., version="v3")` e
persiste somente metadados seguros das projeções `values`, `updates`, `custom`,
`interrupts` e `debug`. A API também oferece
`GET /v1/executions/{id}/events/stream`, usando `sequence_no` como ID SSE e
`Last-Event-ID` para reconexão.

Categorias `lifecycle` e `control` permanecem enquanto a execução existir;
`diagnostic` permanece 90 dias; `audit` fica reservada para a Fase 14.
Quando diagnósticos forem removidos, a timeline é marcada como parcial.

## Limites e histórico

Defaults da política `runtime-v1`: 120 segundos desde o enqueue, 12 passos,
4 chamadas de ferramenta, 45 segundos por modelo, 10 segundos por ferramenta e
3 tentativas. O valor efetivo é o mais restritivo entre hard cap, Workspace,
versão do agente, canal e pedido do cliente.

O `HistoryProvider` `recent-v1` lê somente mensagens anteriores à entrada,
retém até 20 mensagens e aproximadamente 6.000 tokens estimados por
`ceil(caracteres / 4)`, sempre incluindo a entrada atual.

## APIs

`GET /v1/executions` usa cursor keyset opaco e versionado. A timeline usa
`GET /v1/executions/{id}/events?after_sequence=N`, pois esse número será o
`Last-Event-ID` da futura reconexão SSE. Cancelamento é
`POST /v1/executions/{id}/cancel` e é idempotente.

## Retenção e saúde

Checkpoints terminais ficam elegíveis após 7 dias, workers inativos após 7 dias
e logs Docker usam cinco arquivos de 10 MB por serviço. `/health` permanece
compatível; `/health/live` testa o processo e `/health/ready` testa PostgreSQL,
worker, Ollama e SearXNG.
