#!/bin/bash
# vault-sync: mantem uma copia do vault via Obsidian Headless Sync (ob).
# Volume: /data/vault (escrito so aqui), /data/ob-home (credenciais do ob), /data/logs/sync.log
set -eu

# Com argumentos (ex.: docker run ... ob --version), executa o comando e pronto.
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

export HOME=/data/ob-home
VAULT=/data/vault
LOG=/data/logs/sync.log
MARCA=/data/ob-home/.configurado
LIMITE=$((50 * 1024 * 1024))
CONTAINER=garod004-apps-vault-gateway_sync_1

mkdir -p "$VAULT" /data/logs "$HOME"

if [ ! -f "$MARCA" ]; then
    cat <<MSG
=== vault-sync: configuracao inicial pendente ===
O Obsidian Sync ainda nao foi configurado neste servidor.
Rode, no servidor (as credenciais sao digitadas por voce, nunca guardadas aqui):

  sudo docker exec -it $CONTAINER ob login
  sudo docker exec -it $CONTAINER sh -c 'cd /data/vault && ob sync-setup --vault "<nome-do-cofre-remoto>"'
  sudo docker exec -it $CONTAINER sh -c 'cd /data/vault && ob sync-config --mode pull-only --conflict-strategy merge'
  # So rode o passo abaixo depois que o sync-setup tiver dado certo:
  sudo docker exec -it $CONTAINER touch /data/ob-home/.configurado

Depois reinicie o app (Umbrel > app > reiniciar). Aguardando configuracao...
MSG
    trap 'exit 0' TERM INT
    while :; do
        sleep 3600 &
        wait $! || true
    done
fi

# Rotacao simples: trunca o log se passar de 50 MB (tee -a usa O_APPEND, entao e seguro).
rotacionar() {
    if [ -f "$LOG" ] && [ "$(stat -c %s "$LOG")" -gt "$LIMITE" ]; then
        : > "$LOG"
    fi
}
rotacionar
(
    while :; do
        sleep 600
        rotacionar
    done
) &
ROT_PID=$!

cd "$VAULT"
ob sync --continuous > >(tee -a "$LOG") 2>&1 &
OB_PID=$!

# Repassa SIGTERM/SIGINT ao ob para parada limpa.
trap 'kill -TERM "$OB_PID" 2>/dev/null || true' TERM INT

STATUS=0
while :; do
    if wait "$OB_PID"; then STATUS=0; else STATUS=$?; fi
    # wait interrompido por sinal retorna >128 com o processo ainda vivo
    if kill -0 "$OB_PID" 2>/dev/null; then continue; fi
    break
done
kill "$ROT_PID" 2>/dev/null || true
sleep 1   # deixa o tee descarregar a saida
exit "$STATUS"
