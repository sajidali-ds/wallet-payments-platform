#!/usr/bin/env bash
# Dumps the three databases (custom format) to $BACKUP_DIR, keeps 7 days, optionally copies to S3.
#   S3_BUCKET=my-backup-bucket bash deploy/backup_postgres.sh
# The three dumps are taken one after another, not as one atomic snapshot; for point-in-time recovery
# use EBS snapshots (AWS Backup / Data Lifecycle Manager) or move Postgres to RDS.
set -euo pipefail
cd "$(dirname "$0")/.."

PG_USER="$(grep -E '^POSTGRES_USER=' .env | cut -d= -f2-)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${BACKUP_DIR:-/var/backups/wallet-platform}"
mkdir -p "$DEST"

for db in auth_db wallet_db notification_db; do
  docker compose exec -T postgres pg_dump -U "$PG_USER" -Fc "$db" > "$DEST/${db}-${STAMP}.dump"
  echo "dumped $db -> $DEST/${db}-${STAMP}.dump"
done
find "$DEST" -name '*.dump' -mtime +7 -delete

if [ -n "${S3_BUCKET:-}" ]; then
  aws s3 cp "$DEST/" "s3://${S3_BUCKET}/wallet-platform/" --recursive --exclude '*' --include "*-${STAMP}.dump"
fi
