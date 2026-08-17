#!/usr/bin/env bash
set -euo pipefail

base_url="${AMP_BASE_URL:-http://127.0.0.1:8000}"
langfuse_url="${LANGFUSE_BASE_URL:-http://127.0.0.1:3000}"
secrets_file="${LANGFUSE_SECRETS_FILE:-/home/caleo/.config/amp-secrets/langfuse.env.sh}"
[[ -r "$secrets_file" ]] || { echo "Missing Langfuse secrets file" >&2; exit 1; }
# shellcheck disable=SC1090
source "$secrets_file"
conv="$(curl -fsS -X POST "$base_url/v1/conversations" -H 'content-type: application/json' -d '{"channel":"chat"}')"
conversation_id="$(jq -r .id <<<"$conv")"
request_id="$(cat /proc/sys/kernel/random/uuid)"
message="$(curl -fsS -X POST "$base_url/v1/conversations/$conversation_id/messages" -H 'content-type: application/json' -H "Idempotency-Key: $request_id" -d '{"content":"Responda somente com OK.","request_id":"'"$request_id"'","source":"chat","deadline_seconds":120}')"
execution_id="$(jq -r .execution_id <<<"$message")"
for _ in $(seq 1 60); do
  execution="$(curl -fsS "$base_url/v1/executions/$execution_id")"
  status="$(jq -r .status <<<"$execution")"
  case "$status" in
    succeeded) break ;;
    failed|cancelled|expired|dead_letter) echo "$execution"; exit 1 ;;
  esac
  sleep 2
done
timeline="$(curl -fsS "$base_url/v1/executions/$execution_id")"
[[ "$(jq -r .status <<<"$timeline")" == succeeded ]] || { echo "Timeline did not reach succeeded" >&2; exit 1; }
for _ in $(seq 1 15); do
  observations="$(curl -fsS -u "$LANGFUSE_INIT_PROJECT_PUBLIC_KEY:$LANGFUSE_INIT_PROJECT_SECRET_KEY" "$langfuse_url/api/public/v2/observations?limit=100&name=amp.execution")"
  if jq -e --arg sid "$conversation_id" '.data[]? | select((.traceId // "") != "") | select(.sessionId == $sid)' <<<"$observations" >/dev/null; then
    echo "timeline↔trace acceptance passed: execution=$execution_id conversation=$conversation_id"
    exit 0
  fi
  sleep 2
done
echo "No Langfuse observation correlated with execution/conversation" >&2
exit 1
