# Fase 10 — AMP Chat

O AMP Chat é servido pelo `amp-chat` em `http://<host>:3001`. A API e o
worker continuam internos; o Next.js funciona como BFF e encaminha API/SSE
para `amp-api`.

## Subida local

Defina o segredo antes do Compose:

```sh
export AMP_CHAT_TOKEN='um-segredo-local-longo'
export AMP_CHAT_SESSION_SECRET='outro-segredo-para-assinar-sessoes'
docker compose up -d --build amp-db amp-migrate amp-api amp-worker amp-chat
```

Abra `http://<ip-do-servidor>:3001` em um computador ou celular da rede e
informe o token. O navegador recebe somente um cookie `HttpOnly`; o token é
validado e encaminhado pelo BFF.

Em produção, mantenha os dois valores em um secret manager ou arquivo `.env`
fora do controle de versão. Gere um token longo, troque-o durante a rotação e
recrie somente o serviço `amp-chat`:

```sh
AMP_CHAT_TOKEN='novo-segredo' AMP_CHAT_SESSION_SECRET='novo-segredo-de-sessao' \
  docker compose up -d --build amp-chat
```

Se `AMP_PUBLIC_ORIGIN` começar com `https://`, o cookie passa a usar `Secure`;
em HTTP local ele permanece sem esse atributo para funcionar na LAN.

## API do Chat

O recorte local compatível com o Agent Chat UI está em `/threads`:

- `POST/GET/PATCH /threads` e `/threads/{thread_id}` para catálogo e arquivo;
- `GET /threads/{thread_id}/state` e `GET/POST /history` para checkpoints;
- `GET /threads/{thread_id}/runs` e `/runs/{run_id}`;
- `POST /threads/{thread_id}/commands` para `run.start` e `input.respond`;
- `POST /threads/{thread_id}/stream` para o protocolo SSE persistente;
- `POST /threads/{thread_id}/runs/{run_id}/cancel` e `/retry`.

O stream v2 registra envelopes do Agent Streaming Protocol em
`amp.thread_stream_events`. Cada envelope possui `seq` imutável, usado tanto
como ID SSE quanto como cursor. O cliente envia `since` e pode também enviar
`Last-Event-ID`; o servidor retoma depois do maior cursor, sem repetir tokens.
Os eventos de `amp.execution_events` continuam sendo somente observabilidade.

Threads do protótipo anterior são arquivadas e marcadas como protocolo v1 no
corte. Seus checkpoints e logs permanecem no banco para auditoria, mas elas
não aparecem no novo catálogo v2.

`waiting_approval` é exposto como `interrupted` e `succeeded` como
`completed`. A tool `salvar_nota_local` demonstra `interrupt()` e gravação
durável no workspace local depois de aprovação.

O transcript novo é reconstruído dos checkpoints LangGraph. `amp.messages`
permanece somente como projeção legada para compatibilidade dos adaptadores
existentes.

O runtime AMP usa exclusivamente o modelo FAST (`qwen3.5:2b-q4_K_M`); não há
mais nó roteador nem seleção entre perfis de modelo.

## CopilotKit/AG-UI

O frontend usa `@copilotkit/react-core/v2` e o runtime Next.js em
`/api/copilotkit`. O runtime encaminha `agent/run` para o endpoint AG-UI
estático `/ag-ui`; o `threadId` permanece no payload e o token nunca chega ao
navegador. O endpoint também pode ser consumido diretamente em
`/threads/{thread_id}/ag-ui` para diagnóstico.

Quando o firewall do servidor não libera a porta 3001 para a LAN, um acesso
temporário pelo Windows pode usar o túnel SSH:

```powershell
ssh -N -L 3001:127.0.0.1:3001 caleo@192.168.1.250
```

Para acesso de outros dispositivos da LAN, libere a porta TCP 3001 no firewall
do Ubuntu (ou configure um reverse proxy interno); o container já escuta em
`0.0.0.0:3001` e não expõe API, worker ou PostgreSQL.
