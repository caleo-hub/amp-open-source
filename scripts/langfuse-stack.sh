#!/usr/bin/env bash
set -euo pipefail

base_dir="${LANGFUSE_BASE_DIR:-/home/caleo/services/langfuse}"
secrets_file="${LANGFUSE_SECRETS_FILE:-/home/caleo/.config/amp-secrets/langfuse.env.sh}"
override_file="${LANGFUSE_COMPOSE_OVERRIDE:-/home/caleo/services/langfuse/docker-compose.amp.yml}"
[[ -d "$base_dir" && -r "$base_dir/docker-compose.yml" ]] || { echo "Langfuse compose directory not found: $base_dir" >&2; exit 1; }
[[ -r "$secrets_file" ]] || { echo "Langfuse secrets file is not readable: $secrets_file" >&2; exit 1; }
# shellcheck disable=SC1090
set -a
source "$secrets_file"
set +a
: "${LANGFUSE_INIT_PROJECT_PUBLIC_KEY:?Missing Langfuse project public key}"
: "${LANGFUSE_INIT_PROJECT_SECRET_KEY:?Missing Langfuse project secret key}"
export LANGFUSE_INIT_PROJECT_PUBLIC_KEY LANGFUSE_INIT_PROJECT_SECRET_KEY
cd "$base_dir"
args=(-f docker-compose.yml)
[[ -r "$override_file" ]] && args+=(-f "$override_file")
exec docker compose "${args[@]}" "$@"
