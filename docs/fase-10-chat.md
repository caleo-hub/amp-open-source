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
- `GET /threads/{thread_id}/state` e `/history` para checkpoints;
- `GET /threads/{thread_id}/runs` e `/runs/{run_id}`;
- `POST /threads/{thread_id}/runs/stream` para runs e retomadas;
- `GET /threads/{thread_id}/stream` para reconexão com `Last-Event-ID`;
- `POST /threads/{thread_id}/runs/{run_id}/cancel` e `/retry`.

`waiting_approval` é exposto como `interrupted` e `succeeded` como
`completed`. A tool `salvar_nota_local` demonstra `interrupt()` e gravação
durável no workspace local depois de aprovação.

O transcript novo é reconstruído dos checkpoints LangGraph. `amp.messages`
permanece somente como projeção legada para compatibilidade dos adaptadores
existentes.
