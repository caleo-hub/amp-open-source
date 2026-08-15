#!/usr/bin/env bash
set -euo pipefail

backup_file="${1:?Uso: $0 caminho-do-backup.dump}"
test -r "$backup_file"

# Restore is destructive: stop consumers so they cannot read/write while the
# database is being cleaned and restored. Always attempt to bring them back.
docker compose stop amp-api amp-worker
restart_services() { docker compose start amp-api amp-worker; }
trap restart_services EXIT

docker compose exec -T amp-db pg_restore -U amp -d amp --clean --if-exists --no-owner < "$backup_file"
