#!/usr/bin/env bash
set -euo pipefail

BACKUP_FILE="${1:-}"
TARGET_DB="${2:-db.sqlite3}"

if [[ -z "$BACKUP_FILE" ]]; then
  echo "Uso: bash scripts/restore_sqlite.sh <arquivo-backup> [caminho-db]" >&2
  exit 1
fi

if [[ ! -f "$BACKUP_FILE" ]]; then
  echo "Arquivo de backup não encontrado: $BACKUP_FILE" >&2
  exit 1
fi

cp "$BACKUP_FILE" "$TARGET_DB"
echo "Restauração concluída em: $TARGET_DB"
