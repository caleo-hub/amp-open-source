#!/usr/bin/env bash
set -euo pipefail

output_dir="${1:-backups}"
mkdir -p "$output_dir"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
output_file="$output_dir/amp-postgres-$timestamp.dump"

docker compose exec -T amp-db pg_dump   -U amp   -d amp   --format=custom   --schema=amp   --schema=langgraph   > "$output_file"

chmod 600 "$output_file"
printf 'Backup criado em %s\n' "$output_file"
