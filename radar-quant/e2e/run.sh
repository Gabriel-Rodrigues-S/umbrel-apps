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
  RADAR_DATA_DIR="$TMP_DATA" RADAR_PROVIDER=synthetic RADAR_UNIVERSE_PACE=0 \
    .venv/bin/uvicorn app.main:app --port "$PORT" --log-level warning >"$OUT/server.log" 2>&1 &
  SERVER_PID=$!
fi

# espera o primeiro refresh passar por todos os ativos (até 180 s); com dados
# reais ele leva vários segundos e o health já responde depois do primeiro ativo
pending() {
  curl -sf "$BASE/api/assets" | python3 -c 'import json,sys; print(sum(1 for a in json.load(sys.stdin) if not a["last_refresh"]))' 2>/dev/null
}
for _ in $(seq 1 180); do
  [ "$(pending)" = "0" ] && break
  sleep 1
done
[ "$(pending)" = "0" ] || { echo "FALHA: refresh inicial não terminou em $BASE"; exit 1; }

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

# ===================== 1.1 =====================
setsel() { # seletor, valor — troca um <select> e dispara change
  agent-browser eval "(() => { const s = $Q('$1'); s.value = '$2'; s.dispatchEvent(new Event('change', {bubbles: true})); })()" >/dev/null
}

# --- busca no catálogo e ativo fora da watchlist ---
agent-browser click "#tab-chart" >/dev/null
agent-browser fill "#add-symbol" "AMZ" >/dev/null
wait_true "autocompletar encontra AMZN" "!!$Q('#search-results [data-symbol=\"AMZN\"]')"
agent-browser click '#search-results [data-symbol="AMZN"]' >/dev/null
wait_true "AMZN aberto pelo catálogo" "$Q('#chart-title').textContent.includes('AMZN') && window.__radar.state.candleCount > 100"
check "AMZN aberto não entra na watchlist" "$(js "!$Q('#watchlist [data-symbol=\"AMZN\"]')")" "true"
check "botão indica fora da watchlist" "$(js "$Q('#watch-toggle').dataset.watch")" "false"
agent-browser click "#watch-toggle" >/dev/null
wait_true "botão adiciona à watchlist" "!!$Q('#watchlist [data-symbol=\"AMZN\"]') && $Q('#watch-toggle').dataset.watch === 'true'"
agent-browser eval "window.confirm = () => true" >/dev/null
agent-browser click "#watch-toggle" >/dev/null
wait_true "botão tira da watchlist" "!$Q('#watchlist [data-symbol=\"AMZN\"]') && $Q('#watch-toggle').dataset.watch === 'false'"
check "ativo continua aberto depois de sair da watchlist" "$(js "$Q('#chart-title').textContent.includes('AMZN')")" "true"

# --- doze intervalos ---
for I in 1m 3m 5m 10m 30m 1h 1wk 1mo 3mo 6mo 1y 1d; do
  agent-browser click "#interval-$I" >/dev/null
  wait_true "intervalo $I desenha candles" "window.__radar.state.interval === '$I' && window.__radar.state.candleCount > 0"
  if [ "$I" = "5m" ]; then
    wait_true "aviso de intraday visível" "$Q('#intraday-note').offsetParent !== null && $Q('#intraday-note').textContent.trim().length > 0"
  fi
done
check "aviso de intraday some no diário" "$(js "$Q('#intraday-note').offsetParent === null || $Q('#intraday-note').textContent.trim() === ''")" "true"
Y=$(js "String(window.__radar.state.candleCount)")
agent-browser click "#interval-1y" >/dev/null
wait_true "anual tem menos candles que diário" "window.__radar.state.interval === '1y' && window.__radar.state.candleCount < $Y"
agent-browser click "#interval-1d" >/dev/null
wait_true "volta ao diário (1.1)" "window.__radar.state.interval === '1d' && window.__radar.state.candleCount === $Y"

# --- curto prazo ---
agent-browser click "#rec-tab-swing" >/dev/null
wait_true "três setups de curto prazo" "$QA('#swing-card .swing-setup[data-setup][data-state]').length === 3"
check "setups esperados" "$(js "[...$QA('#swing-card .swing-setup')].map(e => e.dataset.setup).sort().join(',')")" "queda,reversao,rompimento"
check "estados válidos" "$(js "[...$QA('#swing-card .swing-setup')].every(e => ['sinal','posicao','nenhum'].includes(e.dataset.state))")" "true"
check "evidência visível em cada setup" "$(js "[...$QA('#swing-card .swing-setup')].every(e => /evidência|amostra/i.test(e.textContent))")" "true"
check "contexto de curto prazo" "$(js "$Q('#swing-context').textContent.trim().length > 0")" "true"
agent-browser click '#swing-card .swing-setup[data-setup="reversao"]' >/dev/null
wait_true "setup selecionado" "$Q('#swing-card .swing-setup[data-setup=\"reversao\"]').getAttribute('aria-pressed') === 'true' || !!$Q('#swing-card .swing-setup[data-setup=\"reversao\"] [aria-pressed=\"true\"]')"
agent-browser screenshot "$OUT/06-curto-prazo.png" >/dev/null
agent-browser click "#rec-tab-position" >/dev/null
wait_true "volta à aba Posição" "$Q('#rec-verdict').offsetParent !== null"

# --- notícias ---
wait_true "notícias do ativo" "$QA('#news-list a[data-news]').length > 0"
check "links de notícia são http(s)" "$(js "[...$QA('#news-list a[data-news]')].every(a => /^https?:\\/\\//.test(a.getAttribute('href') || ''))")" "true"
check "links abrem em nova aba com noopener" "$(js "[...$QA('#news-list a[data-news]')].every(a => a.target === '_blank' && /noopener/.test(a.rel))")" "true"

# --- screener ---
agent-browser click "#tab-ranking" >/dev/null
setsel "#screener-scope" "SP500"
wait_true "screener do S&P 500 com linhas" "$QA('#ranking-table tbody tr[data-asset-id]').length > 0"
wait_true "resumo do índice" "$Q('#screener-summary').textContent.trim().length > 0"
check "paginação informada" "$(js "$Q('#screener-page').textContent.trim().length > 0")" "true"
agent-browser screenshot "$OUT/07-screener.png" >/dev/null
SN=$(curl -sf "$BASE/api/screener?scope=SP500&verdict=comprar" | python3 -c 'import json,sys; print(json.load(sys.stdin)["total"])')
setsel "#screener-verdict" "comprar"
wait_true "filtro de veredito bate com a API ($SN)" "(() => { const n = $QA('#ranking-table tbody tr[data-asset-id]').length; return $SN > 50 ? n === 50 : n === $SN; })()"
setsel "#screener-verdict" ""
setsel "#screener-scope" "watchlist"
wait_true "screener volta à watchlist" "$QA('#ranking-table tbody tr[data-asset-id]').length === $N_OK"
agent-browser click "#tab-chart" >/dev/null

# ===================== 1.1.1 =====================
# --- busca por nome da empresa e por código ---
first_result() { js "(() => { const e = $Q('#search-results [data-symbol]'); return e ? e.dataset.symbol : ''; })()"; }
search_for() { # texto digitado, símbolo esperado em primeiro
  agent-browser fill "#add-symbol" "$1" >/dev/null
  wait_true "busca \"$1\" sugere $2 em primeiro" "(() => { const e = $Q('#search-results [data-symbol]'); return !!e && e.dataset.symbol === '$2'; })()"
}
search_for "banco do brasil" "BBAS3"
search_for "brasil banco" "BBAS3"
search_for "bbas3" "BBAS3"
search_for "BBAS3" "BBAS3"
agent-browser fill "#add-symbol" "itau" >/dev/null
wait_true "busca sem acento encontra o Itaú" "!!$Q('#search-results [data-symbol=\"ITUB4\"]')"
check "resultado da busca mostra o nome da empresa" "$(js "/ita[uú]/i.test($Q('#search-results [data-symbol=\"ITUB4\"]').textContent)")" "true"
agent-browser press Escape >/dev/null
agent-browser fill "#add-symbol" "" >/dev/null

# --- nome da empresa em todo papel ---
check "watchlist mostra o nome das empresas" "$(js "$QA('#watchlist [data-asset-id] .wl-name').length >= 5")" "true"
check "nome da Petrobras na watchlist" "$(js "/petr[oó]/i.test(($Q('#watchlist [data-symbol=\"PETR4\"]').closest('[data-asset-id]') || $Q('#watchlist [data-symbol=\"PETR4\"]')).textContent)")" "true"
agent-browser click "#tab-portfolio" >/dev/null
wait_true "carteira mostra o nome das empresas" "/petr[oó]|vale|apple|ita[uú]|weg/i.test($Q('#portfolio-weights').textContent)"
agent-browser click "#tab-chart" >/dev/null

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
