# Radar Quant 1.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Acrescentar ao Radar Quant o catálogo completo com screener de índices, a análise de curto prazo (swing), notícias por ativo e doze intervalos de gráfico.

**Architecture:** Mesma imagem única (FastAPI + SQLite + JS puro). O banco ganha tabelas `catalog`, `screener`, `news`, `meta` e a coluna `assets.watch`, com migração por `PRAGMA user_version`. Módulos novos e isolados (`catalog.py`, `stats/swing.py`, `news.py`, `screener.py`, `universe.py`) são costurados por `service.py`, `analysis.py` e `main.py`. Intraday é buscado sob demanda e nunca gravado.

**Tech Stack:** Python 3.12, FastAPI, httpx, numpy, pandas, SQLite, pytest, Lightweight Charts 4.2.3, agent-browser.

**Spec:** `radar-quant/docs/2026-10-09-radar-quant-1.1-design.md` (complementa `2026-10-08-radar-quant-design.md`). Leia antes de qualquer tarefa; URLs, fórmulas e formatos de lá são requisito.

## Global Constraints

- Raiz do app: `/home/gabriel/umbrel-apps/radar-quant/`. Branch: `radar-quant-1.1`. Não tocar em outros apps do monorepo.
- Testes: `cd radar-quant && .venv/bin/python -m pytest -q`. A suíte existente (164 testes) precisa continuar verde; ajuste testes antigos só quando o comportamento mudou por exigência da spec, e diga quais no relatório.
- Runtime só com `fastapi`, `uvicorn[standard]`, `httpx`, `numpy`, `pandas` e stdlib. **Nenhuma dependência nova** (RSS com `xml.etree`, sem feedparser).
- Testes sem rede (`httpx.MockTransport`); async via `asyncio.run`.
- Comentários e textos em pt-BR; identificadores em inglês. Código enxuto, no estilo do que já existe.
- `NaN`/`inf` nunca saem na API (`analysis.clean`). Datas diárias em ISO `YYYY-MM-DD`; intraday em segundos epoch UTC.
- Texto vindo de fora (catálogo, notícias, erros) só entra no DOM por `textContent`; links de notícia só `http(s)`.
- Mercados: `B3`, `US`, `CRYPTO`. Índices: `IBOV`, `IBRA`, `SP500`, `NDX`. Setups: `reversao`, `queda`, `rompimento`.
- O banco da 1.0.0 precisa abrir na 1.1.0 sem perder dados.
- Tarefas **[paralela]** não fazem commit (o controlador commita); as demais commitam ao final com o trailer `Co-Authored-By` do próprio modelo.

## Review Focus

1. Banco criado pela 1.0.0 (com ativos, candles e CDI) aberto pela 1.1.0 → tudo preservado, ativos antigos com `watch = 1`, migração idempotente. (Task 1)
2. Fonte do catálogo fora do ar, devolvendo lixo ou uma lista encolhida → linhas antigas do mercado/índice permanecem; as outras fontes seguem. (Task 2)
3. Ativo com volume zero, sem operações ou com poucas → setups em `amostra_insuficiente`/`nenhum`, sem divisão por zero nem `NaN`; ativo com menos de 300 candles continua `insuficiente` e sem `swing`. (Tasks 3, 6)
4. Intraday indisponível (símbolo sem intraday, fonte fora do ar, lista vazia) → resposta 422 com mensagem, nunca 500; o cache não entrega barras de outro ativo/intervalo. (Tasks 5, 6, 8)
5. Notícia com link `javascript:`, título gigante, entidades HTML, XML malformado ou com `<!DOCTYPE` → item descartado ou saneado; a busca de um ativo nunca derruba a rota. Busca do catálogo com `%`, `_`, aspas ou 500 caracteres → lista (vazia ou não), nunca erro. (Tasks 1, 4, 8)

---

### Task 1: Fundação — migração do banco, config e tipos

**Files:** Modify `app/config.py`, `app/db.py`, `app/providers/base.py`. Test: `tests/test_db.py`, `tests/test_config.py` (acrescentar), `tests/test_migration.py` (novo).

**Produces:**

```python
# config.py
INTERVALS = ("1m", "3m", "5m", "10m", "30m", "1h", "1d", "1wk", "1mo", "3mo", "6mo", "1y")
INTRADAY = ("1m", "3m", "5m", "10m", "30m", "1h")
INTRADAY_SECONDS = {"1m": 60, "3m": 180, "5m": 300, "10m": 600, "30m": 1800, "1h": 3600}
INDICES = {"IBOV": ("B3", "Ibovespa"), "IBRA": ("B3", "IBrA"), "SP500": ("US", "S&P 500"), "NDX": ("US", "Nasdaq-100")}
# Settings ganha (com padrão, para não quebrar quem constrói Settings com 3 argumentos):
#   universe: bool = True          env RADAR_UNIVERSE ("0" desliga)
#   universe_pace: float = 1.0     env RADAR_UNIVERSE_PACE

# providers/base.py
@dataclass(frozen=True)
class Bar: time: int; open: float; high: float; low: float; close: float; volume: float   # time = epoch s UTC
# Provider (Protocol) ganha:
#   NATIVE_INTRADAY: frozenset[str]
#   async def fetch_intraday(self, symbol: str, market: str, interval: str) -> tuple[list[Bar], int | None]
#       (barras em ordem crescente, atraso em minutos informado pela fonte ou None)

# db.py
SCHEMA_VERSION = 1
def list_assets(conn, watch: bool | None = True) -> list[dict]     # None = todos; padrão só watchlist
def find_asset(conn, symbol: str, market: str) -> dict | None
def add_asset(conn, symbol: str, market: str, watch: bool = True) -> int   # DuplicateAsset se (symbol, market) já existir
def set_watch(conn, asset_id: int, watch: bool) -> None
def touch_viewed(conn, asset_id: int) -> None                       # last_viewed = agora UTC ISO
def delete_asset(conn, asset_id: int) -> bool                       # apaga também screener e news
def purge_viewed(conn, older_than: str, keep_ids: set[int]) -> int  # apaga watch=0 fora de keep_ids com last_viewed nulo ou < older_than
# catálogo
def replace_catalog_market(conn, market: str, rows: Iterable[tuple[str, str, str]]) -> int  # (symbol, name, kind); preserva `indices` dos que continuam
def set_index_members(conn, index: str, market: str, symbols: Iterable[str]) -> int         # tira o índice de todos do mercado e põe nos listados; insere ausentes (name=symbol, kind="Ação")
def search_catalog(conn, q: str, limit: int = 12) -> list[dict]     # prefixo de símbolo primeiro, depois nome contendo; LIKE escapado; q vazio -> []
def catalog_entry(conn, symbol: str, market: str) -> dict | None    # {symbol, market, name, kind, indices: list[str]}
def index_members(conn, index: str | None = None) -> list[dict]     # None = quem pertence a qualquer índice
def catalog_count(conn, market: str | None = None) -> int
# screener
def upsert_screener(conn, asset_id: int, as_of: str, payload: dict) -> None
def load_screener(conn, asset_ids: Iterable[int] | None = None) -> list[dict]   # [{asset_id, as_of, updated_at, payload: dict}]
# notícias
def replace_news(conn, asset_id: int, items: list[dict]) -> None    # {title, url, source, published_at}; grava fetched_at = agora
def load_news(conn, asset_id: int) -> tuple[list[dict], str | None] # itens por published_at desc, fetched_at
# meta
def get_meta(conn, key: str) -> str | None
def set_meta(conn, key: str, value: str) -> None
```

Migração em `connect`: cria as tabelas-base se não existirem (schema da 1.0.0), lê `PRAGMA user_version`; se `< 1`, numa transação: `ALTER TABLE assets ADD COLUMN watch INTEGER NOT NULL DEFAULT 1` e `ADD COLUMN last_viewed TEXT` (só se a coluna não existir — conferir com `PRAGMA table_info`), cria `catalog`, `screener`, `news`, `meta` e índices (`catalog(market)`, `assets(watch)`), e grava `user_version = 1`. `catalog_entry`/`search_catalog` devolvem `indices` como lista. Todas as escritas pelo `_write` existente (RLock + rollback).

- [ ] **Step 1:** Testes que falham:
  - `test_migration.py`: criar à mão um banco com o schema exato da 1.0.0 (copie o `_SCHEMA` atual para dentro do teste, como string literal), inserir 2 ativos, candles e uma taxa em `rf_rates`, fechar; `db.connect` nele → `user_version == 1`, os 2 ativos com `watch == 1`, candles e rf intactos, tabelas novas existem; abrir de novo → nada muda (idempotente). Banco novo (arquivo inexistente) → mesmo schema final.
  - `list_assets` padrão não traz `watch=0`; `list_assets(conn, None)` traz todos; `add_asset(..., watch=False)`; `set_watch`; `find_asset`; `touch_viewed` preenche `last_viewed`.
  - `delete_asset` remove linhas de `screener` e `news` do ativo.
  - `purge_viewed`: apaga `watch=0` antigo fora de `keep_ids`; preserva `watch=1`, os de `keep_ids` e os vistos depois do corte.
  - Catálogo: `replace_catalog_market` substitui o mercado e preserva `indices` de quem continua; `set_index_members` troca os membros, insere símbolo ausente e não mexe em outro índice do mesmo papel (papel em `IBOV,IBRA` continua em `IBRA` quando `IBOV` muda); `index_members("IBRA")` e `index_members()`.
  - `search_catalog`: `"pet"` traz `PETR4` antes de um papel cujo nome contém "pet"; sem diferenciar maiúsculas; limite respeitado; **Review Focus 5:** `"%"`, `"_"`, `"'; DROP TABLE catalog;--"`, `"a"*500` e `"  "` não levantam erro (`"%"` e `"_"` não casam com tudo).
  - `upsert_screener`/`load_screener` ida e volta (payload dict), filtro por ids; `replace_news`/`load_news` (ordem desc, `fetched_at` preenchido; lista vazia grava `fetched_at` mesmo assim via `meta` ou linha-sentinela — escolha e documente); `get_meta`/`set_meta`.
  - `Settings` com 3 argumentos posicionais continua válido; `get_settings()` lê `RADAR_UNIVERSE=0` e `RADAR_UNIVERSE_PACE=0.2`.
- [ ] **Step 2:** Rodar → FALHA. **Step 3:** Implementar. **Step 4:** Suíte inteira → PASSA (ajustar testes antigos que dependam de `list_assets` trazer tudo não deve ser necessário: todos os ativos antigos são `watch=1`).
- [ ] **Step 5:** Commit: `radar-quant 1.1: migração do banco, catálogo, screener e notícias no db`.

---

### Task 2 [paralela]: Catálogo e composição de índices

**Files:** Create `app/catalog.py`. Test: `tests/test_catalog.py`, `tests/fixtures/catalog_*.{txt,json,csv}`.

**Consumes:** `db.replace_catalog_market`, `db.set_index_members`, `db.catalog_count`, `db.get_meta/set_meta`, `Settings`.
**Produces:**

```python
CRYPTO_CATALOG: list[tuple[str, str, str]]            # 20 itens (symbol, name, "Cripto"), BTC e ETH primeiro
MIN_ROWS = {"US": 3000, "B3": 200}
async def fetch_us(transport=None) -> list[tuple[str, str, str]]
async def fetch_b3(transport=None) -> list[tuple[str, str, str]]
async def fetch_index(index: str, transport=None) -> list[str]     # símbolos no formato do catálogo
def synthetic_catalog() -> tuple[dict[str, list[tuple[str, str, str]]], dict[str, list[str]]]
def catalog_is_stale(conn, days: int = 7) -> bool                  # meta "catalog_refreshed_at" ausente/antigo ou catálogo vazio
async def refresh_catalog(conn, settings, transport=None) -> dict  # {"markets": {m: n}, "indices": {i: n}, "errors": [str]}
class CatalogError(Exception)
```

Regras: as da spec, seção "Catálogo" (URLs, filtros, mínimos). Detalhes:
- `fetch_us`: `nasdaqlisted.txt` usa as colunas `Symbol`, `Security Name`, `Test Issue`, `ETF`; `otherlisted.txt` usa `ACT Symbol`, `Security Name`, `Test Issue`, `ETF`. Leia pelo cabeçalho, não por posição. Nome: corte em `" - "` e remova sufixos como `" Common Stock"`, `" Class A Common Stock"` → fica só o nome da empresa (limite de 80 caracteres). Símbolo precisa casar com `^[A-Z][A-Z0-9.]{0,9}$`; duplicados entre os arquivos: fica o primeiro.
- `fetch_b3`: símbolo em maiúsculas casando com `^[A-Z0-9]{4,6}[0-9]{1,2}$`; fracionário = símbolo terminado em `F` cujo prefixo também está na lista (descartar).
- `fetch_index`: `IBOV`/`IBRA` → `results[].cod`; `SP500` → coluna `Symbol` do CSV (manter o ponto de `BRK.B`); `NDX` → wikitext da página `Nasdaq-100`: extrair os tickers da tabela de componentes (linhas de tabela cujo primeiro campo é um ticker `^[A-Z]{1,5}$`, aceitando o formato `{{NasdaqSymbol|AAPL}}`); menos de 90 ou mais de 110 tickers → `CatalogError`. Índice fora de `config.INDICES` → `ValueError`.
- Todas as buscas: `User-Agent: Mozilla/5.0 (compatible; RadarQuantBot/1.0)`, timeout 30 s, corpo acima de 5 MB → `CatalogError`; status ≠ 200, JSON/CSV malformado → `CatalogError`.
- `synthetic_catalog`: B3 = `PETR4 Petrobras PN`, `VALE3 Vale ON`, `ITUB4 Itaú Unibanco PN`, `BBAS3 Banco do Brasil ON`, `WEGE3 WEG ON`, `BOVA11 iShares Ibovespa` (ETF), `ABCD3 Alfa ON`, `EFGH4 Beta PN`, `IJKL11 Gama FII` (FII), `MNOP3 Delta ON`; US = `AAPL Apple`, `MSFT Microsoft`, `NVDA NVIDIA`, `SPY SPDR S&P 500` (ETF), `QQQ Invesco QQQ` (ETF), `TSLA Tesla`, `AMZN Amazon`, `GOOG Alphabet`, `META Meta Platforms`, `NFLX Netflix`, `BRK.B Berkshire Hathaway`; CRYPTO = `CRYPTO_CATALOG`. Índices: `IBOV` = PETR4, VALE3, ITUB4, BBAS3, WEGE3; `IBRA` = IBOV + ABCD3, EFGH4, MNOP3; `SP500` = AAPL, MSFT, NVDA, TSLA, AMZN, GOOG, META, NFLX; `NDX` = AAPL, MSFT, NVDA, TSLA.
- `refresh_catalog`: `settings.provider == "synthetic"` → grava o sintético (sem rede, sem mínimos). Senão, cada mercado e cada índice em `try` próprio; mercado só é substituído se `len >= MIN_ROWS[market]` (abaixo disso entra em `errors` e fica o antigo); índice com erro mantém o antigo. Grava `meta["catalog_refreshed_at"]` (ISO UTC) se ao menos um mercado foi atualizado.

- [ ] **Step 1:** Fixtures pequenas e realistas (US: cabeçalho + 6 linhas incluindo teste, `$`, ETF e rodapé `File Creation Time`; brapi com `stock/name/type` incluindo `PETR4F` e um `bdr`; B3 índice com `results`; CSV do S&P com `BRK.B`; wikitext com tabela de 100 tickers gerada no teste).
- [ ] **Step 2:** Testes que falham: parsing e filtros de cada fonte; nome limpo; `fetch_index` dos quatro; NDX com 50 tickers → `CatalogError`; HTTP 500 / corpo não-JSON / corpo de 6 MB → `CatalogError`; `synthetic_catalog` com os índices acima; `refresh_catalog` sintético grava tudo e `catalog_is_stale` vira `False`; **Review Focus 2:** modo live com `MockTransport` em que US devolve 10 linhas (abaixo do mínimo) e IBRA dá 500 → catálogo US e membros de IBRA anteriores continuam, B3 e os outros índices são atualizados, `errors` tem 2 entradas; `catalog_is_stale` com meta de 8 dias atrás → `True`.
- [ ] **Step 3:** Rodar → FALHA. **Step 4:** Implementar. **Step 5:** `pytest tests/test_catalog.py -q` → PASSA. **Não commitar.**

---

### Task 3 [paralela]: Curto prazo — `stats/swing.py`

**Files:** Create `app/stats/swing.py`. Test: `tests/test_swing.py`.

**Consumes:** `app/stats/indicators.py` (`sma`, `rsi`) — leia, não altere.
**Produces:**

```python
SETUPS = {"reversao": {"label": "Reversão rápida", "description": ...},
          "queda": {"label": "Queda extrema", "description": ...},
          "rompimento": {"label": "Rompimento", "description": ...}}     # descrições de uma frase, em pt-BR, com a regra
MAX_HOLD = 10; COST = 0.001; MIN_TRADES = 20; POOL_MIN_TRADES = 100; MAX_MARKERS = 200
@dataclass
class Trade: entry_date: pd.Timestamp; entry_price: float; exit_date: pd.Timestamp; exit_price: float; days: int; net: float; excess: float
def signals(df: pd.DataFrame, key: str) -> tuple[pd.Series, pd.Series]        # (entrada, saída) booleanas no índice de df; só dados até t
def simulate(df, key, cost=COST, max_hold=MAX_HOLD) -> tuple[list[Trade], dict | None]   # operações fechadas, posição aberta
def trade_stats(trades: list[Trade], n_boot: int = 2000, seed: int = 42) -> dict
def setup_report(df, key) -> dict
def context(df) -> dict
def swing_report(df) -> dict                                                   # {"setups": [3 relatórios na ordem de SETUPS], "context": {...}}
def pooled_evidence(pool: list[tuple[int, float]], n_boot: int = 1000, seed: int = 42) -> dict
```

`df`: `DatetimeIndex` crescente, colunas `open, high, low, close, volume`. Regras de entrada/saída, execução, custo, excesso e rótulos: seção 2 da spec, literalmente. Detalhes:
- `signals`: máximas/mínimas/volume "anteriores" usam `shift(1)` antes do `rolling`. NaN → `False`.
- `simulate`: entrada na abertura de *t+1* após sinal em *t* sem posição aberta; saída na abertura de *j+1* após sinal de saída no fechamento de *j* (com *j* ≥ dia de entrada); sem sinal de saída até o 10º pregão em posição → sai no **fechamento** desse 10º pregão. `days` = pregões em posição (entrada conta 1). Sinais de entrada durante uma posição são ignorados. Operação sem saída até o fim dos dados → posição aberta `{"entry_date": ISO, "entry_price", "days", "ret"}` (`ret` até o último fechamento, sem custo de saída). `excess = net − (exp(mu·days) − 1)`, `mu` = média de `log(close/close.shift(1))` do `df` inteiro.
- `trade_stats`: `{"trades", "win_rate", "mean_net", "median_net", "avg_days", "mean_excess", "ci_low", "ci_high", "evidence"}`; zero operações → números `None` exceto `trades: 0`, `evidence: "amostra_insuficiente"`; 1 a 19 operações → estatísticas calculadas, IC `None`, `evidence: "amostra_insuficiente"`.
- `setup_report`: `{"key", "label", "description", "state", "position", "stats", "markers", "pool"}`; `state`: `posicao` se há posição aberta; senão `sinal` se a entrada disparou no último candle; senão `nenhum`. `markers`: `{"time": ISO, "type": "entry" | "exit", "price"}` em ordem cronológica, últimas `MAX_MARKERS` (inclui a entrada de uma posição aberta). `pool`: `[[yyyymm (int, mês da entrada), excess], ...]` de todas as operações fechadas, arredondado a 6 casas.
- `context`: `{"atr_pct", "range_5d", "rel_volume", "dist_high20", "dist_low20"}` — ATR(14) de Wilder / fechamento; `range_5d` = desvio EWMA (λ = 0,94) dos retornos diários × √5; `rel_volume` = volume / média dos 20 anteriores (`None` se a média for 0); distâncias = `close/max(high dos últimos 20) − 1` e `close/min(low dos últimos 20) − 1`.
- `pooled_evidence`: `{"trades", "win_rate", "mean_excess", "ci_low", "ci_high", "evidence"}`; menos de `POOL_MIN_TRADES` → IC `None`, `amostra_insuficiente`; bootstrap reamostrando **meses** (com reposição, mesmo número de meses distintos) e tirando a média de todas as operações dos meses sorteados.
- Chave fora de `SETUPS` → `ValueError`.

- [ ] **Step 1:** Testes que falham (séries construídas à mão, pequenas, com valores conferíveis):
  - **Sem antecipação:** `signals(df, k)` e `signals(df.iloc[:400], k)` coincidem nos 400 primeiros, para os três setups; alterar o último candle não muda sinais anteriores.
  - `rompimento`: série plana com um candle de fechamento acima da máxima anterior e volume 2× → entrada só nesse dia; com volume 1,2× → sem entrada; volume todo zero → nenhuma entrada e nenhum erro.
  - `reversao`: tendência de alta de 300 dias com duas quedas fortes seguidas → entrada disparada; a mesma queda com preço abaixo da SMA200 → sem entrada.
  - `simulate`: entrada no preço de **abertura** de *t+1*; saída na abertura após o sinal; limite de 10 pregões sai no fechamento do 10º com `days == 10`; `net == exit/entry − 1 − 0.002`; segunda entrada durante a posição é ignorada; sinal no último candle → nenhuma operação e `state == "sinal"`; operação em aberto no fim → `state == "posicao"` com `position.days` correto.
  - `trade_stats`: lista vazia; 5 operações (IC `None`, `amostra_insuficiente`); 30 operações com excesso constante +1% → `favoravel` com `ci_low == ci_high == 0.01`; excesso constante −1% → `contraria`; determinístico por semente.
  - `setup_report`: chaves presentes, `markers` em ordem e ≤ 200, `pool` com `yyyymm` inteiro; `json.dumps` do relatório funciona e não contém `NaN`.
  - `context` em série conhecida (ATR de candles com amplitude constante de 2 e preço 100 → `atr_pct ≈ 0.02`); volume zero → `rel_volume is None`.
  - `pooled_evidence`: 50 operações → `amostra_insuficiente`; 300 operações em 30 meses com excesso +0,5% constante → `favoravel`; determinístico; todas num único mês → IC degenerado, sem erro.
  - **Review Focus 3:** preço constante por 600 dias → nenhum sinal, relatório válido, sem `NaN`.
  - `swing_report` devolve 3 setups na ordem de `SETUPS`.
- [ ] **Step 2:** Rodar → FALHA. **Step 3:** Implementar (vetorize os sinais; o laço de simulação pode ser Python puro — são ~2500 candles). **Step 4:** `pytest tests/test_swing.py -q` → PASSA. **Não commitar.**

---

### Task 4 [paralela]: Notícias — `news.py`

**Files:** Create `app/news.py`. Test: `tests/test_news.py`, `tests/fixtures/news_google.xml`, `tests/fixtures/news_yahoo.json`.

**Consumes:** `db.load_news`, `db.replace_news`, `db.catalog_entry`, `Settings`.
**Produces:**

```python
TTL_SECONDS = 1800; MAX_ITEMS = 20; MAX_BODY = 2_000_000; MAX_TITLE = 300
class NewsError(Exception)
def parse_google_rss(text: str) -> list[dict]          # {title, url, source, published_at (ISO UTC ou None)}
def parse_yahoo(payload: dict) -> list[dict]
def merge(items: list[dict]) -> list[dict]             # dedup por título normalizado, ordena por data desc (sem data por último), corta em MAX_ITEMS
def synthetic_news(symbol: str) -> list[dict]          # 3 itens determinísticos, url https://example.com/noticia/<symbol>/<n>
async def fetch_news(symbol: str, market: str, name: str | None, transport=None) -> list[dict]   # NewsError se todas as fontes falharem
async def get_news(conn, asset: dict, settings, transport=None) -> dict   # {"items", "fetched_at", "stale"}
```

Regras: seção 3 da spec. Detalhes:
- `parse_google_rss`: `xml.etree.ElementTree.fromstring`; rejeitar (→ `NewsError`) texto com mais de `MAX_BODY` caracteres ou contendo `<!DOCTYPE` ou `<!ENTITY`; XML malformado → `NewsError`. Por `<item>`: `title`, `link`, `pubDate` (via `email.utils.parsedate_to_datetime`, convertido para ISO UTC; inválido → `None`), `source` (texto). Remover do título o sufixo `" - <source>"` quando existir. Item sem título ou sem link `http(s)` é descartado.
- `parse_yahoo`: `payload["news"][]` → `title`, `link`, `publisher`, `providerPublishTime` (epoch → ISO UTC). Estrutura inesperada → lista vazia (não levanta).
- Saneamento comum: `html.unescape`, colapsar espaços, cortar em `MAX_TITLE`; `source` cortada em 80; URL precisa começar com `http://` ou `https://` (comparação sem diferenciar maiúsculas) e ter no máximo 2000 caracteres.
- `fetch_news`: query do Google conforme a spec (cripto usa `name` ou o símbolo se `name` for vazio); Yahoo só para `US`; mesmo `User-Agent` do projeto, timeout 15 s. Uma fonte falhar não impede a outra; todas falharem → `NewsError`.
- `get_news`: sintético → `synthetic_news` (grava no cache normalmente). Cache com menos de `TTL_SECONDS` → devolve sem rede, `stale: False`. Senão busca (nome via `db.catalog_entry`), grava e devolve. `NewsError` → devolve o cache antigo (ou lista vazia) com `stale: True`.

- [ ] **Step 1:** Fixtures: RSS do Google com 5 itens (um com `&amp;` e sufixo " - InfoMoney", um sem link, um com link `javascript:alert(1)`, dois com o mesmo título de fontes diferentes); JSON do Yahoo com 3 notícias.
- [ ] **Step 2:** Testes que falham: parsing dos dois formatos; sufixo removido; datas em ISO UTC; **Review Focus 5:** link `javascript:` descartado, título de 5000 caracteres cortado em 300, `<!DOCTYPE` → `NewsError`, XML truncado → `NewsError`, corpo de 3 MB → `NewsError`, `parse_yahoo({})` e `parse_yahoo({"news": "x"})` → `[]`; `merge` deduplica, ordena e corta em 20; `fetch_news` monta as queries certas por mercado (B3 em pt-BR, US em en-US + Yahoo, cripto pelo nome) — conferir pela URL recebida no `MockTransport`; Google 500 + Yahoo ok → itens do Yahoo; ambos 500 → `NewsError`; `get_news` sintético devolve 3 itens; segunda chamada dentro do TTL não chama a rede (handler conta chamadas); cache vencido + fonte fora do ar → itens antigos com `stale: True`; sem cache + fonte fora → `{"items": [], "stale": True}`.
- [ ] **Step 3:** Rodar → FALHA. **Step 4:** Implementar. **Step 5:** `pytest tests/test_news.py -q` → PASSA. **Não commitar.**

---

### Task 5 [paralela]: Intraday nos providers

**Files:** Modify `app/providers/yahoo.py`, `binance.py`, `synthetic.py`. Test: acrescentar em `tests/test_providers.py` (ou `tests/test_providers_intraday.py`), fixtures novas.

**Consumes:** `Bar`, `ProviderError`, `UnknownSymbol` de `base.py`.
**Produces:** em cada provider, `NATIVE_INTRADAY` e `async def fetch_intraday(symbol, market, interval) -> tuple[list[Bar], int | None]`.

- **Yahoo:** `NATIVE_INTRADAY = frozenset({"1m", "5m", "30m", "1h"})`; parâmetros: `1m` → `interval=1m&range=7d`; `5m` → `5m`/`60d`; `30m` → `30m`/`60d`; `1h` → `interval=60m&range=730d`; sem `events`. Mesma URL, User-Agent, retentativa e tratamento de erro do diário (reaproveite o código, não duplique). Linhas com OHLC nulo/não finito/≤ 0 descartadas; **sem ajuste por `adjclose`**; volume via `_volume`. `time` = timestamp da barra (inteiro). Atraso = `meta.exchangeDataDelayedBy` se for número ≥ 0, senão `None`. Zero barras válidas → `ProviderError("sem dados intraday")`. Intervalo fora de `NATIVE_INTRADAY` → `ProviderError("intervalo não suportado")`.
  - **Ticker dos EUA com ponto:** no diário e no intraday, mercado `US` troca `.` por `-` (`BRK.B` → `BRK-B`). B3 inalterado.
- **Binance:** `NATIVE_INTRADAY = frozenset({"1m", "3m", "5m", "30m", "1h"})`; uma chamada `klines?symbol=<S>USDT&interval=<i>&limit=1000`, com o mesmo fallback de host; a barra em formação é **mantida**; `time` = `openTime // 1000`; atraso `0`. Linhas malformadas/não finitas descartadas; lista vazia → `ProviderError`.
- **Sintético:** `NATIVE_INTRADAY = frozenset({"1m", "3m", "5m", "30m", "1h"})`; passeio aleatório determinístico (semente = `crc32(f"{market}:{symbol}:{interval}")`), terminando em `2026-10-07T20:00:00Z` (epoch 1791403200), barras consecutivas espaçadas pelo intervalo: 1500 (`1m`), 1000 (`3m`), 1500 (`5m`), 700 (`30m`), 900 (`1h`); atraso `None`. Mesmos símbolos especiais do diário (`INVALID*` → `UnknownSymbol`, `FALHA*` → `ProviderError`); `CURTO*` devolve 50 barras.

- [ ] **Step 1:** Fixtures: resposta intraday do Yahoo com 6 barras (uma nula) e `exchangeDataDelayedBy: 15`; outra sem o campo.
- [ ] **Step 2:** Testes que falham: Yahoo — parâmetros por intervalo (conferir query), barras em ordem, linha nula descartada, atraso 15 e `None`, sem ajuste de preço, `BRK.B` → URL com `BRK-B` no diário e no intraday, `PETR4` → `PETR4.SA`, 404 → `UnknownSymbol`, 429 seguido de 200 funciona, tudo nulo → `ProviderError`, intervalo `"3m"` → `ProviderError`; Binance — query com `interval` e `limit=1000`, `time` em segundos, barra corrente mantida, fallback de host, linha malformada descartada, vazio → `ProviderError`; sintético — determinístico, contagens, espaçamento exato, último `time == 1791403200`, `high >= max(open, close)`, símbolos especiais.
- [ ] **Step 3:** Rodar → FALHA. **Step 4:** Implementar. **Step 5:** `pytest tests/test_providers.py tests/test_providers_intraday.py -q` → PASSA. **Não commitar.**

---

### Task 6: Serviço e análise — intervalos, intraday, abrir ativo, swing

**Files:** Modify `app/service.py`, `app/analysis.py`. Test: acrescentar em `tests/test_service.py`, `tests/test_analysis.py`.

**Consumes:** Tasks 1, 3, 5 (assinaturas reais do código).
**Produces:**

```python
# service.py
def resample(df, interval) -> pd.DataFrame            # "1d","1wk","1mo","3mo","6mo","1y"; rótulo = última data real do período
def aggregate_bars(bars: list[Bar], seconds: int) -> list[Bar]   # piso do time no múltiplo; open primeiro, high máx, low mín, close último, volume soma
async def load_intraday(asset: dict, interval: str, settings, provider=None) -> dict
    # {"bars": list[Bar], "delay_minutes": int | None, "fetched_at": ISO}; cache em memória por (asset_id, interval)
def clear_intraday_cache() -> None
async def open_asset(conn, symbol: str, market: str, settings) -> dict   # devolve o dict do ativo (db.get_asset)
async def refresh_all(conn, settings) -> None          # só watch=1 (comportamento atual, agora explícito)

# analysis.py
def analyze_asset(conn, asset) -> dict                 # status ok ganha "swing" (sem a chave "pool" dos setups)
def swing_pool(conn, asset) -> dict[str, list]         # {chave: pool} da mesma análise em cache; {} se insuficiente
def asset_summary(conn, asset) -> dict                 # ganha "watch": bool, "name": str | None, "indices": list[str]
def candles_payload(conn, asset_id, interval) -> dict  # os 6 intervalos derivados do diário
def intraday_payload(bars: list[Bar], interval: str, delay_minutes: int | None) -> dict
    # {"interval", "intraday": True, "candles": [{"time": int, open, high, low, close, volume}], "indicators": {...mesmas chaves, "time" int},
    #  "last_bar_time": int | None, "delay_minutes": int | None}
```

Regras:
- `resample`: `3mo` = trimestre civil, `6mo` = semestre civil (jan–jun, jul–dez), `1y` = ano civil; mesma agregação OHLCV e mesmo rótulo de última data real já usados em `1wk`/`1mo`. Intervalo intraday ou desconhecido → `ValueError`.
- `load_intraday`: se `interval` ∈ `provider.NATIVE_INTRADAY` busca direto; senão `3m` deriva de `1m` e `10m` de `5m` com `aggregate_bars`; intervalo fora de `INTRADAY` → `ValueError`. TTL: 55 s (`1m`, `3m`), 120 s (`5m`, `10m`), 300 s (`30m`, `1h`). Dicionário de módulo com `threading.Lock`, no máximo 64 entradas (descarta a mais antiga). Erro do provider **não** é cacheado e propaga (`ProviderError`/`UnknownSymbol`).
- `open_asset`: normaliza o símbolo (`normalize_symbol`); se não existe, cria com `watch=False`; atualiza se não houver candles ou `last_refresh` tiver mais de 6 h; `UnknownSymbol` num ativo criado nesta chamada → apaga e relança; qualquer outra exceção num ativo criado nesta chamada → apaga e relança; `touch_viewed`; devolve o ativo relido.
- `analyze_asset`: `swing_report(df)` com as colunas OHLCV do diário; o resultado público não tem `pool`; `swing_pool` lê do mesmo cache (não recalcula). Ativo `insuficiente` não tem `swing`.
- `intraday_payload`: indicadores (`sma20/50/200`, Bollinger, RSI14, MACD) sobre os fechamentos das barras; pontos NaN omitidos; passa por `clean`.

- [ ] **Step 1:** Testes que falham:
  - `resample` `3mo`/`6mo`/`1y` em 3 anos de dias úteis sintéticos: contagens (12, 6, 3), `open` do primeiro pregão e `close` do último de cada período, última data == última do diário; `resample(df, "5m")` → `ValueError`.
  - `aggregate_bars`: 6 barras de 1 min → 2 de 3 min com OHLCV certos; barras com buraco não se juntam fora do múltiplo; lista vazia → `[]`.
  - `load_intraday` (provider sintético): `1m` direto; `3m` no mercado B3 sintético — force a derivação com um provider de teste cujo `NATIVE_INTRADAY` não tem `3m`; segunda chamada dentro do TTL não chama o provider (contador); **Review Focus 4:** chave do cache separa ativo e intervalo (ativo A `1m` ≠ ativo B `1m` ≠ ativo A `5m`); erro do provider propaga e não fica em cache; mais de 64 entradas descarta a mais antiga.
  - `open_asset`: símbolo novo cria `watch=0` com candles e `last_viewed`; segundo `open` não refaz o refresh (contador no provider de teste) e atualiza `last_viewed`; ativo da watchlist continua `watch=1`; `INVALIDO` → `UnknownSymbol` e nada fica gravado; `" tsla "` é normalizado.
  - `analyze_asset`: tem `swing.setups` com 3 itens sem a chave `pool`, `swing.context`; `swing_pool` devolve as 3 chaves; `CURTO1` → sem `swing`, `swing_pool == {}`; `json.dumps` sem `NaN`.
  - `asset_summary`: `watch`, `name` e `indices` vindos do catálogo (grave o catálogo sintético no teste); ativo sem entrada no catálogo → `name None`, `indices []`.
  - `candles_payload` com `3mo`, `6mo`, `1y` → 200 de serviço, última `time` == última data diária.
  - `intraday_payload`: `time` inteiro, `last_bar_time` == último, `sma20` presente, lista vazia → `candles: []`, `last_bar_time: None`.
- [ ] **Step 2:** Rodar → FALHA. **Step 3:** Implementar. **Step 4:** Suíte inteira → PASSA. **Step 5:** Commit: `radar-quant 1.1: intervalos, intraday sob demanda, abrir ativo e curto prazo na análise`.

---

### Task 7: Screener e universo dos índices

**Files:** Create `app/screener.py`, `app/universe.py`. Test: `tests/test_screener.py`, `tests/test_universe.py`.

**Consumes:** Tasks 1, 2, 3, 6.
**Produces:**

```python
# screener.py
SCOPES = ("watchlist", "IBOV", "IBRA", "SP500", "NDX")
class ScreenerError(ValueError)
def build_row(conn, asset: dict) -> dict | None        # None se a análise for insuficiente; inclui "pool" {chave: [[yyyymm, excess], ...]}
def store_row(conn, asset: dict) -> bool               # grava (ou apaga a linha, se insuficiente); devolve se gravou
def scope_assets(conn, scope: str) -> list[dict]       # watchlist -> watch=1; índice -> ativos existentes que são membros
def query(conn, scope="watchlist", market=None, verdict=None, evidence=None, setup=None,
          sort="score", order="desc", page=1, page_size=50) -> dict
def summary(conn, scope: str) -> dict
def progress(conn, scope: str) -> dict                 # {"scope", "total": membros do escopo, "ready": com linha no screener}

# universe.py
STALE_HOURS = 20; MAX_FAILS = 5; PURGE_DAYS = 30
def ensure_assets(conn) -> int                         # cria (watch=0) ativos para membros de índice que ainda não existem; devolve quantos criou
def universe_due(conn, now: datetime) -> bool          # nunca rodou, ou (última passada completa há > 20 h e 5 <= now.hour (UTC) < 9)
async def refresh_universe(conn, settings, pace: float | None = None, limit: int | None = None, sleep=asyncio.sleep) -> dict
    # {"updated", "skipped", "failed", "aborted": bool}; grava meta "universe_refreshed_at" só se terminou sem abortar
def purge(conn, now: datetime) -> int
```

Regras:
- Linha do screener: campos da spec; `name` do catálogo; `price`/`change_pct` do último candle; fatores normalizados; `above_sma200` = `dist_sma200` bruto > 0; `setups` = `{chave: {"state", "evidence"}}`; `as_of`. `query` nunca devolve `pool`.
- `query`: lê `db.load_screener` dos ids do escopo; para `watchlist`, ativo `ok` sem linha é calculado e gravado na hora (`store_row`); para índices só o que já está gravado. Filtros: `market` ∈ MARKETS, `verdict` ∈ {comprar, manter, vender}, `evidence` ∈ {favoravel, contraria, sem_evidencia}, `setup` ∈ SETUPS (linha entra se o estado for `sinal` ou `posicao`). `sort`: `symbol` ou campo numérico da linha; valores `None` sempre por último. Parâmetro inválido, `page < 1`, `page_size` fora de 1..200 → `ScreenerError`. Resposta: `{"scope", "total", "page", "page_size", "rows", "updated_at"}` (`updated_at` = maior `updated_at` das linhas ou `None`).
- `summary`: formato da spec; percentuais sobre as linhas existentes (`count == 0` → percentuais `None`, `pooled` com `amostra_insuficiente`); `setups[].active` = linhas com o setup em `sinal`/`posicao`; `pooled` = `swing.pooled_evidence` sobre a união dos `pool` do escopo. Cache em memória por `(scope, count, updated_at)`.
- `refresh_universe`: `ensure_assets`; para cada ativo de índice com `last_refresh` nulo ou mais velho que `STALE_HOURS`: `service.refresh_asset` (trate `UnknownSymbol` como falha, sem apagar o ativo), `analysis.invalidate(id)`, `store_row`; conta falha se o ativo ficou com `last_error`; `MAX_FAILS` falhas **seguidas** → aborta; `await sleep(pace)` entre ativos (pace padrão `settings.universe_pace`); `limit` corta a passada (para testes). Ativos em dia contam como `skipped`.
- `purge`: `db.purge_viewed` com corte de `PURGE_DAYS` e `keep_ids` = ativos membros de índice.

- [ ] **Step 1:** Testes que falham (banco temporário, catálogo sintético gravado, `Settings(provider="synthetic")`, `sleep` falso que só conta):
  - `ensure_assets` cria os membros que faltam com `watch=0` e é idempotente; ativo já na watchlist não é duplicado nem rebaixado.
  - `refresh_universe`: atualiza todos, grava linhas, `aborted False`, meta gravada, `sleep` chamado com o pace; segunda passada → tudo `skipped`; `limit=2` → 2 atualizados e meta **não** gravada... (defina: com `limit` a passada é parcial e não grava a meta); com um provider que falha sempre → aborta após 5 falhas seguidas, `aborted True`, meta não gravada; falhas intercaladas com sucessos não abortam.
  - `universe_due`: sem meta → `True`; meta de 2 h atrás → `False`; meta de 21 h atrás às 06:00 UTC → `True`, às 14:00 UTC → `False`.
  - `purge`: apaga visitado antigo fora de índice; preserva watchlist, membro de índice e visitado recente.
  - `build_row`: campos presentes, `pool` com 3 chaves; `CURTO1` → `None`; `store_row` de insuficiente apaga linha anterior.
  - `query`: `scope="watchlist"` calcula e grava o que falta; `scope="SP500"` só membros; filtros de mercado, veredito, evidência e setup; ordenação por `symbol` asc e por `volatility` desc com `None` por último; paginação (`total` certo, página 2); sem `pool` nas linhas; parâmetros inválidos → `ScreenerError` (escopo, sort inexistente, `page=0`, `page_size=500`).
  - `summary`: contagens e percentuais batem com as linhas; `pooled` presente por setup; escopo vazio → `count 0` sem erro; segunda chamada usa o cache (mesmo objeto).
  - `progress`: `total` = membros do índice, `ready` cresce conforme as linhas são gravadas.
- [ ] **Step 2:** Rodar → FALHA. **Step 3:** Implementar. **Step 4:** Suíte inteira → PASSA. **Step 5:** Commit: `radar-quant 1.1: screener e atualização do universo dos índices`.

---

### Task 8: API, laços de fundo e versão

**Files:** Modify `app/main.py`, `garod004-apps-radar-quant/umbrel-app.yml`, `garod004-apps-radar-quant/docker-compose.yml`, `README.md` (seção Radar Quant). Test: acrescentar em `tests/test_api.py`.

**Consumes:** tudo acima.

Rotas novas/alteradas:
- `GET /api/search?q=&limit=` (limit 1..25, padrão 12) → lista de `{symbol, market, name, kind, indices}`.
- `POST /api/assets/open {symbol, market}` → 200 com `asset_summary`; mercado inválido/símbolo inválido → 422; `UnknownSymbol` → 422 `símbolo não encontrado em <mercado>`.
- `POST /api/assets` → cria com `watch=1`, **ou promove** um existente com `watch=0` (201 nos dois casos; refaz o refresh só se não houver candles); 409 se já for `watch=1`.
- `DELETE /api/assets/{id}` → membro de índice: `set_watch(False)`; senão apaga. 204 nos dois casos; inexistente → 404.
- `GET /api/assets` → só `watch=1`.
- `GET /api/assets/{id}/candles?interval=` → os 12 intervalos. Diário-derivados como hoje (no threadpool). Intraday: `service.load_intraday` + `analysis.intraday_payload`; `ProviderError`/`UnknownSymbol` → 422 `{"detail": "intraday indisponível para este ativo agora"}`. Intervalo fora de `INTERVALS` → 422.
- `GET /api/assets/{id}/news` → `news.get_news`.
- `GET /api/screener`, `GET /api/screener/summary?scope=`, `GET /api/screener/progress?scope=` → `ScreenerError` vira 422 com a mensagem.
- `GET /api/health` ganha `catalog` (total de linhas) e `universe` (`{"total", "ready"}` somando os índices).
- `GET /api/ranking` continua (compatibilidade).

Laços: o laço atual, depois de cada `refresh_all`, chama `screener.store_row` para cada ativo `watch=1` e, se `catalog.catalog_is_stale`, `catalog.refresh_catalog` (erros logados, nunca derrubam o laço). Novo laço `loop_universe` (só se `settings.universe` e sem `RADAR_SKIP_BACKGROUND`): a cada 600 s, se `universe.universe_due(conn, agora UTC)` → `universe.refresh_universe` e `universe.purge`; exceções logadas. Os dois laços compartilham o `refresh_lock` existente só para o `refresh_all`; o universo usa um lock próprio. No encerramento, as duas tarefas são canceladas. Na subida (lifespan), se o catálogo estiver vazio e o provider for sintético, grava o catálogo sintético de forma síncrona antes de aceitar requisições (para os testes e o E2E); no modo live o catálogo é buscado pelo laço.

Versão: `umbrel-app.yml` → `version: '1.1.0'`, `tagline` e `description` atualizados (catálogo, screener, curto prazo, notícias, intervalos; mantém o aviso de que não é recomendação profissional), `releaseNotes` começando com a 1.1.0 e mantendo a nota da 1.0.0; `docker-compose.yml` → `image: ghcr.io/gabriel-rodrigues-s/radar-quant:1.1.0`; README: seção atualizada.

- [ ] **Step 1:** Testes que falham (fixture existente; `RADAR_UNIVERSE=0` nos testes; a fixture grava o catálogo sintético):
  - `/api/search?q=pet` → PETR4 primeiro; `q=` vazio → `[]`; `q=%25` → 200; `limit=0`/`limit=99` → 422.
  - `/api/assets/open` com `AMZN`/US → 200, `watch False`, e `/api/assets` continua com 13; `/api/assets/{id}/analysis` do ativo aberto → 200 com `swing`; `open` de `INVALIDO` → 422 e nada gravado; mercado `XX` → 422.
  - `POST /api/assets` de `AMZN` depois do `open` → 201 e agora `watch True` (14 na lista); de novo → 409.
  - `DELETE` de `AMZN` (membro de SP500 no sintético) → 204 e o ativo continua existindo com `watch False` (`/api/assets/{id}/analysis` ainda 200); `DELETE` de um ativo fora de índice → 204 e depois 404.
  - Candles: cada um dos 12 intervalos → 200; intraday tem `intraday: true` e `time` inteiro; `interval=2m` → 422; **Review Focus 4:** `open` de `FALHA1`... (não abre: use um ativo `ok` e troque o provider por um que falha só no intraday via `monkeypatch` de `service.get_provider`) → 422 com a mensagem, não 500.
  - `/api/assets/{id}/news` → 200 com 3 itens no sintético; id inexistente → 404.
  - `/api/screener` padrão → `scope == "watchlist"`, `total == 13`; `scope=SP500` antes do universo rodar → `total 0`; depois de `asyncio.run(universe.refresh_universe(...))` com o `conn` do app → total = membros; `setup=reversao`, `verdict=comprar`, `sort=symbol&order=asc`, `page_size=5&page=2` → 200; `scope=XX`, `sort=__class__`, `page=0` → 422.
  - `/api/screener/summary?scope=watchlist` → 200 com 3 setups; `/api/screener/progress?scope=IBRA` → `total 8`.
  - `/api/health` tem `catalog > 0` e `universe`.
  - Varredura de `NaN`/`Infinity` estendida às rotas novas.
- [ ] **Step 2:** Rodar → FALHA. **Step 3:** Implementar. **Step 4:** Suíte inteira → PASSA; fumaça real com uvicorn sintético (porta 8436): `health`, `search`, `open`, um intraday, `news`, `screener`, `summary`; derrubar.
- [ ] **Step 5:** Commit: `radar-quant 1.1: API de busca, intraday, notícias e screener; versão 1.1.0`.

---

### Task 9: Frontend

**Files:** Modify `app/static/index.html`, `style.css`, `app.js`.

**Consumes:** a API da Task 8. Leia `app/main.py` e confira cada rota com `curl` contra o backend sintético antes de escrever.

Requisitos: seção "Interface" e blocos 1–4 da spec, mais:
- **Seletores que já existem não mudam** (o E2E da 1.0 depende deles): `#watchlist [data-asset-id]`/`[data-symbol]`, `#add-symbol`, `#add-market`, `#add-submit`, `#add-error`, `.remove-asset`, `#chart-title`, `#interval-1d`, `#interval-1wk`, `#interval-1mo`, `#price-chart`, `#rsi-chart`, `#macd-chart`, `#rec-card`, `#rec-verdict`, `#rec-score`, `#rec-evidence`, `#rec-factors`, `#equity-chart`, `#tab-*`, `#view-*`, `#ranking-table tbody tr[data-asset-id]`, `#ranking-market`, `#portfolio-*`, `#theme-toggle`, `#refresh-btn`, `#disclaimer`, `window.__radar.state` (`selectedId`, `interval`, `candleCount`).
- **Busca:** `#add-symbol` vira o campo de busca com autocompletar (debounce de 200 ms em `/api/search`); lista `#search-results` com itens `[data-symbol][data-market]` mostrando símbolo, nome, mercado, tipo e índices; navegação por setas/Enter/Esc; escolher um item chama `POST /api/assets/open` e abre o ativo no gráfico **sem** pôr na watchlist. O botão `#add-submit` continua adicionando à watchlist o que estiver digitado (com `#add-market`), como hoje.
- **Cabeçalho do ativo:** botão `#watch-toggle` (`data-watch="true|false"`): "Adicionar à watchlist" → `POST /api/assets`; "Na watchlist" → remove (`DELETE`). Nome do ativo em `#chart-name`. Um ativo aberto fora da watchlist continua selecionado e visível mesmo sem estar em `#watchlist`.
- **Intervalos:** doze botões `#interval-1m`, `-3m`, `-5m`, `-10m`, `-30m`, `-1h`, `-1d`, `-1wk`, `-1mo`, `-3mo`, `-6mo`, `-1y`, com rótulos `1m 3m 5m 10m 30m 1h D S M 3M 6M 1A`. Intraday: `timeScale` com `timeVisible: true`, timestamps deslocados para a hora local do navegador (some `-getTimezoneOffset()*60` aos segundos antes de passar à biblioteca), recarga automática a cada 60 s enquanto o intervalo estiver selecionado (e a aba visível), aviso `#intraday-note` com "último candle HH:MM" e, para ações, "Cotação pode vir com atraso" (+ "atraso informado: N min" quando `delay_minutes` > 0); cripto sem o aviso de atraso. 422 do intraday → `#intraday-note` mostra o `detail` e o gráfico fica vazio com a mensagem, sem erro de script. `state.candleCount` reflete o que está desenhado em qualquer intervalo.
- **Cartão com abas:** `#rec-tab-position` e `#rec-tab-swing`; painel `#swing-card` com três blocos `.swing-setup[data-setup][data-state]`: rótulo, descrição, estado ("Sinal hoje — compra na próxima abertura", "Em posição há N pregões (+x%)", "Sem sinal"), estatísticas (operações, taxa de acerto, retorno médio líquido, duração média), evidência com o mesmo destaque visual do veredito (`favoravel`/`contraria`/`sem_evidencia`/`amostra_insuficiente` → "amostra insuficiente") e o IC; `#swing-context` com ATR, faixa de 5 pregões, volume relativo e distâncias. Clicar num setup o seleciona (`aria-pressed`) e desenha as marcações de entrada/saída no gráfico de preço (`series.setMarkers`) quando o intervalo é `1d`; em outros intervalos as marcações somem. Ativo `insuficiente` → mensagem no painel.
- **Notícias:** `#news-panel` abaixo do gráfico, lista `#news-list` com `a[data-news]` (título por `textContent`, `href` só se começar com `http`, `target="_blank"`, `rel="noopener noreferrer"`), fonte e tempo relativo ("há 3 h"); `#news-empty` quando não houver; marca "pode estar desatualizado" se `stale`. Carrega ao trocar de ativo, com token de sequência.
- **Screener (aba Ranking):** `#screener-scope` (Minha watchlist, Ibovespa, IBrA, S&P 500, Nasdaq-100), `#ranking-market` (já existe), `#screener-verdict`, `#screener-evidence`, `#screener-setup`; a tabela `#ranking-table` passa a ler `/api/screener` com ordenação e paginação **no servidor** (`#screener-prev`, `#screener-next`, `#screener-page` com "página X de Y · N papéis"); colunas novas: nome e setups ativos (selos). Faixa `#screener-summary`: total, % acima da média de 200, distribuição de vereditos e, por setup, ativos hoje + evidência agregada do escopo com IC. Para escopo de índice, se `/api/screener/progress` indicar `ready < total`, mostra "montando o índice: X de Y papéis" em `#screener-progress`. Clicar numa linha abre o ativo no gráfico (via `open` quando não for da watchlist).
- Mantém: tema, responsivo sem rolagem horizontal (os doze botões de intervalo quebram/rolam dentro do próprio contêiner), tokens de sequência em todos os carregamentos, `localStorage` em try/catch, nada de `innerHTML` com dado externo.

- [ ] **Step 1:** Subir o backend sintético e inspecionar as rotas. **Step 2:** Implementar. **Step 3:** `node --check app/static/app.js`; conferir no navegador disponível (busca → abrir AMZN → adicionar à watchlist → trocar para 5m e 3M → aba Curto prazo → notícias → screener SP500); `grep` dos seletores novos; `pytest -q` verde. **Step 4:** Commit: `radar-quant 1.1: busca, intervalos, curto prazo, notícias e screener na interface`.

---

### Task 10: E2E, dados reais, Docker e migração (controlador)

- [ ] Ampliar `e2e/run.sh`: busca com autocompletar; abrir ativo fora da watchlist; `#watch-toggle` promove e rebaixa; os doze intervalos mudam `state.interval`/`candleCount`; aviso de intraday; aba Curto prazo com 3 setups; marcações; notícias com links `http`; screener por escopo, filtros e paginação; resumo.
- [ ] Rodar contra sintético, dados reais e imagem Docker.
- [ ] Migração: subir `ghcr.io/gabriel-rodrigues-s/radar-quant:1.0.0` com um volume, esperar o refresh, parar; subir a imagem nova no mesmo volume; conferir watchlist, candles e análise.
- [ ] Revisão final do branch, correções, merge em `main`, push, CI, conferir a tag `:1.1.0`.
