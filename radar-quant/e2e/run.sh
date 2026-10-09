#!/usr/bin/env bash
# E2E do Radar Quant com agent-browser (https://github.com/vercel-labs/agent-browser).
# Uso:
#   e2e/run.sh                 sobe o backend com dados sintéticos e testa
#   e2e/run.sh http://host:porta   testa um servidor já no ar (ex.: contêiner Docker)
# Sai com código != 0 se alguma verificação falhar. Screenshots em e2e/out/.
set -uo pipefail
cd "$(dirname "$0")/.."

OUT=e2e/out
mkdir -p "$OUT"
export AGENT_BROWSER_SESSION="radar-e2e-$$"
FAILS=0
SERVER_PID=""

cleanup() {
  agent-browser close >/dev/null 2>&1 || true
  [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null
  [ -n "${TMP_DATA:-}" ] && rm -rf "$TMP_DATA"
}
trap cleanup EXIT

if [ $# -ge 1 ]; then
  BASE="$1"
else
  PORT=8437
  BASE="http://127.0.0.1:$PORT"
  TMP_DATA=$(mktemp -d)
  RADAR_DATA_DIR="$TMP_DATA" RADAR_PROVIDER=synthetic \
    .venv/bin/uvicorn app.main:app --port "$PORT" --log-level warning >"$OUT/server.log" 2>&1 &
  SERVER_PID=$!
fi

# espera o primeiro refresh terminar (até 120 s)
for _ in $(seq 1 120); do
  if curl -sf "$BASE/api/health" | grep -q '"last_refresh":"'; then break; fi
  sleep 1
done
curl -sf "$BASE/api/health" | grep -q '"last_refresh":"' || { echo "FALHA: servidor não respondeu em $BASE"; exit 1; }

N_ASSETS=$(curl -sf "$BASE/api/assets" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')
N_OK=$(curl -sf "$BASE/api/ranking" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')

js() { agent-browser eval "$1" 2>&1 | tail -1 | sed -e 's/^"//' -e 's/"$//'; }

check() { # descrição, obtido, esperado
  if [ "$2" = "$3" ]; then echo "ok    $1"; else echo "FALHA $1 (obtido: '$2', esperado: '$3')"; FAILS=$((FAILS + 1)); fi
}

wait_true() { # descrição, expressão JS booleana (até 15 s)
  local got=""
  for _ in $(seq 1 30); do
    got=$(js "$2")
    [ "$got" = "true" ] && { echo "ok    $1"; return 0; }
    sleep 0.5
  done
  echo "FALHA $1 (expressão: $2 -> '$got')"; FAILS=$((FAILS + 1)); return 1
}

Q='document.querySelector'
QA='document.querySelectorAll'

agent-browser set viewport 1440 900 >/dev/null
agent-browser open "$BASE/" >/dev/null

# --- carga inicial ---
wait_true "watchlist carregada com $N_ASSETS ativos" "$QA('#watchlist [data-asset-id]').length === $N_ASSETS"
wait_true "gráfico com candles" "window.__radar.state.candleCount > 100"
wait_true "título do gráfico preenchido" "$Q('#chart-title').textContent.trim().length > 0"
wait_true "cartão de recomendação com veredito" "$Q('#rec-verdict').textContent.trim().length > 0"
wait_true "evidência visível no cartão" "$Q('#rec-evidence').textContent.trim().length > 0"
check "quatro fatores no cartão" "$(js "$QA('#rec-factors > *').length >= 4")" "true"
check "aviso legal presente" "$(js "$Q('#disclaimer').textContent.includes('Não é recomendação')")" "true"
check "canvas do gráfico de preço" "$(js "$QA('#price-chart canvas').length > 0")" "true"
check "canvas do RSI" "$(js "$QA('#rsi-chart canvas').length > 0")" "true"
check "canvas do MACD" "$(js "$QA('#macd-chart canvas').length > 0")" "true"
agent-browser screenshot "$OUT/01-grafico.png" >/dev/null

# --- troca de ativo ---
T1=$(js "$Q('#chart-title').textContent.trim()")
ID1=$(js "String(window.__radar.state.selectedId)")
agent-browser eval "[...$QA('#watchlist [data-asset-id]')].find(e => e.dataset.assetId !== '$ID1').click()" >/dev/null
wait_true "trocar de ativo muda o título" "$Q('#chart-title').textContent.trim() !== '$T1'"

# --- intervalos ---
wait_true "candles do novo ativo" "window.__radar.state.candleCount > 100"
D=$(js "String(window.__radar.state.candleCount)")
agent-browser click "#interval-1wk" >/dev/null
wait_true "semanal tem menos candles que diário" "window.__radar.state.interval === '1wk' && window.__radar.state.candleCount < $D"
W=$(js "String(window.__radar.state.candleCount)")
agent-browser click "#interval-1mo" >/dev/null
wait_true "mensal tem menos candles que semanal" "window.__radar.state.interval === '1mo' && window.__radar.state.candleCount < $W"
agent-browser click "#interval-1d" >/dev/null
wait_true "volta ao diário" "window.__radar.state.interval === '1d' && window.__radar.state.candleCount === $D"

# --- adicionar / erro / remover ---
agent-browser fill "#add-symbol" "tsla" >/dev/null
agent-browser select "#add-market" "US" >/dev/null
agent-browser click "#add-submit" >/dev/null
wait_true "TSLA adicionada (símbolo normalizado)" "!!$Q('#watchlist [data-symbol=\"TSLA\"]')"
agent-browser fill "#add-symbol" "INVALIDO" >/dev/null
agent-browser select "#add-market" "US" >/dev/null
agent-browser click "#add-submit" >/dev/null
wait_true "símbolo inválido mostra erro" "$Q('#add-error').textContent.trim().length > 0"
check "símbolo inválido não entra na watchlist" "$(js "!$Q('#watchlist [data-symbol=\"INVALIDO\"]')")" "true"
agent-browser fill "#add-symbol" "TSLA" >/dev/null
agent-browser click "#add-submit" >/dev/null
wait_true "duplicado mostra erro" "$Q('#add-error').textContent.includes('já')"
# o botão de remover pode pedir confirmação: aceita qualquer confirm()
agent-browser eval "window.confirm = () => true" >/dev/null
agent-browser eval "(() => { const el = $Q('#watchlist [data-symbol=\"TSLA\"]'); const item = el.closest('[data-asset-id]') || el; (item.querySelector('.remove-asset') || el.querySelector('.remove-asset')).click(); })()" >/dev/null
wait_true "TSLA removida" "!$Q('#watchlist [data-symbol=\"TSLA\"]') && $QA('#watchlist [data-asset-id]').length === $N_ASSETS"

# --- ranking ---
agent-browser click "#tab-ranking" >/dev/null
wait_true "ranking com $N_OK linhas" "$QA('#ranking-table tbody tr[data-asset-id]').length === $N_OK"
check "aba ranking visível" "$(js "$Q('#view-ranking').offsetParent !== null && $Q('#view-chart').offsetParent === null")" "true"
agent-browser screenshot "$OUT/02-ranking.png" >/dev/null
agent-browser select "#ranking-market" "CRYPTO" >/dev/null
wait_true "filtro de mercado reduz o ranking" "$QA('#ranking-table tbody tr[data-asset-id]').length < $N_OK && $QA('#ranking-table tbody tr[data-asset-id]').length > 0"
RID=$(js "$Q('#ranking-table tbody tr[data-asset-id]').dataset.assetId")
agent-browser click "#ranking-table tbody tr[data-asset-id]" >/dev/null
wait_true "clique no ranking abre o ativo no gráfico" "$Q('#view-chart').offsetParent !== null && String(window.__radar.state.selectedId) === '$RID'"

# --- carteira ---
agent-browser click "#tab-portfolio" >/dev/null
wait_true "carteira com pesos" "$QA('#portfolio-weights [data-symbol]').length >= 2"
check "matriz de correlação desenhada" "$(js "$QA('#portfolio-correlation td').length >= 4")" "true"
check "estatísticas da carteira" "$(js "$Q('#portfolio-stats').textContent.trim().length > 0")" "true"
SUM=$(curl -sf "$BASE/api/portfolio" | python3 -c 'import json,sys; print(round(sum(w["weight"] for w in json.load(sys.stdin)["weights"]), 6))')
check "pesos da carteira somam 1" "$SUM" "1.0"
P1=$(js "$Q('#portfolio-weights').textContent")
agent-browser select "#portfolio-method" "min_variance" >/dev/null
wait_true "trocar o método muda os pesos" "$Q('#portfolio-weights').textContent !== $(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$P1")"
agent-browser screenshot "$OUT/03-carteira.png" >/dev/null

# --- tema ---
TH=$(js "document.documentElement.dataset.theme || ''")
agent-browser click "#theme-toggle" >/dev/null
wait_true "alternar tema muda data-theme" "(document.documentElement.dataset.theme || '') !== '$TH'"
agent-browser click "#tab-chart" >/dev/null
sleep 1
agent-browser screenshot "$OUT/04-tema-alternado.png" >/dev/null

# --- layout estreito ---
agent-browser set viewport 390 844 >/dev/null
sleep 1
check "sem rolagem horizontal no celular" "$(js "document.documentElement.scrollWidth <= window.innerWidth + 1")" "true"
agent-browser screenshot "$OUT/05-celular.png" >/dev/null

# --- erros de página ---
ERRS=$(agent-browser errors 2>&1 | grep -v -i -E '^\s*$|no (page )?errors' | head -20)
if [ -z "$ERRS" ]; then echo "ok    nenhum erro de página"; else echo "FALHA erros de página:"; echo "$ERRS"; FAILS=$((FAILS + 1)); fi

echo
if [ "$FAILS" -eq 0 ]; then echo "E2E: tudo ok"; else echo "E2E: $FAILS falha(s)"; fi
exit "$FAILS"
