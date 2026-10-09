# Radar Quant — design (spec)

Data: 2026-10-08. Aprovado por Gabriel em conversa (design + push ao final).

## Objetivo

App pessoal, no Umbrel, para acompanhar ações (B3 e EUA) e cripto em gráficos no
estilo TradingView e receber recomendações de posição/longo prazo baseadas em
estatística, **sempre acompanhadas da evidência** (backtest com intervalo de
confiança). Três visões: ativo (score + evidência), ranking da watchlist e
sugestão de carteira.

Sucesso = o Gabriel abre o app, vê a watchlist com veredito por ativo, abre um
gráfico de candles com indicadores, entende por que o veredito é aquele, e vê
pesos sugeridos de carteira. Quando a estatística não sustenta o sinal, a tela
diz isso explicitamente.

Lição herdada do Crypto-Paper-Bot (análise de 08/10/2026): indicador aceso não
é vantagem. Nenhum veredito é exibido sem o backtest correspondente.

## Fora do escopo (v1)

Intraday, alertas, dados fundamentalistas, ordens reais, múltiplos usuários,
login próprio (o `app_proxy` do Umbrel já autentica), conversão cambial.

## Arquitetura

Uma imagem Docker: FastAPI + SQLite + frontend estático (HTML/CSS/JS puro) com
Lightweight Charts (biblioteca aberta do TradingView, arquivo vendorizado em
`static/vendor/`, sem CDN). Mesmo padrão dos outros apps do monorepo.

```
radar-quant/
  Dockerfile  requirements.txt  requirements-dev.txt  pytest.ini  .dockerignore
  app/
    config.py            # env: RADAR_DATA_DIR, RADAR_PROVIDER, RADAR_REFRESH_HOURS
    db.py                # SQLite: assets, candles, rf_rates
    providers/
      base.py            # Candle, Provider (Protocol), ProviderError
      yahoo.py           # B3 (.SA) e US
      binance.py         # CRYPTO (par USDT)
      bcb.py             # CDI diário (SGS 12) — taxa livre de risco do mercado B3
      synthetic.py       # séries determinísticas para testes/E2E
      registry.py        # mercado -> provider
    stats/
      indicators.py      # sma, ema, rsi, macd, bollinger
      factors.py         # fatores, score, veredito (ponto e série histórica)
      backtest.py        # backtest do sinal + bootstrap em blocos
      portfolio.py       # correlação, Ledoit-Wolf, paridade de risco, mínima variância
    service.py           # refresh de dados, leitura de séries (pandas)
    analysis.py          # orquestra: análise por ativo, ranking, carteira; cache
    main.py              # rotas FastAPI + tarefa de refresh em segundo plano
    static/              # index.html, style.css, app.js, vendor/
  tests/                 # pytest
  e2e/                   # roteiro agent-browser
garod004-apps-radar-quant/   # umbrel-app.yml, docker-compose.yml, icon.svg
```

Dependências de runtime: `fastapi`, `uvicorn[standard]`, `httpx`, `numpy`,
`pandas`. Sem scipy (Ledoit-Wolf e otimização implementados em numpy).

## Dados

- **Mercados:** `B3`, `US`, `CRYPTO`. Um ativo é `(symbol, market)`, com o
  símbolo como o usuário digita: `PETR4`, `AAPL`, `BTC`. Cada provider traduz
  (`PETR4`→`PETR4.SA`, `BTC`→`BTCUSDT`). Mercado novo = provider novo + entrada
  no registry.
- **Yahoo:** `GET query1.finance.yahoo.com/v8/finance/chart/{sym}?range=10y&interval=1d&events=div,splits`,
  com `User-Agent` de navegador. Usa OHLC ajustado pelo fator `adjclose/close`.
  Linhas com valor nulo são descartadas.
- **Binance:** `GET /api/v3/klines?symbol=..&interval=1d&limit=1000`, paginado
  por `startTime` até 3000 candles; host `api.binance.com`, com fallback
  `data-api.binance.vision`.
- **BCB:** série SGS 12 (CDI % a.d.) em JSON, últimos 10 anos.
- **Armazenamento:** só candles diários. Semanal e mensal são reamostrados no
  backend (`W-FRI`, fim de mês). Tabelas:
  - `assets(id, symbol, market, name, currency, position, last_refresh, last_error)` — único `(symbol, market)`
  - `candles(asset_id, date, open, high, low, close, volume)` — PK `(asset_id, date)`
  - `rf_rates(date, rate)` — taxa diária em fração
- **Refresh:** na subida, ao adicionar ativo, a cada `RADAR_REFRESH_HOURS`
  (padrão 6) e por `POST /api/refresh`. Falha de um provider registra
  `last_error` no ativo e mantém os candles já gravados. Um ativo com erro não
  interrompe os demais.
- **Watchlist inicial** (semeada só com o banco vazio): PETR4, VALE3, ITUB4,
  BBAS3, WEGE3, BOVA11 (B3); AAPL, MSFT, NVDA, SPY, QQQ (US); BTC, ETH (CRYPTO).

## Motor estatístico

Tudo sobre fechamentos diários ajustados. Mínimo de **300 candles**; abaixo
disso o ativo recebe veredito `insuficiente` e nenhum número.

### Fatores

| Fator | Definição | Normalização para [−1, 1] |
|---|---|---|
| `momentum` | retorno de t−252 a t−21 | `tanh(x / 0.30)` |
| `trend` | estatística t da inclinação da regressão linear do log-preço nos últimos 126 dias | `tanh(x / 20)` |
| `dist_sma200` | `close / SMA200 − 1` | `tanh(x / 0.15)` |
| `reversal` | −z-score do retorno de 5 dias contra os retornos de 5 dias dos últimos 252 dias | `tanh(x / 2)` |

Informativos (não entram no score): volatilidade EWMA anualizada (λ=0,94, ×√252)
e drawdown atual contra o máximo de 252 dias.

### Score e veredito

`score = 100 × (0,35·momentum + 0,35·trend + 0,20·dist_sma200 + 0,10·reversal)`,
com os valores normalizados. Pesos fixos, definidos a priori — não são
ajustados aos dados, então não há sobreajuste de parâmetros a corrigir.

- `score ≥ +30` → **comprar**
- `score ≤ −30` → **vender**
- caso contrário → **manter**

### Backtest (evidência)

A mesma função de score é calculada para cada dia do histórico usando só dados
até aquele dia. Estratégia long/caixa com histerese: entra quando o score ≥ +30,
sai quando ≤ −30, mantém a posição entre os dois. O sinal do dia *t* vale para o
retorno de *t+1*. Custo de 0,1% por troca de posição. Em caixa rende a taxa
livre de risco (CDI para B3; zero para US e CRYPTO).

Métricas, para a estratégia e para buy-and-hold no mesmo período: retorno
anualizado, volatilidade anualizada, Sharpe (excesso sobre a taxa livre de
risco), drawdown máximo. Só da estratégia: número de operações, % do tempo
posicionado, taxa de acerto das operações fechadas.

**Evidência:** bootstrap em blocos (bloco de 21 dias, 1000 reamostragens,
semente fixa) da diferença diária `retorno_estratégia − retorno_buy_and_hold`,
gerando IC de 95% do excesso anualizado. Rótulo:

- limite inferior > 0 → `favoravel`
- limite superior < 0 → `contraria`
- caso contrário → `sem_evidencia` (texto na tela: "sem evidência estatística")

Anos por ano: 252 para B3/US, 365 para CRYPTO.

## Ranking

Todos os ativos com análise válida, ordenados por score, com as colunas de
fatores, volatilidade, drawdown e rótulo de evidência. Filtro por mercado.
Ordenação por coluna é feita no frontend.

## Carteira

Sobre os ativos selecionados (padrão: todos com análise válida; filtro por
mercado). Retornos **semanais** (`W-FRI`) dos últimos 3 anos, para alinhar B3,
EUA e cripto, que têm calendários diferentes. Precisa de ≥ 2 ativos e ≥ 52
semanas em comum; senão devolve erro explicativo.

- Covariância com encolhimento de Ledoit-Wolf (alvo: identidade escalada).
- `risk_parity`: contribuições de risco iguais (iterativo), long-only.
- `min_variance`: mínima variância long-only por gradiente projetado no simplex.
- Teto de 35% por ativo quando há ≥ 3 ativos (excesso redistribuído).
- Saída: pesos, matriz de correlação, e retorno anualizado, volatilidade,
  Sharpe (rf = 0) e drawdown máximo da carteira no período.

Limitação declarada na tela: retornos em moeda local de cada ativo, sem
conversão cambial.

## API

| Rota | Retorno |
|---|---|
| `GET /api/health` | `{status, assets, last_refresh}` |
| `GET /api/assets` | watchlist: id, symbol, market, currency, último preço, variação % do dia, score, veredito, evidência, last_error |
| `POST /api/assets` `{symbol, market}` | cria, dispara refresh do ativo; 409 se duplicado; 422 se o provider não conhece o símbolo |
| `DELETE /api/assets/{id}` | remove ativo e candles |
| `GET /api/assets/{id}/candles?interval=1d\|1wk\|1mo` | OHLCV + indicadores (sma20, sma50, sma200, bollinger, rsi14, macd) alinhados por data |
| `GET /api/assets/{id}/analysis` | fatores (bruto e normalizado), score, veredito, backtest, evidência, curva de equity (estratégia × buy-and-hold) |
| `GET /api/ranking?market=` | lista ordenada por score |
| `GET /api/portfolio?method=&market=` | pesos, correlação, estatísticas |
| `POST /api/refresh` | dispara refresh geral, devolve imediatamente |

Datas em ISO `YYYY-MM-DD`. `NaN` nunca sai na API (vira `null`).

A análise por ativo é cacheada em memória, chave `(asset_id, data do último
candle)`; refresh invalida.

## Interface

Uma página, três abas, em português, tema escuro por padrão com alternância
claro/escuro, responsiva.

- **Gráfico:** watchlist à esquerda (símbolo, preço, variação, selo de
  veredito; agrupada por mercado; adicionar e remover ativo). Ao centro, candles
  + volume, botões D/S/M, alternância de SMA 20/50/200 e Bollinger, painéis de
  RSI e MACD. À direita, cartão de recomendação: veredito, score, barras dos
  quatro fatores, volatilidade, drawdown, bloco de evidência (rótulo, IC,
  estratégia × buy-and-hold) e mini-gráfico da curva de equity.
- **Ranking:** tabela ordenável, filtro por mercado; clicar numa linha abre o
  ativo na aba Gráfico.
- **Carteira:** seletor de método e de mercado, barras de pesos, mapa de calor
  de correlação, estatísticas, aviso de moeda local.

Rodapé fixo: "Ferramenta de análise estatística para uso pessoal. Não é
recomendação profissional de investimento; resultado passado não garante
resultado futuro."

Estados de erro visíveis: ativo sem dados suficientes, falha de fonte
(`last_error`), carteira sem ativos suficientes.

## Testes

- **Unitários (pytest, TDD):** indicadores e fatores contra valores calculados
  à mão; score/veredito em séries sintéticas (tendência de alta → comprar,
  queda → vender, ruído → manter); backtest sem viés de antecipação (alterar o
  futuro não muda sinais passados) e com custos; bootstrap determinístico por
  semente; pesos de carteira somam 1, respeitam o teto e igualam contribuições
  de risco; providers contra respostas JSON gravadas (`httpx.MockTransport`).
- **API:** `TestClient` com `RADAR_PROVIDER=synthetic` e banco temporário.
- **E2E:** `agent-browser` (Vercel) contra `localhost` com provider sintético:
  carrega, troca de ativo, troca de intervalo, adiciona/remove ativo, abre
  Ranking e Carteira, alterna tema, sem erros no console. Depois, verificação
  com dados reais.
- **Docker:** build local e as mesmas checagens de saúde contra o contêiner.

## Empacotamento Umbrel

- `garod004-apps-radar-quant/`: `umbrel-app.yml` (id `garod004-apps-radar-quant`,
  porta **8430**, categoria finance, versão `1.0.0`), `docker-compose.yml`
  (imagem `ghcr.io/gabriel-rodrigues-s/radar-quant:1.0.0`, volume
  `${APP_DATA_DIR}/data:/app/data`), `icon.svg`.
- `.github/scripts/detectar-apps.py`: nova entrada `radar-quant`.
- `README.md` do monorepo: seção do app.
- Entrega: merge em `main` + push → CI publica `:1.0.0` → Gabriel clica
  **Instalar** na store "Apps do Gabriel".
