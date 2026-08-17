#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" != "--confirm" || -z "${2:-}" ]]; then
  echo "Usage: $0 --confirm /home/caleo/backups/langfuse/<timestamp>" >&2
  exit 2
fi
backup_dir="$(realpath "$2")"
backup_root="$(realpath "${LANGFUSE_BACKUP_DIR:-/home/caleo/backups/langfuse}")"
case "$backup_dir/" in "$backup_root"/*) ;; *) echo "Backup must be below $backup_root" >&2; exit 1;; esac
volumes=(langfuse_langfuse_clickhouse_data langfuse_langfuse_clickhouse_logs langfuse_langfuse_minio_data langfuse_langfuse_postgres_data langfuse_langfuse_redis_data)
for volume in "${volumes[@]}"; do [[ -r "$backup_dir/$volume.tar.gz" ]] || { echo "Missing archive: $volume" >&2; exit 1; }; done
"$(dirname "${BASH_SOURCE[0]}")/langfuse-stack.sh" down
cleanup() { "$(dirname "${BASH_SOURCE[0]}")/langfuse-stack.sh" up -d >/dev/null 2>&1 || true; }
trap cleanup EXIT
for volume in "${volumes[@]}"; do
  docker run --rm -v "$volume:/data" -v "$backup_dir:/backup:ro" alpine sh -c 'find /data -mindepth 1 -delete && tar -xzf "/backup/'"$volume"'.tar.gz" -C /data'
done
echo "Langfuse restore completed from: $backup_dir"
