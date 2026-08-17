#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
secrets_file="${LANGFUSE_SECRETS_FILE:-/home/caleo/.config/amp-secrets/langfuse.env.sh}"
langfuse_base_url="${LANGFUSE_BASE_URL:-http://192.168.1.250:3000}"

if [[ ! -r "$secrets_file" ]]; then
  echo "Langfuse secrets file is not readable: $secrets_file" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$secrets_file"

: "${LANGFUSE_INIT_PROJECT_PUBLIC_KEY:?Missing Langfuse project public key}"
: "${LANGFUSE_INIT_PROJECT_SECRET_KEY:?Missing Langfuse project secret key}"

auth_string="$({
  printf '%s:%s' \
    "$LANGFUSE_INIT_PROJECT_PUBLIC_KEY" \
    "$LANGFUSE_INIT_PROJECT_SECRET_KEY"
} | base64 | tr -d '\n')"

export OTEL_ENABLED=true
export OTEL_EXPORTER_OTLP_ENDPOINT="${langfuse_base_url%/}/api/public/otel/v1/traces"
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic ${auth_string},x-langfuse-ingestion-version=4"
export OTEL_TRACE_SAMPLING_RATIO="${OTEL_TRACE_SAMPLING_RATIO:-1}"

cd "$repo_dir"
exec docker compose "$@"
