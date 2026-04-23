#!/usr/bin/env bash
set -euo pipefail

DB_PATH="${1:-db.sqlite3}"
BACKUP_DIR="${2:-backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

if [[ ! -f "$DB_PATH" ]]; then
  echo "Banco não encontrado em: $DB_PATH" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_FILE="$BACKUP_DIR/db_${STAMP}.sqlite3"

cp "$DB_PATH" "$BACKUP_FILE"
find "$BACKUP_DIR" -type f -name 'db_*.sqlite3' -mtime +"$RETENTION_DAYS" -delete

echo "Backup criado: $BACKUP_FILE"
