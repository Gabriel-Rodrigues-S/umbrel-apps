# Radar Quant 1.1 — design (spec)

Data: 2026-10-09. Aprovado por Gabriel em conversa (quatro blocos + push ao final).
Complementa `2026-10-08-radar-quant-design.md`; o que não é citado aqui continua valendo.

## Objetivo

1. **Catálogo e screener:** todos os papéis da B3 e dos EUA pesquisáveis e analisáveis sob demanda; screener pré-analisado dos índices (IBrA, Ibovespa, S&P 500, Nasdaq-100).
2. **Curto prazo:** três setups de swing (1 a 10 pregões) em candles diários, com evidência por ativo e por índice.
3. **Notícias por ação**, na tela do ativo.
4. **Doze intervalos de gráfico:** 1m, 3m, 5m, 10m, 30m, 1h, 1D, 1S, 1M, 3M, 6M, 1A.

Regra herdada da 1.0: nenhum sinal aparece sem a evidência ao lado.

## Fora do escopo

Sinais intraday, venda a descoberto, alertas, sentimento de notícias, fundamentos, cotação em tempo real da B3 (o dado gratuito vem atrasado; provider continua plugável).

## Modelo de dados (migração)

O banco da 1.0.0 instalado precisa ser preservado. Versão do schema em `PRAGMA user_version` (1.0.0 = 0; 1.1.0 = 1); migração idempotente na conexão.

- `assets`: novas colunas `watch INTEGER NOT NULL DEFAULT 1` (1 = watchlist) e `last_viewed TEXT`. Linhas existentes ficam `watch = 1`.
- `catalog(symbol, market, name, kind, indices)` — PK `(symbol, market)`; `kind` ∈ `Ação`, `ETF`, `FII`, `BDR`, `Cripto`; `indices` = códigos separados por vírgula (`IBOV`, `IBRA`, `SP500`, `NDX`), vazio se não pertence a nenhum.
- `screener(asset_id PK, as_of, payload, updated_at)` — `payload` é JSON da linha do screener.
- `news(asset_id, url, title, source, published_at, fetched_at)` — PK `(asset_id, url)`.
- `meta(key PK, value)`.

Um ativo com `watch = 0` é cache: ou pertence a um índice, ou foi só visitado. Visitados fora de índice e sem `last_viewed` nos últimos 30 dias são apagados (com candles, screener e notícias) na rotina diária.

## 1. Catálogo e screener

### Catálogo

Atualizado na subida se vazio e depois a cada 7 dias. Cada fonte falha de forma independente e, se falhar, as linhas antigas daquele mercado ficam.

- **EUA:** `https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt` e `otherlisted.txt` (texto separado por `|`). Descarta `Test Issue = Y`, símbolos com `$` e a linha de rodapé `File Creation Time`. `kind` = `ETF` se a coluna ETF for `Y`, senão `Ação`. Só substitui o mercado se vierem ≥ 3000 linhas.
- **B3:** `https://brapi.dev/api/quote/list` (campo `stocks`: `stock`, `name`, `type`). Descarta fracionários (símbolo terminado em `F` com 5+ caracteres antes dele sendo ticker padrão, ex. `PETR4F`). `type`: `stock` → `Ação`, `fund` → `FII` (ou `ETF` se o nome contiver "ETF"/"ISHARES"/"INDEX"), `bdr` → `BDR`. Só substitui se vierem ≥ 200 linhas.
- **Cripto:** lista fixa dos 20 maiores pares USDT.
- **Índices:** IBOV e IBRA pela API da B3 (`https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall/GetPortfolioDay/<base64 de {"language":"pt-br","pageNumber":1,"pageSize":300,"index":"IBRA","segment":"1"}>`, campo `results[].cod`); S&P 500 por `https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv` (coluna `Symbol`); Nasdaq-100 pela API da Wikipedia (`action=parse&page=Nasdaq-100&prop=wikitext&format=json`, tabela de componentes). Índice cuja fonte falhar mantém a composição anterior. Membro de índice que não esteja no catálogo é inserido.
- Símbolos de classe dos EUA ficam com ponto no catálogo (`BRK.B`); o provider Yahoo troca `.` por `-`.

Busca: `GET /api/search?q=&limit=` — até 12 resultados; primeiro símbolo com prefixo `q`, depois nome contendo `q`; sem diferenciar maiúsculas; caracteres curinga do `LIKE` escapados; `q` vazio → lista vazia.

### Abrir ativo sob demanda

`POST /api/assets/open {symbol, market}`: cria o ativo com `watch = 0` se não existir, atualiza candles se não houver ou se o último refresh tiver mais de 6 h, grava `last_viewed`, devolve o resumo. Símbolo desconhecido pela fonte → 422 e nada fica gravado.

`POST /api/assets` passa a promover (`watch = 1`) um ativo já existente; 409 só se já estiver na watchlist. `DELETE /api/assets/{id}`: se o ativo pertence a algum índice, só rebaixa (`watch = 0`); senão apaga.

Ranking e carteira continuam só sobre `watch = 1`.

### Universo dos índices

Rotina em segundo plano: garante um ativo (`watch = 0`) para cada membro de índice e atualiza os que estão com refresh mais velho que 20 h, uma chamada por `RADAR_UNIVERSE_PACE` segundos (padrão 1,0). Cinco falhas de fonte seguidas abortam a passada (retoma no ciclo seguinte). Depois de cada ativo atualizado, grava a linha do screener. Roda na subida se nunca rodou; depois, uma vez por dia entre 05:00 e 09:00 UTC (madrugada em Manaus). `RADAR_UNIVERSE=0` desliga. A watchlist continua a cada 6 h e também grava suas linhas do screener.

### Screener

`GET /api/screener?scope=&market=&verdict=&evidence=&setup=&sort=&order=&page=&page_size=`

- `scope`: `watchlist` (padrão), `IBOV`, `IBRA`, `SP500`, `NDX`.
- `setup`: chave de setup — só linhas com o setup em `sinal` ou `posicao`.
- `sort`: qualquer coluna numérica da linha ou `symbol`; padrão `score` desc. `page_size` padrão 50, máx. 200.
- Resposta: `{scope, total, page, page_size, rows, updated_at}`.

Linha: `id, symbol, market, name, price, change_pct, score, verdict, evidence, momentum, trend, dist_sma200, reversal, volatility, drawdown, above_sma200, setups {chave: {state, evidence}}, as_of`.

`GET /api/screener/summary?scope=`: `{scope, count, pct_above_sma200, verdicts {comprar, manter, vender}, setups [{key, label, active, pooled {trades, win_rate, mean_excess, ci_low, ci_high, evidence}}]}`.

## 2. Curto prazo (swing)

Só compra. Sobre candles diários ajustados; mínimo de 300 candles.

| Chave | Rótulo | Entrada (no fechamento de *t*) | Saída (no fechamento) |
|---|---|---|---|
| `reversao` | Reversão rápida | RSI(2) < 10 e fechamento > SMA200 | fechamento > SMA5 |
| `queda` | Queda extrema | fechamento < SMA20 − 2·desvio20 e fechamento > SMA200 | fechamento ≥ SMA20 |
| `rompimento` | Rompimento | fechamento > máxima dos 20 pregões anteriores e volume > 1,5 × média de volume dos 20 anteriores | fechamento < mínima dos 10 pregões anteriores |

Execução simulada: sinal no fechamento de *t*, compra na **abertura de *t+1***; saída na abertura seguinte ao sinal de saída; limite de 10 pregões em posição (sai no fechamento do 10º). Uma operação por vez por setup. Custo de 0,1% por ponta. Retorno líquido = saída/entrada − 1 − 0,002.

Evidência por ativo: excesso de cada operação = retorno líquido − retorno esperado de segurar o ativo pelo mesmo número de pregões (`exp(μ·h) − 1`, μ = média do log-retorno diário do histórico). Bootstrap i.i.d. das operações (2000 reamostragens, semente fixa) → IC de 95% do excesso médio. Rótulo: menos de 20 operações → `amostra_insuficiente`; limite inferior > 0 → `favoravel`; superior < 0 → `contraria`; senão `sem_evidencia`.

Estado no último candle: `sinal` (entrada disparou hoje; compra seria na próxima abertura), `posicao` (operação simulada aberta: data e preço de entrada, pregões decorridos, retorno até agora), `nenhum`.

Contexto: ATR(14) em % do preço; faixa esperada para 5 pregões (± volatilidade EWMA diária × √5); volume relativo (volume / média de 20); distância da máxima e da mínima de 20 pregões.

Evidência do índice (`pooled`): junta os excessos de todas as operações do setup em todos os ativos do escopo; bootstrap **por mês de entrada** (reamostra meses inteiros, 1000 vezes) para respeitar a correlação entre papéis no mesmo período. Menos de 100 operações → `amostra_insuficiente`.

A análise do ativo (`GET /api/assets/{id}/analysis`) ganha `swing: {setups: [...], context: {...}}`; cada setup traz `key, label, description, state, position, stats {trades, win_rate, mean_net, median_net, avg_days, mean_excess, ci_low, ci_high, evidence}, markers [{time, type, price}]` (últimas 200 marcações).

## 3. Notícias

`GET /api/assets/{id}/news` → `{items: [{title, url, source, published_at}], fetched_at, stale}`.

- Google Notícias RSS (`https://news.google.com/rss/search`): B3 → `q=<símbolo>`, `hl=pt-BR&gl=BR&ceid=BR:pt-419`; EUA → `q=<símbolo> stock`, `hl=en-US&gl=US&ceid=US:en`; cripto → `q=<nome>`, pt-BR.
- Yahoo (`https://query1.finance.yahoo.com/v1/finance/search?q=<símbolo>&newsCount=10&quotesCount=0`) só para EUA.
- Junta, remove duplicatas por título normalizado, ordena por data decrescente, até 20 itens. Só URLs `http(s)`; título limitado a 300 caracteres; o sufixo " - Fonte" do Google é removido do título.
- RSS lido com `xml.etree.ElementTree`; corpo acima de 2 MB ou contendo `<!DOCTYPE`/`<!ENTITY` é rejeitado.
- Cache no SQLite por 30 minutos. Se a busca falhar e houver cache, devolve o cache com `stale: true`; sem cache, lista vazia com `stale: true`.
- Buscadas só quando o ativo é aberto. Só título, fonte, data e link — sem texto da matéria.

## 4. Intervalos do gráfico

`GET /api/assets/{id}/candles?interval=` aceita `1m, 3m, 5m, 10m, 30m, 1h, 1d, 1wk, 1mo, 3mo, 6mo, 1y`.

- **Derivados do diário:** `1wk` (W-FRI), `1mo`, `3mo` (trimestre civil), `6mo` (semestre civil), `1y` (ano civil), sempre rotulados com a última data real de pregão do período.
- **Intraday**, sob demanda, nunca gravado em disco:

| Intervalo | Ações (Yahoo) | Cripto (Binance) |
|---|---|---|
| 1m | `interval=1m&range=7d` | `1m`, 1000 barras |
| 3m | agregado do 1m | `3m` |
| 5m | `interval=5m&range=60d` | `5m` |
| 10m | agregado do 5m | agregado do `5m` |
| 30m | `interval=30m&range=60d` | `30m` |
| 1h | `interval=60m&range=730d` | `1h` |

  Agregação por piso do timestamp no múltiplo do intervalo. Cache em memória: 55 s (1m, 3m), 120 s (5m, 10m), 300 s (30m, 1h); no máximo 64 entradas.
- Resposta intraday: `time` em segundos epoch UTC; campos extras `intraday: true`, `last_bar_time`, `delay_minutes` (o que a fonte informar em `exchangeDataDelayedBy`, ou `null`). Indicadores iguais aos do diário.
- Sinais (score, setups, evidência) continuam diários.

Tela: doze botões de intervalo; nos intraday o eixo mostra hora local do navegador, o gráfico se atualiza a cada 60 s e aparece o aviso "Cotação de ações pode vir com atraso; último candle HH:MM" (com o atraso informado pela fonte quando houver). Cripto não mostra o aviso de atraso.

## Interface

- **Busca:** campo com autocompletar (símbolo, nome, mercado, tipo, índices). Escolher um resultado abre o ativo; o cabeçalho do gráfico mostra o botão "Adicionar à watchlist" / "Na watchlist".
- **Cartão de recomendação** com duas abas: "Posição" (o da 1.0) e "Curto prazo" (três setups com estado, estatísticas e evidência; contexto; ao selecionar um setup, marcações de entrada/saída no gráfico diário).
- **Notícias:** painel abaixo do gráfico; links abrem em nova aba com `rel="noopener noreferrer"`.
- **Ranking → Screener:** seletor de escopo, filtros de veredito, evidência e setup, paginação, faixa de resumo do índice (amplitude + evidência agregada por setup). Clicar numa linha abre o ativo.
- Estados: buscando dados do ativo recém-aberto; screener do índice ainda sendo montado (mostra quantos de quantos); sem notícias; intraday indisponível para o ativo.

## Testes e entrega

- TDD por módulo; providers e fontes com `httpx.MockTransport`; nada de rede nos testes.
- Migração: banco criado pelo schema da 1.0.0 abre na 1.1.0 com os dados intactos.
- E2E (`agent-browser`) ampliado: busca, abrir ativo fora da watchlist, promover, doze intervalos, aba Curto prazo, notícias, screener por índice e filtros.
- Verificação com dados reais e com a imagem Docker, incluindo subir a 1.1.0 sobre um volume criado pela 1.0.0.
- Versão `1.1.0` no manifest; compose aponta para `radar-quant:1.1.0`.
