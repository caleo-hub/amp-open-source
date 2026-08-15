#!/usr/bin/env bash
set -euo pipefail

backup_file="${1:?Uso: $0 caminho-do-backup.dump}"
test -r "$backup_file"

docker compose exec -T amp-db pg_restore   -U amp   -d amp   --clean   --if-exists   --no-owner   < "$backup_file"
