# Radar Quant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** App Umbrel que mostra gráficos estilo TradingView de ações (B3, EUA) e cripto e dá recomendações estatísticas com evidência (backtest + IC), ranking e sugestão de carteira.

**Architecture:** Uma imagem Docker com FastAPI + SQLite + frontend estático (JS puro + Lightweight Charts vendorizado). Providers plugáveis por mercado gravam candles diários; um motor em numpy/pandas calcula fatores, score, backtest e carteira; a API expõe tudo em JSON.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, httpx, numpy, pandas, SQLite, pytest, Lightweight Charts 4.2.3, Docker, agent-browser (E2E).

**Spec:** `radar-quant/docs/2026-10-08-radar-quant-design.md` — leia antes de qualquer tarefa; fórmulas e formatos de lá valem como requisito.

## Global Constraints

- Raiz do app: `/home/gabriel/umbrel-apps/radar-quant/`. Branch git: `radar-quant`. Nunca tocar em outras pastas de app do monorepo.
- Python do projeto: `radar-quant/.venv/bin/python` (criado na Task 1). Rodar testes com `cd radar-quant && .venv/bin/python -m pytest -q`.
- Runtime só com `fastapi`, `uvicorn[standard]`, `httpx`, `numpy`, `pandas`. **Sem scipy, sem scikit-learn.**
- Código, comentários e textos de interface em português (pt-BR), no estilo dos outros apps do repo. Identificadores em inglês.
- Mercados: exatamente `B3`, `US`, `CRYPTO`. Limiar de veredito: `+30` / `−30`. Mínimo de 300 candles.
- `NaN`/`inf` nunca saem na API: viram `null`.
- Testes não acessam a internet (providers testados com `httpx.MockTransport`).
- Tarefas marcadas **[paralela]** não fazem `git commit`: o controlador commita. As demais commitam ao final.
- Porta 8430.

## Review Focus

1. Fonte devolve linhas nulas, lista vazia ou JSON de erro → provider descarta/levanta `ProviderError`, nunca grava lixo nem derruba o refresh. (Task 2)
2. Ativo com menos de 300 candles → `status: "insuficiente"` em watchlist, análise e ranking; fica fora da carteira; nada quebra. (Tasks 6, 7)
3. Provider fora do ar no refresh → candles antigos preservados, `last_error` preenchido, demais ativos atualizados. (Task 6)
4. Score nunca cruza os limiares, ou preço constante (variância zero) → zero operações, `hit_rate: null`, nenhuma divisão por zero, nenhum `NaN` na API. (Tasks 3, 4, 7)
5. Símbolo digitado como ` petr4 `, `PETR4.SA` ou `btcusdt` → normalizado para `PETR4`/`BTC`; duplicado → 409; inexistente → 422 e nada fica gravado. (Task 7)

---

### Task 1: Fundação — scaffold, config, base de providers, banco

**Files:**
- Create: `radar-quant/requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `.dockerignore`
- Create: `radar-quant/app/__init__.py`, `app/config.py`, `app/db.py`, `app/providers/__init__.py`, `app/providers/base.py`, `app/stats/__init__.py`
- Test: `radar-quant/tests/__init__.py`, `tests/test_db.py`, `tests/test_config.py`

**Interfaces — Produces:**

```python
# app/config.py
MARKETS = ("B3", "US", "CRYPTO")
PERIODS_PER_YEAR = {"B3": 252, "US": 252, "CRYPTO": 365}
CURRENCY = {"B3": "BRL", "US": "USD", "CRYPTO": "USD"}
DEFAULT_WATCHLIST = [("PETR4","B3"),("VALE3","B3"),("ITUB4","B3"),("BBAS3","B3"),("WEGE3","B3"),("BOVA11","B3"),
                     ("AAPL","US"),("MSFT","US"),("NVDA","US"),("SPY","US"),("QQQ","US"),("BTC","CRYPTO"),("ETH","CRYPTO")]
@dataclass(frozen=True)
class Settings:
    data_dir: Path        # env RADAR_DATA_DIR, padrão /app/data
    provider: str         # env RADAR_PROVIDER: "live" (padrão) | "synthetic"
    refresh_hours: float  # env RADAR_REFRESH_HOURS, padrão 6
def get_settings() -> Settings          # lê o ambiente a cada chamada
def normalize_symbol(symbol: str, market: str) -> str
    # strip + upper; B3: remove sufixo ".SA"; CRYPTO: remove sufixo "USDT" e "-USD"; vazio -> ValueError

# app/providers/base.py
@dataclass(frozen=True)
class Candle: date: str; open: float; high: float; low: float; close: float; volume: float   # date = "YYYY-MM-DD"
class ProviderError(Exception): ...
class UnknownSymbol(ProviderError): ...
class Provider(Protocol):
    async def fetch_daily(self, symbol: str, market: str) -> list[Candle]: ...

# app/db.py
class DuplicateAsset(Exception): ...
def connect(path: Path) -> sqlite3.Connection   # cria pasta e schema; row_factory=sqlite3.Row; check_same_thread=False; WAL; foreign_keys ON
def list_assets(conn) -> list[dict]             # ordenado por position, id
def get_asset(conn, asset_id: int) -> dict | None
def add_asset(conn, symbol: str, market: str) -> int      # currency via CURRENCY; position = max+1; DuplicateAsset se (symbol, market) existir
def delete_asset(conn, asset_id: int) -> bool             # apaga candles junto
def upsert_candles(conn, asset_id: int, candles: Iterable[Candle]) -> int   # INSERT OR REPLACE; devolve quantidade
def load_candles(conn, asset_id: int) -> list[sqlite3.Row]                  # date asc
def set_refresh_status(conn, asset_id: int, error: str | None) -> None      # last_refresh = agora UTC ISO; last_error
def upsert_rf(conn, rows: Iterable[tuple[str, float]]) -> None
def load_rf(conn) -> list[tuple[str, float]]                                # date asc
```

Schema conforme a spec (tabelas `assets`, `candles`, `rf_rates`). Todas as funções de escrita fazem `commit`. Use um `threading.RLock` de módulo em volta de cada operação (a conexão é compartilhada entre threads).

- [ ] **Step 1:** Criar `requirements.txt` (`fastapi==0.115.0`, `uvicorn[standard]==0.30.6`, `httpx==0.27.2`, `numpy==2.1.1`, `pandas==2.2.3`), `requirements-dev.txt` (`-r requirements.txt`, `pytest==8.3.3`), `pytest.ini` (`[pytest]\ntestpaths = tests\npythonpath = .`), `.dockerignore` (`.venv`, `tests`, `e2e`, `docs`, `data`, `__pycache__`, `*.pyc`, `.pytest_cache`).
- [ ] **Step 2:** `cd radar-quant && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements-dev.txt`. Esperado: instala sem erro.
- [ ] **Step 3:** Escrever testes que falham — `tests/test_config.py`: `normalize_symbol(" petr4 ","B3")=="PETR4"`, `("PETR4.SA","B3")→"PETR4"`, `("btcusdt","CRYPTO")→"BTC"`, `("BTC-USD","CRYPTO")→"BTC"`, `("  ","US")` levanta `ValueError`; `get_settings()` respeita `monkeypatch.setenv`. `tests/test_db.py` (com `tmp_path`): criar ativo e listar; duplicado levanta `DuplicateAsset`; `upsert_candles` duas vezes na mesma data substitui (1 linha, valor novo); `load_candles` em ordem crescente; `delete_asset` remove candles; `set_refresh_status(conn, id, "falhou")` aparece em `get_asset`; `upsert_rf`/`load_rf` ida e volta.
- [ ] **Step 4:** Rodar pytest → FALHA (módulos inexistentes).
- [ ] **Step 5:** Implementar `config.py`, `providers/base.py`, `db.py`.
- [ ] **Step 6:** Rodar pytest → PASSA.
- [ ] **Step 7:** Commit: `git add radar-quant && git commit -m "radar-quant: fundação (config, banco, base de providers)"`.

---

### Task 2 [paralela]: Providers (Yahoo, Binance, BCB, sintético, registry)

**Files:**
- Create: `app/providers/yahoo.py`, `binance.py`, `bcb.py`, `synthetic.py`, `registry.py`
- Test: `tests/test_providers.py`, `tests/fixtures/yahoo_petr4.json`, `tests/fixtures/binance_btc.json`, `tests/fixtures/bcb_cdi.json`

**Interfaces — Consumes:** `Candle`, `ProviderError`, `UnknownSymbol`, `Settings`.
**Produces:**

```python
class YahooProvider:   def __init__(self, transport: httpx.AsyncBaseTransport | None = None); async def fetch_daily(symbol, market) -> list[Candle]
class BinanceProvider: mesma forma
class SyntheticProvider: async def fetch_daily(symbol, market) -> list[Candle]
async def fetch_cdi(transport=None) -> list[tuple[str, float]]          # bcb.py: (data ISO, taxa diária em fração)
def get_provider(market: str, settings: Settings) -> Provider           # registry.py; mercado inválido -> ValueError
async def fetch_rf_rates(settings: Settings) -> list[tuple[str, float]] # live: fetch_cdi(); synthetic: [] 
```

Regras:
- **Yahoo:** URL e parâmetros da spec; ticker `f"{symbol}.SA"` para B3, `symbol` para US. Header `User-Agent: Mozilla/5.0 ...`. Timeout 20 s. HTTP 404 ou `chart.error` com `code == "Not Found"` → `UnknownSymbol`; outro status/erro/JSON inválido/`result` vazio → `ProviderError`. Para cada índice: se qualquer OHLC ou `adjclose` for `None`, descarta; fator `f = adjclose/close`; grava `open*f, high*f, low*f, adjclose`, `volume or 0`. Data = timestamp convertido em UTC + `meta.gmtoffset` segundos → `YYYY-MM-DD`. Datas duplicadas: fica a última. Zero candles válidos → `ProviderError`.
- **Binance:** par `f"{symbol}USDT"`. Tenta `https://api.binance.com`, depois `https://data-api.binance.vision` se a primeira der erro de rede ou status ≥ 500/451/403. Paginação: começa em `startTime` = agora − 3000 dias, `limit=1000`, avança `startTime = último openTime + 86_400_000` até vir menos de 1000 linhas ou 3 páginas. HTTP 400 com `code == -1121` → `UnknownSymbol`. Data = `openTime` em UTC. **Descartar o candle do dia UTC corrente** (ainda em formação).
- **BCB:** `GET https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados?formato=json&dataInicial=DD/MM/AAAA&dataFinal=DD/MM/AAAA` (janela de 10 anos menos 1 dia, limite da API). Cada item `{"data":"02/01/2024","valor":"0.043739"}` → `("2024-01-02", 0.00043739)`. Erro → `ProviderError`.
- **Sintético:** determinístico. `seed = zlib.crc32(f"{market}:{symbol}".encode())`; dias úteis (`pd.bdate_range`) terminando em `2026-10-07`; 1500 candles; GBM diário com `mu = -0.0002 + (seed % 1000)/1000*0.0010`, `sigma = 0.012 + (seed % 7)*0.002`, preço inicial 50; `open` = fechamento anterior, `high/low` = max/min(open, close) × (1 ± |ruído| 0,5%), volume inteiro positivo. Símbolos especiais: começa com `INVALID` → `UnknownSymbol`; começa com `CURTO` → só os últimos 100 candles; começa com `FALHA` → `ProviderError("fonte indisponível")`.

- [ ] **Step 1:** Criar as três fixtures à mão, pequenas e realistas: Yahoo com 5 timestamps (um deles com `close: null`), `adjclose` diferente de `close`, `gmtoffset: -10800`; Binance com 4 klines no formato de lista (um deles com `openTime` de hoje — gere o timestamp dentro do teste, não na fixture, ou monte a resposta no teste); BCB com 3 itens.
- [ ] **Step 2:** Escrever testes que falham (use `asyncio.run(...)`, sem pytest-asyncio; `httpx.MockTransport(handler)`):
  - Yahoo: devolve 4 candles (linha nula descartada), ajuste aplicado (`close == adjclose`, `open == open*adj/close`), URL contém `PETR4.SA`; 404 → `UnknownSymbol`; corpo `{"chart":{"result":null,"error":{"code":"Not Found"}}}` → `UnknownSymbol`; HTTP 500 → `ProviderError`; corpo não-JSON → `ProviderError`; todas as linhas nulas → `ProviderError`.
  - Binance: par `BTCUSDT` na query; candle de hoje descartado; primeira URL com 451 → usa o fallback; `{"code":-1121}` com 400 → `UnknownSymbol`; lista vazia → `ProviderError`.
  - BCB: conversão de data e de percentual; HTTP 500 → `ProviderError`.
  - Sintético: duas chamadas iguais → listas idênticas; 1500 candles; `low <= min(open, close)` e `high >= max(open, close)` em todos; `INVALIDO` → `UnknownSymbol`; `CURTO1` → 100; `FALHA1` → `ProviderError`.
  - Registry: `synthetic` → `SyntheticProvider` para os três mercados; `live` → Yahoo para B3/US, Binance para CRYPTO; mercado `"XX"` → `ValueError`; `fetch_rf_rates` em `synthetic` → `[]`.
- [ ] **Step 3:** Rodar `pytest tests/test_providers.py -q` → FALHA.
- [ ] **Step 4:** Implementar os cinco módulos.
- [ ] **Step 5:** Rodar → PASSA. **Não commitar.**

---

### Task 3 [paralela]: Indicadores e fatores

**Files:**
- Create: `app/stats/indicators.py`, `app/stats/factors.py`
- Test: `tests/test_indicators.py`, `tests/test_factors.py`

**Produces:**

```python
# indicators.py — todas recebem pd.Series de fechamento e devolvem com o mesmo índice
def sma(s, n) -> pd.Series
def ema(s, n) -> pd.Series                       # ewm(span=n, adjust=False)
def rsi(s, n=14) -> pd.Series                    # Wilder (ewm alpha=1/n); sem perdas -> 100; sem variação -> 50
def macd(s, fast=12, slow=26, signal=9) -> pd.DataFrame      # colunas macd, signal, hist
def bollinger(s, n=20, k=2.0) -> pd.DataFrame                # colunas mid, upper, lower (desvio populacional, ddof=0)

# factors.py
MIN_CANDLES = 300; BUY_THRESHOLD = 30.0; SELL_THRESHOLD = -30.0
WEIGHTS = {"momentum": 0.35, "trend": 0.35, "dist_sma200": 0.20, "reversal": 0.10}
SCALES  = {"momentum": 0.30, "trend": 20.0, "dist_sma200": 0.15, "reversal": 2.0}
LABELS  = {"momentum": "Momentum 12-1", "trend": "Tendência (126 d)", "dist_sma200": "Distância da média de 200", "reversal": "Reversão (5 d)"}
def factor_frame(close: pd.Series) -> pd.DataFrame   # colunas = chaves de WEIGHTS, valores brutos, NaN onde indefinido
def normalize(raw: pd.DataFrame) -> pd.DataFrame     # tanh(raw / SCALES[col])
def score_series(close: pd.Series) -> pd.Series      # 100 * soma ponderada; NaN enquanto algum fator for NaN
def verdict(score: float) -> str                     # "comprar" | "manter" | "vender"
def ewma_vol(close: pd.Series, periods_per_year: int, lam: float = 0.94) -> float
def current_drawdown(close: pd.Series, window: int = 252) -> float    # <= 0
```

Definições exatas na spec (seção "Fatores"). Detalhes:
- `momentum[t] = close[t-21] / close[t-252] - 1`.
- `trend[t]`: regressão de `log(close)` contra `x = 0..125` na janela que termina em `t`; `t_stat = slope / se(slope)`, `se = sqrt(SSR/(n-2)) / sqrt(Sxx)`. Se `SSR == 0` (reta perfeita ou preço constante): `t_stat = 0` quando `slope == 0`, senão `sign(slope) * 1e6` (o `tanh` satura). Vetorizar com `numpy.lib.stride_tricks.sliding_window_view`.
- `reversal[t] = -(r5[t] - média_252(r5)) / desvio_252(r5)`, `r5 = close.pct_change(5)`; desvio zero → `0.0`.
- `dist_sma200[t] = close[t] / sma(close, 200)[t] - 1`.
- `ewma_vol`: variância EWMA dos retornos diários (`var_t = lam*var_{t-1} + (1-lam)*r_t²`, inicializada com a variância amostral dos 20 primeiros retornos), devolve `sqrt(var_final * periods_per_year)`.

- [ ] **Step 1:** Testes que falham:
  - `sma([1,2,3,4,5], 3)` → `[nan, nan, 2, 3, 4]`; `ema` de série constante = constante; `rsi` de série estritamente crescente = 100 no fim, decrescente = 0, constante = 50; `bollinger` de constante → `upper == lower == mid`; `macd.hist == macd.macd - macd.signal`.
  - Série de 600 pontos `100 * exp(0.001 * t)` com ruído gaussiano pequeno (seed fixa, sigma 0,005): `score_series` final ≥ 30 e `verdict == "comprar"`. Mesma coisa com `-0.001` → `"vender"`. Passeio aleatório sem drift (seed fixa) com 600 pontos: `|score| < 60` e a função não devolve NaN no fim.
  - **Sem antecipação:** `score_series(close)` e `score_series(close.iloc[:450])` coincidem (`np.allclose`, `equal_nan=True`) nos primeiros 450 pontos.
  - `score_series` é NaN antes do índice 256 e finito a partir do 257.
  - Preço constante (600 pontos): `score_series` final finito (== 0), `ewma_vol == 0`, `current_drawdown == 0`.
  - `momentum` calculado à mão em uma série curta conhecida (ex.: `close[t] = t+1`, conferir `factor_frame(close)["momentum"].iloc[300] == 280/49 - 1`).
  - `verdict(30) == "comprar"`, `verdict(-30) == "vender"`, `verdict(29.9) == "manter"`.
  - `current_drawdown` de série que cai 20% do topo = `-0.2`.
- [ ] **Step 2:** Rodar → FALHA.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Rodar `pytest tests/test_indicators.py tests/test_factors.py -q` → PASSA. **Não commitar.**

---

### Task 4 [paralela]: Backtest e bootstrap

**Files:**
- Create: `app/stats/backtest.py`
- Test: `tests/test_backtest.py`

**Interfaces — Consumes:** nada de outras tarefas (recebe a série de score pronta).
**Produces:**

```python
def positions_from_score(score: pd.Series, buy: float = 30.0, sell: float = -30.0) -> pd.Series
    # 0.0/1.0 com histerese: vira 1 quando score >= buy, vira 0 quando score <= sell, senão mantém; começa em 0; NaN mantém
def block_bootstrap_ci(x: np.ndarray, periods_per_year: int, n_boot: int = 1000, block: int = 21, seed: int = 42) -> tuple[float, float, float]
    # (média anualizada = mean(x)*ppy, ic_inferior, ic_superior) com percentis 2,5 e 97,5 das médias reamostradas anualizadas
def perf_stats(returns: pd.Series, rf: pd.Series, periods_per_year: int) -> dict
    # {"ann_return", "ann_vol", "sharpe", "max_drawdown"}; ann_return geométrico; sharpe = mean(ret-rf)/std(ret)*sqrt(ppy), 0.0 se std == 0
@dataclass
class BacktestResult:
    start: str; end: str
    strategy: dict; buy_hold: dict
    trades: int; time_in_market: float; hit_rate: float | None
    excess_mean: float; ci_low: float; ci_high: float
    evidence: str                 # "favoravel" | "contraria" | "sem_evidencia"
    equity: pd.DataFrame          # colunas strategy, buy_hold; começa em 1.0
def run_backtest(close: pd.Series, score: pd.Series, rf_daily: pd.Series | None, periods_per_year: int,
                 cost: float = 0.001, n_boot: int = 1000, block: int = 21, seed: int = 42) -> BacktestResult
```

Regras de `run_backtest`:
- Período = do primeiro índice com score não-NaN até o fim. Se sobrarem menos de 30 retornos, levanta `ValueError("histórico insuficiente para backtest")`.
- `ret = close.pct_change()`; `pos = positions_from_score(score)`; posição efetiva do dia `t` é `pos[t-1]` (`shift(1)`, primeiro = 0).
- `rf_daily`: reindexado no índice de `close`, faltantes = 0; `None` = zeros.
- `strat[t] = held[t]*ret[t] + (1-held[t])*rf[t] - cost*|held[t]-held[t-1]|`.
- `trades` = número de entradas (0→1). Operações fechadas = pares entrada/saída; `hit_rate` = fração com retorno composto líquido > 0; `None` se não houver operação fechada. `time_in_market = mean(held)`.
- `excess = strat - ret` → `block_bootstrap_ci`. Rótulo conforme a spec. Se `excess` for todo zero → `sem_evidencia` com IC `(0, 0)`.
- Bootstrap: blocos circulares de tamanho `block` (índices iniciais sorteados por `np.random.default_rng(seed)`), concatenados até o tamanho de `x`.

- [ ] **Step 1:** Testes que falham:
  - `positions_from_score([0, 35, 10, -10, -31, 0, 30])` → `[0,1,1,1,0,0,1]`; NaN no meio mantém o valor anterior.
  - **Sem antecipação:** com `close` e `score` fixos, alterar `close.iloc[-1]` não muda `equity.iloc[:-1]`; e com score `[.., 35 no dia k, ..]` o primeiro retorno capturado é o do dia `k+1`.
  - Score sempre 100 a partir do dia 0, `cost=0`, `rf=None`: `equity.strategy` == `equity.buy_hold` a partir do 2º dia de posição (tolerância 1e-9, considerando o atraso de um dia) e `trades == 1`, `hit_rate is None`.
  - Score sempre 0: `trades == 0`, `time_in_market == 0`, `hit_rate is None`, `strategy.ann_return == 0` com `rf=None`, e igual ao rf composto quando `rf_daily` é constante 0,0004.
  - Custo: uma entrada com `cost=0.01` reduz a equity em 1% frente a `cost=0` no dia da entrada.
  - `hit_rate`: cenário construído com 2 operações fechadas, uma ganhadora e uma perdedora → `0.5`.
  - Bootstrap determinístico (mesma seed → mesmo IC; seed diferente → IC diferente); `x` constante 0,001 → IC inferior == superior == `0.001*252`; série i.i.d. N(0,1%) de 2000 pontos → IC contém 0.
  - Evidência: `strat` construído para ganhar do buy-and-hold todo dia → `favoravel`; perder todo dia → `contraria`.
  - Menos de 30 retornos válidos → `ValueError`.
  - Preço constante com score 0 → nenhum NaN em `strategy`/`buy_hold` (`sharpe == 0`).
- [ ] **Step 2:** Rodar → FALHA.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Rodar `pytest tests/test_backtest.py -q` → PASSA. **Não commitar.**

---

### Task 5 [paralela]: Carteira

**Files:**
- Create: `app/stats/portfolio.py`
- Test: `tests/test_portfolio.py`

**Produces:**

```python
class PortfolioError(ValueError): ...
METHODS = ("risk_parity", "min_variance")
def ledoit_wolf(returns: np.ndarray) -> np.ndarray     # (T, N) -> cov (N, N); alvo = média das variâncias * identidade; intensidade em [0, 1]
def risk_parity(cov: np.ndarray) -> np.ndarray         # long-only, soma 1, contribuições de risco iguais
def min_variance(cov: np.ndarray) -> np.ndarray        # long-only, soma 1 (gradiente projetado no simplex)
def apply_cap(w: np.ndarray, cap: float) -> np.ndarray # limita a cap e redistribui o excesso proporcionalmente entre os não limitados; repete até convergir
def build_portfolio(returns: pd.DataFrame, method: str, cap: float = 0.35) -> dict
```

`build_portfolio`: `returns` = retornos semanais, colunas = rótulos; faz `dropna()`; método fora de `METHODS` → `PortfolioError`; menos de 2 colunas → `PortfolioError("são necessários pelo menos 2 ativos")`; menos de 52 linhas → `PortfolioError("são necessárias pelo menos 52 semanas em comum")`. O teto só se aplica com ≥ 3 ativos. Devolve:

```python
{"weights": {rotulo: float}, "correlation": {"labels": [...], "matrix": [[...]]},
 "stats": {"ann_return": float, "ann_vol": float, "sharpe": float, "max_drawdown": float}, "weeks": int}
```
Estatísticas com 52 períodos/ano, rf = 0, sobre a carteira com pesos fixos rebalanceada toda semana. Correlação com variância zero → 0 fora da diagonal (sem NaN).

Algoritmos: Ledoit-Wolf pela fórmula fechada de Ledoit & Wolf (2004) para alvo identidade escalada (`delta = min(1, max(0, b²/d²))`). Paridade de risco: iteração multiplicativa `w_i ← w_i * (alvo / RC_i)^0.5`, renormalizando, até `max|RC_i/Σ RC − 1/N| < 1e-8` ou 5000 iterações. Mínima variância: 5000 passos de gradiente projetado (projeção euclidiana no simplex, passo `1/maior autovalor`).

- [ ] **Step 1:** Testes que falham:
  - `ledoit_wolf`: simétrica, positiva definida, traço ≈ traço da covariância amostral; com colunas idênticas a amostral é singular e a encolhida não.
  - `risk_parity` com covariância diagonal `[0.04, 0.01]` → pesos `[1/3, 2/3]` (inverso da volatilidade); em covariância aleatória 5×5 PD, contribuições de risco iguais (tolerância 1e-4), pesos ≥ 0, soma 1.
  - `min_variance` diagonal `[0.04, 0.01]` → `[0.2, 0.8]`; em caso onde a solução irrestrita teria peso negativo, todos os pesos ≥ 0 e soma 1; variância ≤ à da carteira de pesos iguais.
  - `apply_cap([0.7, 0.2, 0.1], 0.35)` → máximo 0,35, soma 1; não altera vetor que já respeita o teto.
  - `build_portfolio` com 4 ativos sintéticos (seed fixa, 160 semanas): pesos somam 1, todos ≤ 0,35 + 1e-9, matriz 4×4 com diagonal 1, estatísticas finitas. Com 2 ativos o teto não se aplica.
  - Erros: 1 coluna, 30 linhas, método `"x"` → `PortfolioError`.
  - Coluna constante (variância zero) → nenhum NaN no resultado.
- [ ] **Step 2:** Rodar → FALHA.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Rodar `pytest tests/test_portfolio.py -q` → PASSA. **Não commitar.**

---

### Task 6: Serviço de dados e orquestração de análise

**Files:**
- Create: `app/service.py`, `app/analysis.py`
- Test: `tests/test_service.py`, `tests/test_analysis.py`

**Interfaces — Consumes:** tudo das Tasks 1–5 (assinaturas acima).
**Produces:**

```python
# service.py
def seed_watchlist(conn) -> None                         # só se não houver ativos
async def refresh_asset(conn, asset: dict, settings, provider=None) -> None
    # busca, upsert, set_refresh_status(None). ProviderError (exceto UnknownSymbol) -> set_refresh_status(str(e)) e retorna.
    # UnknownSymbol -> grava last_error e relança.
async def refresh_all(conn, settings) -> None            # rf (falha é ignorada com log) + cada ativo; UnknownSymbol também não interrompe aqui
def load_frame(conn, asset_id: int) -> pd.DataFrame      # DatetimeIndex; colunas open, high, low, close, volume
def resample(df: pd.DataFrame, interval: str) -> pd.DataFrame   # "1d" | "1wk" (W-FRI) | "1mo" (fim de mês); OHLC first/max/min/last, volume soma; ValueError se inválido
def load_rf_series(conn) -> pd.Series                    # DatetimeIndex -> taxa diária

# analysis.py
def invalidate(asset_id: int | None = None) -> None
def analyze_asset(conn, asset: dict) -> dict             # cache em memória por (asset_id, data do último candle)
def asset_summary(conn, asset: dict) -> dict
def ranking(conn, market: str | None = None) -> list[dict]
def portfolio(conn, method: str, market: str | None = None) -> dict      # levanta PortfolioError
def candles_payload(conn, asset_id: int, interval: str) -> dict
def clean(obj)                                           # recursivo: NaN/inf -> None; numpy -> tipos nativos
```

Formatos (todas as saídas passam por `clean`):

```jsonc
// analyze_asset — status "ok"
{"asset_id":1,"symbol":"PETR4","market":"B3","currency":"BRL","status":"ok","candles":1500,"as_of":"2026-10-07",
 "score":42.1,"verdict":"comprar",
 "factors":[{"key":"momentum","label":"Momentum 12-1","raw":0.21,"normalized":0.60,"weight":0.35}, ...4 itens na ordem de WEIGHTS],
 "volatility":0.31,"drawdown":-0.08,
 "backtest":{"start":"...","end":"...","strategy":{...4 métricas},"buy_hold":{...},"trades":12,"time_in_market":0.61,"hit_rate":0.5,
             "excess":{"mean":0.01,"ci_low":-0.05,"ci_high":0.07},"evidence":"sem_evidencia"},
 "equity":[{"date":"2021-01-08","strategy":1.0,"buy_hold":1.0}, ...]}   // reamostrado semanal (último valor da semana)
// status "insuficiente": {"asset_id","symbol","market","currency","status":"insuficiente","candles":n,"as_of":ou null} e mais nada
// asset_summary
{"id":1,"symbol":"PETR4","market":"B3","currency":"BRL","price":38.2,"change_pct":0.012,"score":42.1,"verdict":"comprar",
 "evidence":"sem_evidencia","status":"ok","last_error":null,"last_refresh":"..."}   // sem candles: price/change/score/verdict/evidence null, status "insuficiente"
// ranking item
{"id","symbol","market","score","verdict","evidence","momentum","trend","dist_sma200","reversal","volatility","drawdown"}  // fatores normalizados; ordenado por score desc; só status ok
// portfolio
{"method":"risk_parity","market":null,"weights":[{"id","symbol","market","weight"}] (ordem decrescente de peso),
 "correlation":{"labels":["PETR4",...],"matrix":[[...]]},"stats":{...},"weeks":156,
 "note":"Retornos em moeda local de cada ativo, sem conversão cambial."}
// candles_payload
{"interval":"1d","candles":[{"time":"2026-10-07","open":..,"high":..,"low":..,"close":..,"volume":..}],
 "indicators":{"sma20":[{"time","value"}],"sma50":[...],"sma200":[...],"bb_upper":[...],"bb_lower":[...],"rsi14":[...],"macd":[...],"macd_signal":[...],"macd_hist":[...]}}
 // pontos com valor NaN são omitidos; indicadores calculados sobre a série já reamostrada
```

Regras: `periods_per_year` por mercado; rf só para `B3` (via `load_rf_series`), `None` nos outros. Carteira: fecha semanal `W-FRI` de cada ativo `ok`, últimos 156 pontos, `pct_change`, junta por data (inner), rótulo = símbolo (se repetir entre mercados, `SÍMBOLO (MERCADO)`). `backtest` que levantar `ValueError` → ativo `insuficiente`.

- [ ] **Step 1:** Testes que falham (banco em `tmp_path`, `Settings(provider="synthetic")`, `asyncio.run`):
  - `seed_watchlist` cria 13 ativos e é idempotente.
  - `refresh_all` grava candles de todos; `load_frame` tem `DatetimeIndex` crescente.
  - **Review Focus 3:** ativos `PETR4` e `FALHA1`: após `refresh_all`, `PETR4` tem candles e `last_error is None`; `FALHA1` tem `last_error` contendo "indisponível". Depois, pré-gravar candles em um ativo, trocar o provider (parâmetro `provider=`) por um que levanta `ProviderError` e conferir que os candles antigos continuam lá.
  - `resample`: 10 dias úteis → `1wk` tem 2 linhas com `open` do primeiro dia e `close` do último, `volume` somado; intervalo `"2h"` → `ValueError`.
  - `analyze_asset` em ativo sintético: `status == "ok"`, 4 fatores, `verdict` coerente com `score`, `json.dumps` funciona, não há `NaN` no texto serializado; segunda chamada devolve o mesmo objeto (cache); após `invalidate` recalcula.
  - **Review Focus 2:** ativo `CURTO1` → `status == "insuficiente"`; não aparece em `ranking`; `portfolio` o ignora; `asset_summary` tem `price` preenchido e `score is None`.
  - `ranking` ordenado por score decrescente; filtro `market="US"` só traz US.
  - `portfolio(conn, "risk_parity")` com a watchlist sintética: pesos somam 1 (1e-6), `labels` batem com os pesos; com um único ativo `ok` → `PortfolioError`.
  - `candles_payload` `1d`: `len(candles) == 1500`, `sma200` tem `1500-199` pontos, todos os `time` em ISO; `1mo` tem menos candles que `1wk`.
  - `clean({"a": float("nan"), "b": [np.float64(1.5), float("inf")]})` → `{"a": None, "b": [1.5, None]}`.
- [ ] **Step 2:** Rodar → FALHA.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Rodar a suíte inteira → PASSA.
- [ ] **Step 5:** Commit: `radar-quant: serviço de dados e análise`.

---

### Task 7: API FastAPI e refresh em segundo plano

**Files:**
- Create: `app/main.py`, `app/static/index.html` (provisório: `<h1>Radar Quant</h1>`)
- Test: `tests/test_api.py`

**Interfaces — Consumes:** `service`, `analysis`, `db`, `config`. **Produces:** as rotas da tabela "API" da spec, servindo `app/static` em `/` (`StaticFiles(html=True)` montado por último).

Regras:
- `create_app() -> FastAPI` + `app = create_app()`. `lifespan`: `settings = get_settings()`, `conn = db.connect(settings.data_dir / "radar.db")`, `seed_watchlist`, inicia `asyncio.create_task(loop_refresh())` (roda `refresh_all`, invalida o cache, dorme `refresh_hours*3600`; exceções são logadas e o laço continua); no encerramento cancela a tarefa e fecha a conexão. Estado em `app.state`.
- Variável `RADAR_SKIP_BACKGROUND=1` não inicia o laço (os testes fazem o refresh explicitamente).
- Rotas de leitura são `def` (rodam no threadpool). `POST /api/assets` e `POST /api/refresh` são `async`.
- `POST /api/assets`: corpo `{symbol, market}`; mercado fora de `MARKETS` → 422; `normalize_symbol` (`ValueError` → 422); `DuplicateAsset` → 409 `{"detail": "ativo já está na watchlist"}`; `refresh_asset`; `UnknownSymbol` → apaga o ativo e 422 `{"detail": "símbolo não encontrado em <mercado>"}`; sucesso → 201 com `asset_summary`.
- `DELETE` inexistente → 404. `candles`/`analysis` de id inexistente → 404. `interval` inválido → 422. `GET /api/portfolio`: método padrão `risk_parity`; `PortfolioError` → 422 com a mensagem. `market` inválido em ranking/portfolio → 422.
- `POST /api/refresh`: agenda `refresh_all` + `invalidate` em tarefa de fundo, devolve 202 `{"status": "agendado"}`.
- `GET /api/health`: `{"status":"ok","assets":n,"last_refresh":max(last_refresh) ou null}`.
- Respostas JSON com `Cache-Control: no-store`.

- [ ] **Step 1:** Testes que falham com `fastapi.testclient.TestClient` (fixture: `monkeypatch.setenv` de `RADAR_DATA_DIR=tmp_path`, `RADAR_PROVIDER=synthetic`, `RADAR_SKIP_BACKGROUND=1`; `with TestClient(create_app()) as c:`; chamar `POST /api/refresh` não basta — a fixture roda `asyncio.run(service.refresh_all(...))` usando `c.app.state.conn`):
  - `/api/health` → 200, `assets == 13`.
  - `/api/assets` → 13 itens, todos com `status == "ok"` e `verdict` em `{comprar, manter, vender}`.
  - `/api/assets/{id}/candles` → 200; `?interval=1wk` ok; `?interval=5m` → 422; id 9999 → 404.
  - `/api/assets/{id}/analysis` → 200, tem `backtest.evidence`.
  - `/api/ranking?market=CRYPTO` → 2 itens; `market=XX` → 422.
  - `/api/portfolio` → 200, pesos somam 1; `?method=min_variance` → 200; `?method=x` → 422; `?market=CRYPTO` (2 ativos) → 200.
  - **Review Focus 5:** `POST {"symbol":" tsla ","market":"US"}` → 201 com `symbol == "TSLA"`; repetir → 409; `{"symbol":"PETR4.SA","market":"B3"}` → 409 (já existe como PETR4); `{"symbol":"btcusdt","market":"CRYPTO"}` → 409; `{"symbol":"INVALIDO","market":"US"}` → 422 e `/api/assets` continua com a mesma contagem; `{"symbol":"X","market":"LSE"}` → 422; `{"symbol":" ","market":"US"}` → 422.
  - **Review Focus 2/4:** `POST {"symbol":"CURTO1","market":"US"}` → 201 com `status == "insuficiente"`; `/api/assets/{id}/analysis` → 200 com `status == "insuficiente"`; `/api/ranking` e `/api/portfolio` seguem 200.
  - `DELETE /api/assets/{id}` → 204; de novo → 404.
  - Nenhuma resposta contém o texto `NaN` ou `Infinity`.
  - `GET /` → 200 HTML.
- [ ] **Step 2:** Rodar → FALHA.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Suíte inteira → PASSA. Subir de verdade: `RADAR_DATA_DIR=/tmp/rq-smoke RADAR_PROVIDER=synthetic .venv/bin/uvicorn app.main:app --port 8430` em segundo plano, `curl -s localhost:8430/api/health`, e derrubar o processo.
- [ ] **Step 5:** Commit: `radar-quant: API e refresh em segundo plano`.

---

### Task 8 [paralela com 9]: Frontend

**Files:**
- Create/replace: `app/static/index.html`, `app/static/style.css`, `app/static/app.js`
- Create: `app/static/vendor/lightweight-charts.standalone.production.js` (v4.2.3) e `app/static/vendor/LICENSE-lightweight-charts.txt`
- Create: `app/static/favicon.svg`

**Interfaces — Consumes:** a API da Task 7 (formatos na Task 6). Nenhum build: JS puro em módulo único, sem CDN, sem fontes externas.

Requisitos (seção "Interface" da spec, integral) mais:
- Baixar a biblioteca: `curl -fsSL https://unpkg.com/lightweight-charts@4.2.3/dist/lightweight-charts.standalone.production.js -o app/static/vendor/lightweight-charts.standalone.production.js` e a licença de `https://unpkg.com/lightweight-charts@4.2.3/LICENSE`. Conferir que o arquivo começa com o cabeçalho de licença da TradingView e tem > 100 KB. Manter o logo de atribuição padrão da biblioteca.
- API v4: `LightweightCharts.createChart(el, opts)`, `chart.addCandlestickSeries()`, `addHistogramSeries()`, `addLineSeries()`. `time` aceita `"YYYY-MM-DD"`.
- Três gráficos empilhados e sincronizados pelo intervalo visível (`timeScale().subscribeVisibleLogicalRangeChange`): preço+volume (volume em `priceScaleId: ""` com `scaleMargins` no rodapé), RSI (linhas guia 30/70), MACD (linha, sinal, histograma). Redimensionam com `ResizeObserver`.
- Cores de candle: alta `#26a69a`, baixa `#ef5350`. Selos de veredito: comprar verde, manter cinza/âmbar, vender vermelho, insuficiente cinza tracejado. Evidência: `favoravel` → "evidência favorável", `contraria` → "evidência contrária", `sem_evidencia` → "sem evidência estatística".
- Números em pt-BR (`Intl.NumberFormat("pt-BR")`), percentuais com sinal, moeda conforme `currency`.
- Tema: atributo `data-theme` em `<html>`, variáveis CSS, persistido em `localStorage` dentro de `try/catch`; os gráficos trocam de cor junto.
- Layout: grid de 3 colunas em telas ≥ 1100 px; abaixo disso empilha (watchlist vira faixa horizontal rolável), sem rolagem horizontal da página.
- Estados: carregando (esqueleto), erro de rede (faixa com "Tentar de novo"), ativo `insuficiente` (cartão explica "menos de 300 candles"), `last_error` (ícone de alerta com `title`), erro 422 da carteira (mensagem do backend).
- Atualização automática da watchlist a cada 60 s; botão "Atualizar dados" chama `POST /api/refresh` e recarrega após 5 s.
- Mapa de calor de correlação em `<table>` com cor de fundo de −1 (vermelho) a +1 (verde) e o valor na célula.
- Texto vindo da API vai para o DOM por `textContent`, nunca por `innerHTML`.
- **Seletores estáveis para o E2E** (obrigatórios): `#tab-chart`, `#tab-ranking`, `#tab-portfolio`, `#view-chart`, `#view-ranking`, `#view-portfolio`, `#watchlist` com itens `[data-asset-id]` e `[data-symbol]`, `#add-symbol` (input), `#add-market` (select), `#add-submit`, `#add-error`, botões `.remove-asset`, `#chart-title`, `#interval-1d`, `#interval-1wk`, `#interval-1mo`, `#price-chart`, `#rsi-chart`, `#macd-chart`, `#rec-card`, `#rec-verdict`, `#rec-score`, `#rec-evidence`, `#rec-factors`, `#equity-chart`, `#ranking-table` (com `tbody tr[data-asset-id]`), `#ranking-market`, `#portfolio-method`, `#portfolio-market`, `#portfolio-weights` (com `[data-symbol]`), `#portfolio-correlation`, `#portfolio-stats`, `#portfolio-error`, `#theme-toggle`, `#refresh-btn`, `#disclaimer`. Expor `window.__radar = {state}` com `state.selectedId`, `state.interval`, `state.candleCount` para asserções.

- [ ] **Step 1:** Baixar e conferir a biblioteca e a licença.
- [ ] **Step 2:** Escrever `index.html`, `style.css`, `app.js`.
- [ ] **Step 3:** Subir o backend sintético (`RADAR_DATA_DIR=/tmp/rq-front RADAR_PROVIDER=synthetic .venv/bin/uvicorn app.main:app --port 8431`), conferir `curl -s localhost:8431/ | grep -c 'id="watchlist"'` = 1, `curl -sI localhost:8431/app.js` = 200, `node --check app/static/app.js` sem erro, e derrubar o processo.
- [ ] **Step 4:** `pytest -q` segue verde (o teste `GET /` continua passando). **Não commitar.**

---

### Task 9 [paralela com 8]: Docker e empacotamento Umbrel

**Files:**
- Create: `radar-quant/Dockerfile`
- Create: `garod004-apps-radar-quant/umbrel-app.yml`, `docker-compose.yml`, `icon.svg`
- Modify: `.github/scripts/detectar-apps.py` (dicionário `APPS`), `README.md` (nova seção após "Painel Mercado")

Conteúdo:
- `Dockerfile`: igual ao de `painel-mercado/Dockerfile`, trocando a porta para 8430 e mantendo `--workers 1`; `ENV RADAR_DATA_DIR=/app/data`.
- `docker-compose.yml`: copiar o de `garod004-apps-painel-mercado`, com `APP_HOST: garod004-apps-radar-quant_server_1`, `APP_PORT: 8430`, `image: ghcr.io/gabriel-rodrigues-s/radar-quant:1.0.0`.
- `umbrel-app.yml`: mesmos campos do Painel Mercado; `id: garod004-apps-radar-quant`, `name: Radar Quant`, `tagline: Gráficos e recomendações estatísticas para ações e cripto`, `category: finance`, `version: '1.0.0'`, `port: 8430`, descrição em português cobrindo mercados, score com evidência, ranking e carteira, e o aviso de que não é recomendação profissional; `releaseNotes` da primeira versão; URLs de ícone/galeria apontando para `garod004-apps-radar-quant/icon.svg`.
- `icon.svg`: 256×256, fundo escuro arredondado, três candles e uma linha de tendência; sem texto.
- `detectar-apps.py`: entrada `"radar-quant": {"image": "radar-quant", "context": "./radar-quant", "manifest": "garod004-apps-radar-quant", "paths": ["radar-quant/"]}`.
- `README.md`: seção "📊 Radar Quant" no formato das vizinhas (descrição, imagem, porta 8430).

- [ ] **Step 1:** Criar/editar os arquivos.
- [ ] **Step 2:** `python3 -c "import yaml,sys; [yaml.safe_load(open(f)) for f in sys.argv[1:]]" garod004-apps-radar-quant/umbrel-app.yml garod004-apps-radar-quant/docker-compose.yml` sem erro; `GITHUB_EVENT_NAME=workflow_dispatch INPUT_APPS=radar-quant GITHUB_OUTPUT=/dev/null python3 .github/scripts/detectar-apps.py` lista `radar-quant` com versão `1.0.0`.
- [ ] **Step 3:** `docker build -t radar-quant:dev radar-quant` conclui. `docker run -d --rm --name rq-dev -e RADAR_PROVIDER=synthetic -p 8432:8430 radar-quant:dev`; aguardar até 30 s por `curl -sf localhost:8432/api/health`; conferir `assets == 13`; `docker logs rq-dev` sem `Traceback`; `docker stop rq-dev`.
- [ ] **Step 4:** **Não commitar.**

---

### Task 10: E2E com agent-browser e verificação com dados reais (controlador)

**Files:**
- Create: `radar-quant/e2e/run.sh`, `radar-quant/e2e/README.md`

- [ ] **Step 1:** `npm i -g agent-browser && agent-browser install`.
- [ ] **Step 2:** `e2e/run.sh`: sobe o backend sintético em porta livre com banco temporário, espera o `/api/health`, percorre com `agent-browser` (carregar; watchlist com 13 itens; clicar em outro ativo e ver `#chart-title` mudar; D/S/M mudam `state.candleCount`; adicionar `TSLA`/US e ver na watchlist; adicionar `INVALIDO` e ver `#add-error`; remover `TSLA`; aba Ranking com 13 linhas e clique abrindo o gráfico; aba Carteira com pesos somando 100% e troca de método; alternar tema; `agent-browser errors` vazio), salva screenshots em `e2e/out/` e sai com código ≠ 0 se alguma asserção falhar.
- [ ] **Step 3:** Rodar até passar; corrigir o que aparecer (via subagente de correção) e rodar a suíte pytest de novo.
- [ ] **Step 4:** Verificação com dados reais: subir com `RADAR_PROVIDER=live`, esperar o refresh, conferir que os 13 ativos têm preço plausível e sem `last_error` (ou registrar qual fonte falhou e por quê), abrir no navegador e tirar screenshots das três abas.
- [ ] **Step 5:** Repetir o roteiro contra a imagem Docker.
- [ ] **Step 6:** Commit final, revisão do branch inteiro, merge em `main`, push, acompanhar o CI (`gh run watch`) e conferir a tag `:1.0.0` no ghcr.
