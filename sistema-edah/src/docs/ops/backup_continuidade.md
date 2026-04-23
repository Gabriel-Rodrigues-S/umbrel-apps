# Backup, Restauração e Continuidade

## Escopo
- Banco SQLite local (`db.sqlite3`) para ambientes simples/MVP.
- Artefatos críticos: banco e configurações de ambiente.

## Política de backup
- Frequência sugerida: diário.
- Retenção padrão: 7 dias.
- Script: `bash scripts/backup_sqlite.sh`

## Restauração
- Comando:
  - `bash scripts/restore_sqlite.sh <arquivo-backup> [db.sqlite3]`
- Validar após restore:
  1. `uv run python manage.py check`
  2. `bash scripts/smoke_healthcheck.sh`

## RTO e RPO (MVP)
- RTO alvo: até 30 minutos.
- RPO alvo: até 24 horas.

## Teste de continuidade
- Executar simulação de restore ao menos 1x por mês.
- Registrar tempo de recuperação e falhas encontradas.
