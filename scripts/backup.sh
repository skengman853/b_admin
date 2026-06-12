#!/usr/bin/env bash
# Back up the b_admin Postgres database to Cloudflare R2.
#
#   ./scripts/backup.sh
#
# Dumps via the db container (custom format, compressed), uploads via the api
# container using the app's existing R2 credentials, keeps the last 3 dumps
# locally and the last 14 remotely.
set -euo pipefail

cd "$(dirname "$0")/.."

STAMP="$(date +%Y%m%dT%H%M%S)"
NAME="b_admin-${STAMP}.dump"
mkdir -p backend/backups

echo "dumping database -> backend/backups/${NAME}"
docker compose exec -T db pg_dump -U postgres -Fc invoice_organizer > "backend/backups/${NAME}"

docker compose exec -T api python scripts/upload_backup_to_r2.py "backups/${NAME}"

# Keep only the 3 most recent local dumps.
ls -1t backend/backups/b_admin-*.dump 2>/dev/null | tail -n +4 | xargs -I{} rm -f {}
echo "local backups:"
ls -lh backend/backups/ | tail -n +2
