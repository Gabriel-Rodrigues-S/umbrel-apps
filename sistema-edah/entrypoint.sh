#!/bin/sh
set -e

# ── Gerar SECRET_KEY e persistir no volume ────────────────────────────────────
mkdir -p /app/data
if [ -z "$DJANGO_SECRET_KEY" ]; then
    SECRET_FILE=/app/data/.secret_key
    if [ ! -f "$SECRET_FILE" ]; then
        python -c "import secrets; print(secrets.token_hex(50))" > "$SECRET_FILE"
        echo "[entrypoint] SECRET_KEY gerada e salva em $SECRET_FILE"
    fi
    export DJANGO_SECRET_KEY=$(cat "$SECRET_FILE")
fi

# ── Redirecionar SQLite para volume persistente ───────────────────────────────
ln -sf /app/data/db.sqlite3 /app/db.sqlite3

# ── Criar pastas de mídia e estáticos ────────────────────────────────────────
mkdir -p /app/uploads /app/staticfiles

# ── Aplicar migrations ────────────────────────────────────────────────────────
python manage.py migrate --noinput

# ── Coletar arquivos estáticos ────────────────────────────────────────────────
python manage.py collectstatic --noinput --clear

# ── Criar admin inicial + dados padrão (idempotente) ─────────────────────────
python manage.py bootstrap_sys_edah

echo "[entrypoint] Sistema EDAH iniciando na porta 8270..."

# ── Iniciar Gunicorn ──────────────────────────────────────────────────────────
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8270 \
    --workers 2 \
    --timeout 60 \
    --access-logfile - \
    --error-logfile -
