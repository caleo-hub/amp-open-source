# Async Path Alexa ↔ AMP

O canal Alexa não espera o Ollama. `POST /voice` valida a chave, timestamp e origem, grava a mensagem na conversa e cria uma execução na fila PostgreSQL. Responde `202 Accepted` com `execution_id`, `conversation_id` e `request_id`.

O worker processa e persiste o resultado. `GET /voice/executions/{execution_id}` traduz `queued`/`running` para `processing`, `succeeded` para `completed`, e `failed`/`cancelled` para `failed`.

Mensagens MQTT usam `action=submit` com `text` ou `action=result` com `execution_id`, e a resposta é publicada em `amp/ubuntu/response/{request_id}`. A entrega at-least-once é segura porque a persistência deduplica por `source + request_id`/idempotency key.

O canal `voice` permite explicitamente apenas `system_status` e `pesquisar_web`. Novas ferramentas não ficam disponíveis automaticamente.

Hoje a API não recebe uma identidade estável de usuário Alexa; a associação é feita por `request_id` e `conversation_id`. Uma Lambda futura pode transportar uma identidade estável sem criar outro modelo de persistência.

## Teste manual no Ubuntu

Com stack e worker ativos:

```bash
mosquitto_pub --cafile "$IOT_CA" --cert "$IOT_CERT" --key "$IOT_KEY" -h "$IOT_ENDPOINT" -p 8883 -t amp/ubuntu/command -q 1 -m '{"action":"submit","request_id":"alexa-demo-001","text":"pesquise notícias de inteligência artificial"}'
```

O bridge deve publicar imediatamente um ACK `accepted`. Extraia o `execution_id` e consulte:

```bash
mosquitto_pub --cafile "$IOT_CA" --cert "$IOT_CERT" --key "$IOT_KEY" -h "$IOT_ENDPOINT" -p 8883 -t amp/ubuntu/command -q 1 -m '{"action":"result","request_id":"alexa-demo-result-001","execution_id":"<UUID>"}'
```

Não marque o fluxo end-to-end como concluído sem testar Lambda/AWS IoT, certificados, bridge, PostgreSQL, worker e Ollama no Ubuntu real.
