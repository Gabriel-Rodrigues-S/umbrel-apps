#!/usr/bin/env bash
set -euo pipefail

export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-ci-temporary-secret-key}"
export DJANGO_DEBUG="${DJANGO_DEBUG:-True}"
export DJANGO_ALLOWED_HOSTS="${DJANGO_ALLOWED_HOSTS:-127.0.0.1,localhost}"
export DJANGO_CSRF_TRUSTED_ORIGINS="${DJANGO_CSRF_TRUSTED_ORIGINS:-http://127.0.0.1:8000,http://localhost:8000}"
export BOOTSTRAP_ADMIN_PASSWORD="${BOOTSTRAP_ADMIN_PASSWORD:-Admin@123456}"

uv run python manage.py migrate --noinput
uv run python manage.py bootstrap_sys_edah

uv run python manage.py runserver 127.0.0.1:8000 > /tmp/django-smoke.log 2>&1 &
SERVER_PID=$!

cleanup() {
  if kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    kill "$SERVER_PID" || true
  fi
}
trap cleanup EXIT

for i in {1..30}; do
  if curl -s "http://127.0.0.1:8000/login/" >/dev/null 2>&1; then
    break
  fi
  sleep 1
  if [[ "$i" -eq 30 ]]; then
    echo "Servidor não respondeu a tempo." >&2
    cat /tmp/django-smoke.log >&2 || true
    exit 1
  fi
done

curl -fsS "http://127.0.0.1:8000/api/health/theme/" | grep -Eq '"status"\s*:\s*"ok"'
curl -fsS "http://127.0.0.1:8000/login/" >/dev/null

echo "Smoke check de release passou com sucesso."
