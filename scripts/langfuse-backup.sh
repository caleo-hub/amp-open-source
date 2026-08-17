#!/usr/bin/env bash
set -euo pipefail

base_dir="${LANGFUSE_BASE_DIR:-/home/caleo/services/langfuse}"
backup_root="${LANGFUSE_BACKUP_DIR:-/home/caleo/backups/langfuse}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir="$backup_root/$timestamp"
volumes=(langfuse_langfuse_clickhouse_data langfuse_langfuse_clickhouse_logs langfuse_langfuse_minio_data langfuse_langfuse_postgres_data langfuse_langfuse_redis_data)
[[ -r "$base_dir/docker-compose.yml" ]] || { echo "Compose not found: $base_dir" >&2; exit 1; }
mkdir -p "$backup_dir"
cleanup() { "$(dirname "${BASH_SOURCE[0]}")/langfuse-stack.sh" up -d >/dev/null 2>&1 || true; }
trap cleanup EXIT
"$(dirname "${BASH_SOURCE[0]}")/langfuse-stack.sh" down
cp "$base_dir/docker-compose.yml" "$backup_dir/"
[[ -r "$base_dir/docker-compose.amp.yml" ]] && cp "$base_dir/docker-compose.amp.yml" "$backup_dir/"
{
  date -u +%FT%TZ
  docker version --format '{{.Server.Version}}'
  printf '%s\n' "${volumes[@]}"
} > "$backup_dir/manifest.txt"
for volume in "${volumes[@]}"; do
  docker volume inspect "$volume" >/dev/null
  docker run --rm -v "$volume:/data:ro" -v "$backup_dir:/backup" alpine tar -czf "/backup/$volume.tar.gz" -C /data .
done
echo "Langfuse cold backup created: $backup_dir"
