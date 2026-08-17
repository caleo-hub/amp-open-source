# Langfuse self-hosted no AMP

O AMP usa a instalação open source do Langfuse em `http://192.168.1.250:3000`.
O compose oficial fica em `/home/caleo/services/langfuse`; o override do AMP
fica em `/home/caleo/services/langfuse/docker-compose.amp.yml`.

As chaves não ficam no repositório nem no compartilhamento Samba. O arquivo
protegido é `/home/caleo/.config/amp-secrets/langfuse.env.sh` (permissão `600`).
`scripts/compose-langfuse.sh` calcula o header OTLP Basic e exporta o endpoint
`/api/public/otel/v1/traces`, `x-langfuse-ingestion-version=4` e a amostragem.

## Operação

```bash
./scripts/langfuse-stack.sh ps
./scripts/langfuse-stack.sh logs --tail=100 langfuse-web
./scripts/langfuse-stack.sh up -d
```

Para atualizar, faça backup frio primeiro, atualize o clone oficial e execute
`./scripts/langfuse-stack.sh pull` seguido de `up -d`. Nunca publique o arquivo
de secrets ou o conteúdo dos volumes.

## Backup e restore

`scripts/langfuse-backup.sh` para o stack, arquiva os cinco volumes persistentes
(Postgres, ClickHouse, MinIO e Redis), salva os compose/manifesto e inicia o
stack novamente. O destino padrão é `/home/caleo/backups/langfuse/<UTC>`.

```bash
./scripts/langfuse-backup.sh
./scripts/langfuse-restore.sh --confirm /home/caleo/backups/langfuse/<UTC>
```

O restore é deliberadamente destrutivo nos volumes Langfuse e exige `--confirm`.
Valide o backup em host separado antes de usá-lo em produção; o backup não
contém segredos.

## Aceitação

Com o AMP e Langfuse saudáveis, execute `scripts/acceptance-observability.sh`.
Ele cria uma execução, verifica o status na timeline da API e confirma uma
observação `amp.execution` no Langfuse com a correlação da conversa/execução.
