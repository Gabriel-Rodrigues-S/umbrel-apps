/* Radar Quant — frontend em módulo único, sem build e sem dependências além
   da Lightweight Charts (vendor/). Todo texto vindo da API entra no DOM por
   textContent. */
(function () {
  "use strict";

  // ------------------------------------------------------------------ tema
  // Roda antes do <body> existir para não piscar o tema errado.
  var THEME_KEY = "radar-quant:theme";
  var SELECTED_KEY = "radar-quant:selected";
  var OPENED_KEY = "radar-quant:opened";   // {symbol, market} do ativo aberto fora da watchlist

  function storageGet(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
  }
  function storageSet(key, value) {
    try { window.localStorage.setItem(key, value); } catch (e) { /* armazenamento indisponível */ }
  }

  var savedTheme = storageGet(THEME_KEY);
  var initialTheme = savedTheme === "light" || savedTheme === "dark" ? savedTheme : "dark";
  document.documentElement.setAttribute("data-theme", initialTheme);

  // ---------------------------------------------------------------- estado
  var state = {
    theme: initialTheme,
    tab: "chart",
    assets: [],
    assetsLoaded: false,
    opened: null,     // resumo do ativo aberto pela busca/screener que não está na watchlist
    opening: null,    // { symbol, market } enquanto POST /api/assets/open está em curso
    selectedId: null,
    interval: "1d",
    candleCount: 0,
    markerCount: 0,
    overlays: { sma20: true, sma50: true, sma200: true, bb: false },
    recTab: "position",
    swingSetup: null,
    screener: { rows: [], total: 0, page: 1, pageSize: 50, sort: "score", order: "desc" },
  };
  window.__radar = { state: state };

  var MIN_CANDLES = 300;
  var INTERVALS = ["1m", "3m", "5m", "10m", "30m", "1h", "1d", "1wk", "1mo", "3mo", "6mo", "1y"];
  var INTRADAY = { "1m": 1, "3m": 1, "5m": 1, "10m": 1, "30m": 1, "1h": 1 };
  var VIEW_SPAN = { "1d": 180, "1wk": 156, "1mo": 120, "3mo": 80, "6mo": 60, "1y": 40 };
  var INTRADAY_SPAN = 200;
  var INTRADAY_RELOAD_MS = 60000;
  var INTRADAY_FRESH_S = 6 * 3600;   // último candle mais velho que isto: mercado fechado
  var INDEX_LABEL = { IBOV: "Ibovespa", IBRA: "IBrA", SP500: "S&P 500", NDX: "Nasdaq-100" };
  var MARKET_ORDER = ["B3", "US", "CRYPTO"];
  var MARKET_LABEL = { B3: "B3", US: "EUA", CRYPTO: "Cripto" };
  var VERDICT_LABEL = { comprar: "Comprar", manter: "Manter", vender: "Vender", insuficiente: "Dados insuficientes" };
  var VERDICT_SHORT = { comprar: "Comprar", manter: "Manter", vender: "Vender", insuficiente: "Insuficiente" };
  var EVIDENCE_LABEL = {
    favoravel: "evidência favorável",
    contraria: "evidência contrária",
    sem_evidencia: "sem evidência estatística",
  };
  var EVIDENCE_SHORT = { favoravel: "favorável", contraria: "contrária", sem_evidencia: "sem evid." };
  // Setups de curto prazo têm um rótulo a mais: poucas operações para concluir algo.
  var SWING_EVIDENCE_LABEL = {
    favoravel: "evidência favorável",
    contraria: "evidência contrária",
    sem_evidencia: "sem evidência estatística",
    amostra_insuficiente: "amostra insuficiente",
  };
  var SWING_EVIDENCE_LEGEND = {
    favoravel: "favorável", contraria: "contrária", sem_evidencia: "sem evidência", amostra_insuficiente: "amostra insuficiente",
  };
  var SWING_EVIDENCE_SHORT = {
    favoravel: "favorável", contraria: "contrária", sem_evidencia: "s/ evid.", amostra_insuficiente: "amostra insuf.",
  };
  var SWING_EVIDENCE_ORDER = ["favoravel", "contraria", "sem_evidencia", "amostra_insuficiente"];
  var SETUP_SHORT = { reversao: "Reversão", queda: "Queda", rompimento: "Rompimento" };
  var SETUP_STATE_SHORT = { sinal: "sinal", posicao: "posição" };
  var EVIDENCE_EXPLAIN = {
    favoravel: "O intervalo inteiro fica acima de zero: no histórico, a estratégia superou segurar o ativo.",
    contraria: "O intervalo inteiro fica abaixo de zero: no histórico, a estratégia foi pior que segurar o ativo.",
    sem_evidencia: "O intervalo inclui zero: o histórico não distingue a estratégia de simplesmente segurar o ativo.",
  };
  var UP = "#26a69a";
  var DOWN = "#ef5350";
  var HEAT_POS = "38, 166, 154";
  var HEAT_NEG = "239, 83, 80";

  function $(id) { return document.getElementById(id); }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function hideIfPresent(id) {
    var node = $(id);
    if (node) node.hidden = true;
  }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  function isNum(v) { return typeof v === "number" && isFinite(v); }

  // ------------------------------------------------------------ formatação
  var LOCALE = "pt-BR";
  var DASH = "—";

  function priceDigits(v) {
    var a = Math.abs(v);
    if (!isNum(v) || a === 0 || a >= 1) return 2;
    if (a >= 0.01) return 4;
    return 6;
  }

  function fmtNum(v, digits) {
    if (!isNum(v)) return DASH;
    var d = digits === undefined ? 2 : digits;
    return new Intl.NumberFormat(LOCALE, { minimumFractionDigits: d, maximumFractionDigits: d }).format(v);
  }

  function fmtSigned(v, digits) {
    if (!isNum(v)) return DASH;
    var d = digits === undefined ? 2 : digits;
    return new Intl.NumberFormat(LOCALE, {
      minimumFractionDigits: d, maximumFractionDigits: d, signDisplay: "exceptZero",
    }).format(v);
  }

  function fmtMoney(v, currency) {
    if (!isNum(v)) return DASH;
    var d = priceDigits(v);
    try {
      return new Intl.NumberFormat(LOCALE, {
        style: "currency", currency: currency || "USD", minimumFractionDigits: d, maximumFractionDigits: d,
      }).format(v);
    } catch (e) {
      return fmtNum(v, d) + (currency ? " " + currency : "");
    }
  }

  // Percentual com sinal (variações, retornos, drawdown).
  function fmtPct(v, digits) {
    if (!isNum(v)) return DASH;
    var d = digits === undefined ? 2 : digits;
    return new Intl.NumberFormat(LOCALE, {
      style: "percent", minimumFractionDigits: d, maximumFractionDigits: d, signDisplay: "exceptZero",
    }).format(v);
  }

  // Percentual sem sinal (níveis: volatilidade, pesos, tempo posicionado).
  function fmtShare(v, digits) {
    if (!isNum(v)) return DASH;
    var d = digits === undefined ? 1 : digits;
    return new Intl.NumberFormat(LOCALE, {
      style: "percent", minimumFractionDigits: d, maximumFractionDigits: d,
    }).format(v);
  }

  function fmtCompact(v) {
    if (!isNum(v)) return DASH;
    return new Intl.NumberFormat(LOCALE, { notation: "compact", maximumFractionDigits: 2 }).format(v);
  }

  function fmtDate(iso) {
    if (typeof iso !== "string") return DASH;
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
    return m ? m[3] + "/" + m[2] + "/" + m[1] : iso;
  }

  // "07/10" — data curta do candle diário nos selos e no cartão de curto prazo.
  function fmtDay(iso) {
    var m = typeof iso === "string" ? /^\d{4}-(\d{2})-(\d{2})/.exec(iso) : null;
    return m ? m[2] + "/" + m[1] : "";
  }

  // Onde a tela dizia "hoje"/"fechamento": o último candle diário pode ser de um pregão em andamento.
  function candleText(asOf, short) {
    var day = short ? fmtDay(asOf) : (typeof asOf === "string" && asOf ? fmtDate(asOf) : "");
    return day ? "candle de " + day : "último candle";
  }

  function fmtDateTime(iso) {
    if (typeof iso !== "string" || !iso) return "";  // new Date(null) é o epoch 0, não uma data inválida
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return new Intl.DateTimeFormat(LOCALE, {
      day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
    }).format(d);
  }

  // Barra intraday já deslocada para a hora local (ver drawCandles): lê-se em UTC.
  function fmtBarTime(shifted) {
    var d = new Date(shifted * 1000);
    if (isNaN(d.getTime())) return DASH;
    var two = function (n) { return String(n).padStart(2, "0"); };
    return two(d.getUTCDate()) + "/" + two(d.getUTCMonth() + 1) + " " + two(d.getUTCHours()) + ":" + two(d.getUTCMinutes());
  }

  // Idade do último candle intraday: "há 15 min", "há 1 h 05 min".
  function fmtAge(seconds) {
    var min = Math.max(0, Math.round(seconds / 60));
    if (min < 60) return "há " + min + " min";
    return "há " + Math.floor(min / 60) + " h " + String(min % 60).padStart(2, "0") + " min";
  }

  // "há 3 h" — tempo relativo curto para as notícias.
  function fmtAgo(iso) {
    if (typeof iso !== "string" || !iso) return "";
    var t = Date.parse(iso);
    if (isNaN(t)) return "";
    var s = (Date.now() - t) / 1000;
    if (s < 60) return "agora";
    if (s < 3600) return "há " + Math.floor(s / 60) + " min";
    if (s < 86400) return "há " + Math.floor(s / 3600) + " h";
    if (s < 30 * 86400) return "há " + Math.floor(s / 86400) + " d";
    return new Intl.DateTimeFormat(LOCALE, { day: "2-digit", month: "2-digit", year: "numeric" }).format(new Date(t));
  }

  function isIntraday(interval) { return INTRADAY[interval] === 1; }

  function signClass(v) {
    if (!isNum(v) || v === 0) return "";
    return v > 0 ? "pos" : "neg";
  }

  // Nome da empresa para exibir ao lado do código. Vazio quando não há nome ou
  // quando ele só repete o código (FIIs, ETFs e BDRs vêm assim do catálogo da B3).
  function displayName(name, symbol) {
    if (typeof name !== "string") return "";
    var text = name.trim();
    if (!text || text.toUpperCase() === String(symbol || "").trim().toUpperCase()) return "";
    return text;
  }

  function marketLabel(m) { return MARKET_LABEL[m] || m || ""; }

  // ------------------------------------------------------------------- API
  function ApiError(status, detail) {
    this.name = "ApiError";
    this.status = status;
    this.message = detail;
  }
  ApiError.prototype = Object.create(Error.prototype);

  function detailText(body) {
    if (!body || body.detail === undefined || body.detail === null) return "";
    var d = body.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      return d.map(function (item) {
        if (item && typeof item === "object") {
          var where = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : "";
          return (where ? where + ": " : "") + (item.msg || "valor inválido");
        }
        return String(item);
      }).join("; ");
    }
    return String(d);
  }

  function api(path, options) {
    return fetch(path, options).then(function (res) {
      if (res.status === 204) return null;
      return res.json().catch(function () { return null; }).then(function (body) {
        if (!res.ok) throw new ApiError(res.status, detailText(body) || "Erro " + res.status + " do servidor.");
        return body;
      });
    }, function () {
      throw new ApiError(0, "Sem conexão com o servidor.");
    });
  }

  function isNetworkFailure(err) {
    return !(err instanceof ApiError) || err.status === 0 || err.status >= 500;
  }

  function showNetError(err, text) {
    var msg = text ? text : err && err.status >= 500
      ? "O servidor respondeu com erro (" + err.status + ")."
      : "Não foi possível falar com o servidor.";
    $("net-error-msg").textContent = msg;
    $("net-error").hidden = false;
  }

  function hideNetError() { $("net-error").hidden = true; }

  function report(err) {
    if (isNetworkFailure(err)) showNetError(err);
    if (window.console && !(err instanceof ApiError)) console.error(err);
  }

  // -------------------------------------------------------------- gráficos
  var charts = null;      // { price, rsi, macd, equity } — cada um { chart, el, ... }
  var chartData = null;   // dados do ativo em exibição, indexados por data
  var hoverOwner = null;  // gráfico sob o mouse (único que propaga o crosshair)
  var loadedKey = "";     // "id|intervalo" do que está desenhado
  var chartDigits = 2;
  var syncPaused = 0;     // > 0 enquanto um intervalo visível é aplicado por código
  // Intervalo escolhido pelo usuário. state.interval é o do que está desenhado:
  // só muda quando a resposta chega, para candleCount e interval andarem juntos.
  var selInterval = "1d";
  var drawnIntraday = false;  // tipo de tempo do que está nas séries (segundos x datas)
  var swingData = null;   // analysis.swing do ativo em exibição (setups com marcações)

  // A biblioteca aplica o intervalo no próximo quadro; sem pausar a
  // sincronização, os eventos intermediários de setData de um painel
  // sobrescrevem o intervalo recém-pedido nos outros.
  function showRange(range) {
    var apply = function () {
      [charts.price, charts.rsi, charts.macd].forEach(function (c) {
        c.chart.timeScale().setVisibleLogicalRange(range);
      });
    };
    syncPaused++;
    apply();
    var frame = window.requestAnimationFrame || function (fn) { return window.setTimeout(fn, 16); };
    frame(function () { frame(function () { apply(); syncPaused--; }); });
  }

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function palette() {
    return {
      bg: cssVar("--panel"),
      text: cssVar("--muted"),
      grid: cssVar("--border"),
      line: cssVar("--border-strong"),
      sma20: cssVar("--c-sma20"),
      sma50: cssVar("--c-sma50"),
      sma200: cssVar("--c-sma200"),
      bb: cssVar("--c-bb"),
      strategy: cssVar("--c-strategy"),
      buyhold: cssVar("--c-buyhold"),
      rsi: cssVar("--c-sma200"),
      macd: cssVar("--c-sma50"),
      signal: cssVar("--c-sma20"),
    };
  }

  function timeKey(t) {
    if (typeof t === "string") return t;
    if (typeof t === "number") return String(t);  // intraday: segundos já deslocados
    if (t && typeof t === "object" && "year" in t) {
      return t.year + "-" + String(t.month).padStart(2, "0") + "-" + String(t.day).padStart(2, "0");
    }
    return "";
  }

  function baseOptions(p, el, showTime, formatter) {
    return {
      width: Math.max(el.clientWidth, 10),
      height: Math.max(el.clientHeight, 10),
      layout: {
        background: { type: "solid", color: p.bg },
        textColor: p.text,
        fontSize: 11,
        fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
      },
      grid: { vertLines: { color: p.grid }, horzLines: { color: p.grid } },
      rightPriceScale: { borderColor: p.line, minimumWidth: 78 },
      timeScale: { borderColor: p.line, visible: showTime, rightOffset: 3, minBarSpacing: 1 },
      crosshair: { mode: 0 },
      localization: { locale: LOCALE, priceFormatter: formatter },
    };
  }

  function themeOptions(p) {
    return {
      layout: { background: { type: "solid", color: p.bg }, textColor: p.text },
      grid: { vertLines: { color: p.grid }, horzLines: { color: p.grid } },
      rightPriceScale: { borderColor: p.line },
      timeScale: { borderColor: p.line },
    };
  }

  function lineOpts(color, extra) {
    var o = {
      color: color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
      crosshairMarkerVisible: false,
    };
    if (extra) Object.keys(extra).forEach(function (k) { o[k] = extra[k]; });
    return o;
  }

  function createCharts() {
    var LC = window.LightweightCharts;
    if (!LC || typeof LC.createChart !== "function") return false;
    var p = palette();
    var priceFmt = function (v) { return fmtNum(v, chartDigits); };
    var plainFmt = function (v) { return fmtNum(v, 2); };

    // --- preço + volume + médias
    var priceEl = $("price-chart");
    var price = LC.createChart(priceEl, baseOptions(p, priceEl, false, priceFmt));
    var volume = price.addHistogramSeries({
      priceScaleId: "", priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false,
    });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    var bbUpper = price.addLineSeries(lineOpts(p.bb, { lineStyle: 2, visible: state.overlays.bb }));
    var bbLower = price.addLineSeries(lineOpts(p.bb, { lineStyle: 2, visible: state.overlays.bb }));
    var sma200 = price.addLineSeries(lineOpts(p.sma200, { visible: state.overlays.sma200 }));
    var sma50 = price.addLineSeries(lineOpts(p.sma50, { visible: state.overlays.sma50 }));
    var sma20 = price.addLineSeries(lineOpts(p.sma20, { visible: state.overlays.sma20 }));
    var candles = price.addCandlestickSeries({
      upColor: UP, downColor: DOWN, borderUpColor: UP, borderDownColor: DOWN, wickUpColor: UP, wickDownColor: DOWN,
    });
    candles.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.22 } });

    // --- RSI
    var rsiEl = $("rsi-chart");
    var rsi = LC.createChart(rsiEl, baseOptions(p, rsiEl, false, plainFmt));
    var rsiLine = rsi.addLineSeries(lineOpts(p.rsi, {
      lineWidth: 2, lastValueVisible: true,
      autoscaleInfoProvider: function () { return { priceRange: { minValue: 0, maxValue: 100 } }; },
    }));
    var guide = function (value) {
      return rsiLine.createPriceLine({
        price: value, color: p.line, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "",
      });
    };
    var rsiGuides = [guide(70), guide(30)];
    rsiLine.priceScale().applyOptions({ scaleMargins: { top: 0.06, bottom: 0.06 } });

    // --- MACD
    var macdEl = $("macd-chart");
    var macd = LC.createChart(macdEl, baseOptions(p, macdEl, true, plainFmt));
    var macdHist = macd.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });
    var macdLine = macd.addLineSeries(lineOpts(p.macd, { lineWidth: 2 }));
    var macdSignal = macd.addLineSeries(lineOpts(p.signal, { lineWidth: 2 }));

    // --- equity (independente dos outros três)
    var eqEl = $("equity-chart");
    var eqOpts = baseOptions(p, eqEl, true, plainFmt);
    eqOpts.rightPriceScale.minimumWidth = 0;
    eqOpts.handleScroll = false;
    eqOpts.handleScale = false;
    var equity = LC.createChart(eqEl, eqOpts);
    var eqBuyHold = equity.addLineSeries(lineOpts(p.buyhold, { lineWidth: 2 }));
    var eqStrategy = equity.addLineSeries(lineOpts(p.strategy, { lineWidth: 2 }));

    charts = {
      price: { chart: price, el: priceEl, main: candles, valueOf: function (t) { var c = chartData && chartData.candle[t]; return c ? c.close : undefined; } },
      rsi: { chart: rsi, el: rsiEl, main: rsiLine, valueOf: function (t) { return chartData ? chartData.ind.rsi14[t] : undefined; } },
      macd: { chart: macd, el: macdEl, main: macdLine, valueOf: function (t) { return chartData ? chartData.ind.macd[t] : undefined; } },
      equity: { chart: equity, el: eqEl },
      series: {
        candles: candles, volume: volume, sma20: sma20, sma50: sma50, sma200: sma200,
        bbUpper: bbUpper, bbLower: bbLower, rsi: rsiLine, rsiGuides: rsiGuides,
        macdHist: macdHist, macd: macdLine, macdSignal: macdSignal,
        eqStrategy: eqStrategy, eqBuyHold: eqBuyHold,
      },
    };

    window.__radar.charts = charts;  // só para depuração/E2E

    var synced = [charts.price, charts.rsi, charts.macd];

    // Sincroniza o intervalo visível entre os três painéis.
    var syncing = false;
    synced.forEach(function (src) {
      src.chart.timeScale().subscribeVisibleLogicalRangeChange(function (range) {
        if (syncing || syncPaused > 0 || !range) return;
        syncing = true;
        synced.forEach(function (other) {
          if (other !== src) other.chart.timeScale().setVisibleLogicalRange(range);
        });
        syncing = false;
      });
    });

    // Crosshair: só o gráfico sob o mouse propaga, o que evita eco entre eles.
    synced.forEach(function (src) {
      src.el.addEventListener("mouseenter", function () { hoverOwner = src; });
      src.el.addEventListener("mouseleave", function () {
        if (hoverOwner === src) hoverOwner = null;
        synced.forEach(function (c) { c.chart.clearCrosshairPosition(); });
        renderLegends(null);
      });
      src.chart.subscribeCrosshairMove(function (param) {
        if (hoverOwner !== src) return;
        var t = param && param.time !== undefined ? timeKey(param.time) : null;
        synced.forEach(function (other) {
          if (other === src) return;
          var v = t ? other.valueOf(t) : undefined;
          if (t && isNum(v)) other.chart.setCrosshairPosition(v, param.time, other.main);
          else other.chart.clearCrosshairPosition();
        });
        renderLegends(t);
      });
    });

    // Redimensiona junto com o contêiner (inclui voltar de uma aba oculta).
    if (typeof ResizeObserver === "function") {
      var ro = new ResizeObserver(function (entries) {
        entries.forEach(function (entry) {
          var target = entry.target;
          var w = target.clientWidth, h = target.clientHeight;
          if (w < 10 || h < 10) return;
          [charts.price, charts.rsi, charts.macd, charts.equity].forEach(function (c) {
            if (c.el === target) c.chart.resize(w, h);
          });
        });
      });
      [priceEl, rsiEl, macdEl, eqEl].forEach(function (node) { ro.observe(node); });
    }
    return true;
  }

  function applyChartTheme() {
    if (!charts) return;
    var p = palette();
    var opts = themeOptions(p);
    [charts.price, charts.rsi, charts.macd, charts.equity].forEach(function (c) { c.chart.applyOptions(opts); });
    var s = charts.series;
    s.sma20.applyOptions({ color: p.sma20 });
    s.sma50.applyOptions({ color: p.sma50 });
    s.sma200.applyOptions({ color: p.sma200 });
    s.bbUpper.applyOptions({ color: p.bb });
    s.bbLower.applyOptions({ color: p.bb });
    s.rsi.applyOptions({ color: p.rsi });
    s.rsiGuides.forEach(function (g) { g.applyOptions({ color: p.line }); });
    s.macd.applyOptions({ color: p.macd });
    s.macdSignal.applyOptions({ color: p.signal });
    s.eqStrategy.applyOptions({ color: p.strategy });
    s.eqBuyHold.applyOptions({ color: p.buyhold });
  }

  function applyOverlays() {
    Object.keys(state.overlays).forEach(function (key) {
      var btn = document.querySelector('[data-overlay="' + key + '"]');
      if (btn) btn.setAttribute("aria-pressed", String(state.overlays[key]));
    });
    if (!charts) return;
    var s = charts.series;
    s.sma20.applyOptions({ visible: state.overlays.sma20 });
    s.sma50.applyOptions({ visible: state.overlays.sma50 });
    s.sma200.applyOptions({ visible: state.overlays.sma200 });
    s.bbUpper.applyOptions({ visible: state.overlays.bb });
    s.bbLower.applyOptions({ visible: state.overlays.bb });
    renderLegends(null);
  }

  function toMap(points, shift) {
    var map = Object.create(null);
    (points || []).forEach(function (pt) {
      if (pt && isNum(pt.value)) map[shift && isNum(pt.time) ? pt.time + shift : pt.time] = pt.value;
    });
    return map;
  }

  // Devolve um ponto por candle (vazio onde o indicador ainda não existe), para
  // que os três painéis tenham exatamente a mesma escala de tempo.
  function aligned(times, map, colorFn) {
    return times.map(function (t) {
      var v = map[t];
      if (!isNum(v)) return { time: t };
      var pt = { time: t, value: v };
      if (colorFn) pt.color = colorFn(v);
      return pt;
    });
  }

  function setOverlay(text) {
    var node = $("chart-overlay");
    if (text) { node.textContent = text; node.hidden = false; }
    else { node.hidden = true; node.textContent = ""; }
  }

  function drawCandles(payload, resetView) {
    var intraday = !!(payload && payload.intraday);
    // Intraday chega em segundos epoch UTC e a biblioteca desenha em UTC: soma-se
    // o deslocamento do fuso do navegador para o eixo mostrar a hora local. Um
    // único deslocamento para a série inteira mantém os tempos estritamente crescentes.
    var shift = intraday ? -new Date().getTimezoneOffset() * 60 : 0;
    var rows = (payload && Array.isArray(payload.candles) ? payload.candles : []).filter(function (c) {
      return c && (intraday ? isNum(c.time) : typeof c.time === "string")
        && isNum(c.open) && isNum(c.high) && isNum(c.low) && isNum(c.close);
    }).map(function (c) {
      return { time: intraday ? c.time + shift : c.time, open: c.open, high: c.high, low: c.low, close: c.close, volume: c.volume };
    });
    var ind = (payload && payload.indicators) || {};
    var times = rows.map(function (c) { return c.time; });

    chartData = { times: times, candle: Object.create(null), ind: {}, intraday: intraday };
    rows.forEach(function (c) { chartData.candle[c.time] = c; });
    ["sma20", "sma50", "sma200", "bb_upper", "bb_lower", "rsi14", "macd", "macd_signal", "macd_hist"].forEach(function (k) {
      chartData.ind[k] = toMap(ind[k], shift);
    });

    state.candleCount = rows.length;
    if (!charts) { setOverlay("A biblioteca de gráficos não carregou. Recarregue a página."); return; }

    var last = rows.length ? rows[rows.length - 1].close : NaN;
    chartDigits = priceDigits(last);
    var s = charts.series;
    if (intraday !== drawnIntraday) {
      // Datas e segundos não convivem na mesma escala: esvazia tudo antes de trocar.
      s.candles.setMarkers([]);
      [s.candles, s.volume, s.sma20, s.sma50, s.sma200, s.bbUpper, s.bbLower, s.rsi, s.macd, s.macdSignal, s.macdHist]
        .forEach(function (series) { series.setData([]); });
      [charts.price, charts.rsi, charts.macd].forEach(function (c) {
        c.chart.timeScale().applyOptions({ timeVisible: intraday, secondsVisible: false });
      });
      drawnIntraday = intraday;
    }
    s.candles.applyOptions({
      priceFormat: { type: "price", precision: chartDigits, minMove: Math.pow(10, -chartDigits) },
    });
    s.candles.setData(rows.map(function (c) {
      return { time: c.time, open: c.open, high: c.high, low: c.low, close: c.close };
    }));
    s.volume.setData(rows.map(function (c) {
      var up = c.close >= c.open;
      return isNum(c.volume)
        ? { time: c.time, value: c.volume, color: up ? "rgba(38, 166, 154, 0.45)" : "rgba(239, 83, 80, 0.45)" }
        : { time: c.time };
    }));
    var I = chartData.ind;
    s.sma20.setData(aligned(times, I.sma20));
    s.sma50.setData(aligned(times, I.sma50));
    s.sma200.setData(aligned(times, I.sma200));
    s.bbUpper.setData(aligned(times, I.bb_upper));
    s.bbLower.setData(aligned(times, I.bb_lower));
    s.rsi.setData(aligned(times, I.rsi14));
    s.macd.setData(aligned(times, I.macd));
    s.macdSignal.setData(aligned(times, I.macd_signal));
    s.macdHist.setData(aligned(times, I.macd_hist, function (v) {
      return v >= 0 ? "rgba(38, 166, 154, 0.7)" : "rgba(239, 83, 80, 0.7)";
    }));

    if (resetView && rows.length) {
      var span = intraday ? INTRADAY_SPAN : (VIEW_SPAN[state.interval] || 180);
      showRange({ from: Math.max(rows.length - span, 0) - 0.5, to: rows.length + 2.5 });
    }
    setOverlay(rows.length ? "" : "Sem dados de preço para este ativo.");
    renderLegends(null);
    applyMarkers();
  }

  function currentSetup() {
    if (!swingData || !state.swingSetup) return null;
    for (var i = 0; i < swingData.setups.length; i++) {
      if (swingData.setups[i] && swingData.setups[i].key === state.swingSetup) return swingData.setups[i];
    }
    return null;
  }

  // Marcações de entrada/saída do setup selecionado. Só existem no diário: os
  // setups são calculados em candles diários, então em qualquer outro intervalo
  // (e sem setup selecionado) a lista fica vazia.
  function applyMarkers() {
    var list = [];
    var setup = currentSetup();
    if (setup && selInterval === "1d" && state.interval === "1d" && chartData && !chartData.intraday) {
      (Array.isArray(setup.markers) ? setup.markers : []).forEach(function (m) {
        if (!m || typeof m.time !== "string" || (m.type !== "entry" && m.type !== "exit")) return;
        var t = m.time.slice(0, 10);
        if (!chartData.candle[t]) return;
        var entry = m.type === "entry";
        list.push({
          time: t, position: entry ? "belowBar" : "aboveBar", color: entry ? UP : DOWN,
          shape: entry ? "arrowUp" : "arrowDown",
        });
      });
      list.sort(function (a, b) { return a.time < b.time ? -1 : a.time > b.time ? 1 : 0; });
    }
    state.markerCount = list.length;
    if (charts) charts.series.candles.setMarkers(list);

    var note = $("swing-markers-note");
    if (!setup) { note.hidden = true; note.textContent = ""; return; }
    note.textContent = selInterval !== "1d"
      ? "As marcações de entrada e saída de “" + setup.label + "” só aparecem no intervalo diário (D)."
      : list.length
        ? "No gráfico: " + list.length + " marcações de “" + setup.label + "” — ▲ entrada (abaixo da barra), ▼ saída (acima da barra)."
        : "“" + setup.label + "” ainda não teve operações neste histórico: nada a marcar no gráfico.";
    note.hidden = false;
  }

  function legendItem(parent, label, value, color) {
    var span = el("span", "", label);
    var b = el("b", "", value);
    if (color) b.style.color = color;
    span.appendChild(b);
    parent.appendChild(span);
  }

  // t = data sob o crosshair; null mostra o último candle.
  function renderLegends(t) {
    var priceLg = $("price-legend"), rsiLg = $("rsi-legend"), macdLg = $("macd-legend");
    clear(priceLg); clear(rsiLg); clear(macdLg);
    rsiLg.appendChild(el("b", "", "RSI 14"));
    macdLg.appendChild(el("b", "", "MACD 12, 26, 9"));
    if (!chartData || !chartData.times.length) return;
    var key = t && chartData.candle[t] ? t : chartData.times[chartData.times.length - 1];
    var c = chartData.candle[key];
    var I = chartData.ind;
    var p = palette();
    var tone = c.close >= c.open ? cssVar("--up-text") : cssVar("--down-text");

    priceLg.appendChild(el("b", "", chartData.intraday ? fmtBarTime(Number(key)) : fmtDate(key)));
    legendItem(priceLg, "A", fmtNum(c.open, chartDigits), tone);
    legendItem(priceLg, "Máx", fmtNum(c.high, chartDigits), tone);
    legendItem(priceLg, "Mín", fmtNum(c.low, chartDigits), tone);
    legendItem(priceLg, "F", fmtNum(c.close, chartDigits), tone);
    if (isNum(c.volume)) legendItem(priceLg, "Vol", fmtCompact(c.volume));
    if (state.overlays.sma20 && isNum(I.sma20[key])) legendItem(priceLg, "SMA 20", fmtNum(I.sma20[key], chartDigits), p.sma20);
    if (state.overlays.sma50 && isNum(I.sma50[key])) legendItem(priceLg, "SMA 50", fmtNum(I.sma50[key], chartDigits), p.sma50);
    if (state.overlays.sma200 && isNum(I.sma200[key])) legendItem(priceLg, "SMA 200", fmtNum(I.sma200[key], chartDigits), p.sma200);
    if (state.overlays.bb && isNum(I.bb_upper[key]) && isNum(I.bb_lower[key])) {
      legendItem(priceLg, "BB", fmtNum(I.bb_lower[key], chartDigits) + " – " + fmtNum(I.bb_upper[key], chartDigits), p.bb);
    }

    if (isNum(I.rsi14[key])) legendItem(rsiLg, "", fmtNum(I.rsi14[key], 1), p.rsi);
    if (isNum(I.macd[key])) legendItem(macdLg, "MACD", fmtSigned(I.macd[key], 2), p.macd);
    if (isNum(I.macd_signal[key])) legendItem(macdLg, "Sinal", fmtSigned(I.macd_signal[key], 2), p.signal);
    if (isNum(I.macd_hist[key])) {
      legendItem(macdLg, "Hist.", fmtSigned(I.macd_hist[key], 2), I.macd_hist[key] >= 0 ? cssVar("--up-text") : cssVar("--down-text"));
    }
  }

  function drawEquity(points) {
    if (!charts) return;
    var rows = (Array.isArray(points) ? points : []).filter(function (pt) { return pt && typeof pt.date === "string"; });
    var pick = function (key) {
      return rows.filter(function (pt) { return isNum(pt[key]); })
        .map(function (pt) { return { time: pt.date, value: pt[key] }; });
    };
    charts.series.eqStrategy.setData(pick("strategy"));
    charts.series.eqBuyHold.setData(pick("buy_hold"));
    if (rows.length) charts.equity.chart.timeScale().fitContent();
  }

  // ------------------------------------------------------------- watchlist
  function watchAsset(id) {
    for (var i = 0; i < state.assets.length; i++) if (state.assets[i].id === id) return state.assets[i];
    return null;
  }

  // Watchlist ou o ativo aberto sob demanda (que só existe na seleção atual).
  function findAsset(id) {
    var a = watchAsset(id);
    if (a) return a;
    return state.opened && state.opened.id === id ? state.opened : null;
  }

  function readOpened() {
    try {
      var v = JSON.parse(storageGet(OPENED_KEY) || "null");
      return v && typeof v.symbol === "string" && typeof v.market === "string" ? { symbol: v.symbol, market: v.market } : null;
    } catch (e) { return null; }
  }

  function persistSelection() {
    if (state.selectedId === null) return;
    storageSet(SELECTED_KEY, String(state.selectedId));
    var o = state.opened && state.opened.id === state.selectedId ? state.opened : null;
    storageSet(OPENED_KEY, o ? JSON.stringify({ symbol: o.symbol, market: o.market }) : "");
  }

  function pickDefault() {
    if (!state.assets.length) return;
    var stored = Number(storageGet(SELECTED_KEY));
    state.selectedId = watchAsset(stored) ? stored : state.assets[0].id;
  }

  function assetVerdict(a) {
    return a && a.status === "ok" && a.verdict ? a.verdict : "insuficiente";
  }

  function alertIcon(message) {
    var icon = el("span", "alert-icon", "⚠");
    icon.title = "Falha na fonte de dados: " + message;
    icon.setAttribute("role", "img");
    icon.setAttribute("aria-label", "Falha na fonte de dados: " + message);
    return icon;
  }

  var watchlistSig = null;  // assinatura do que está desenhado na watchlist

  function watchlistSignature() {
    return JSON.stringify([state.selectedId, state.assets.map(function (a) {
      return [a.id, a.symbol, a.market, a.name, a.currency, a.price, a.change_pct, a.status, a.verdict, a.evidence, a.last_error];
    })]);
  }

  // Reconstrói só quando algo visível mudou: o auto-refresh de 60 s não pode
  // roubar o foco do teclado nem engolir um clique em andamento.
  function renderWatchlist() {
    var root = $("watchlist");
    var sig = watchlistSignature();
    if (sig === watchlistSig) return;
    watchlistSig = sig;

    var active = document.activeElement;
    var focusItem = active && root.contains(active) && active.closest ? active.closest("[data-asset-id]") : null;
    var focusId = focusItem ? focusItem.dataset.assetId : null;
    var focusSel = active && active.classList && active.classList.contains("remove-asset") ? ".remove-asset" : ".wl-select";

    clear(root);
    root.setAttribute("aria-busy", "false");
    if (!state.assets.length) {
      root.appendChild(el("p", "wl-empty", "Watchlist vazia. Adicione um símbolo acima."));
      return;
    }
    var markets = MARKET_ORDER.slice();
    state.assets.forEach(function (a) { if (markets.indexOf(a.market) < 0) markets.push(a.market); });

    markets.forEach(function (market) {
      var items = state.assets.filter(function (a) { return a.market === market; });
      if (!items.length) return;
      var group = el("section", "wl-group");
      group.dataset.market = market;
      group.appendChild(el("h3", "wl-group-title", marketLabel(market)));
      var list = el("ul", "wl-items");
      items.forEach(function (a) {
        var li = el("li", "wl-item" + (a.id === state.selectedId ? " selected" : ""));
        li.dataset.assetId = String(a.id);
        li.dataset.symbol = a.symbol;
        li.dataset.market = a.market;

        var pick = el("button", "wl-select");
        pick.type = "button";
        if (a.id === state.selectedId) pick.setAttribute("aria-current", "true");
        var sym = el("span", "wl-symbol", a.symbol);
        if (a.last_error) sym.appendChild(alertIcon(a.last_error));
        pick.appendChild(sym);
        pick.appendChild(el("span", "wl-price", fmtMoney(a.price, a.currency)));
        var company = displayName(a.name, a.symbol);
        if (company) {
          var nameEl = el("span", "wl-name", company);
          nameEl.title = company;
          pick.appendChild(nameEl);
        }
        var verdict = assetVerdict(a);
        var evidence = a.status === "ok" && EVIDENCE_LABEL[a.evidence] ? a.evidence : "";
        li.dataset.evidence = evidence;
        var row2 = el("span", "wl-row2");
        var badge = el("span", "badge wl-badge", VERDICT_SHORT[verdict] || verdict);
        badge.dataset.verdict = verdict;
        row2.appendChild(badge);
        if (evidence) {
          // Evidência visível ao lado do veredito: ponto colorido + texto curto;
          // o rótulo completo vai para leitores de tela e para o title.
          var ev = el("span", "wl-ev");
          ev.dataset.evidence = evidence;
          ev.title = EVIDENCE_LABEL[evidence];
          var shortText = el("span", "", EVIDENCE_SHORT[evidence]);
          shortText.setAttribute("aria-hidden", "true");
          ev.appendChild(shortText);
          ev.appendChild(el("span", "sr-only", EVIDENCE_LABEL[evidence]));
          row2.appendChild(ev);
        }
        row2.appendChild(el("span", "wl-change " + signClass(a.change_pct), fmtPct(a.change_pct)));
        pick.appendChild(row2);
        li.appendChild(pick);

        var rm = el("button", "remove-asset", "×");
        rm.type = "button";
        rm.title = "Remover " + a.symbol;
        rm.setAttribute("aria-label", "Remover " + a.symbol + " da watchlist");
        li.appendChild(rm);
        list.appendChild(li);
      });
      group.appendChild(list);
      root.appendChild(group);
    });

    if (focusId !== null) {
      var again = root.querySelector('[data-asset-id="' + focusId + '"] ' + focusSel);
      if (again) again.focus({ preventScroll: true });
    }
  }

  function renderDataStatus() {
    var latest = "";
    state.assets.forEach(function (a) { if (a.last_refresh && a.last_refresh > latest) latest = a.last_refresh; });
    var text = latest ? fmtDateTime(latest) : "";
    $("data-status").textContent = text ? "Dados de " + text : "";
  }

  var assetsToken = 0;

  function loadAssets() {
    var token = ++assetsToken;
    return api("/api/assets").then(function (list) {
      if (token !== assetsToken) return state.assets;  // resposta antiga: uma mais nova já foi pedida
      state.assets = Array.isArray(list) ? list : [];
      state.assetsLoaded = true;
      hideNetError();
      if (state.opened && watchAsset(state.opened.id)) state.opened = null;  // foi promovido à watchlist
      if (state.selectedId !== null && !findAsset(state.selectedId)) state.selectedId = null;
      if (state.selectedId === null && !state.opening) pickDefault();
      renderWatchlist();
      renderDataStatus();
      return state.assets;
    });
  }

  // ------------------------------------------------------- ativo em foco
  var detailToken = 0;
  var openToken = 0;      // aberturas sob demanda (POST /api/assets/open)
  var detailStamp = "";   // last_refresh do ativo quando o detalhe foi carregado

  function renderChartHeader(a) {
    $("chart-title").textContent = a ? a.symbol : DASH;
    $("chart-market").textContent = a ? marketLabel(a.market) : "";
    $("chart-market").hidden = !a;
    $("chart-price").textContent = a ? fmtMoney(a.price, a.currency) : "";
    var change = $("chart-change");
    change.textContent = a && isNum(a.change_pct) ? fmtPct(a.change_pct) : "";
    change.className = "quote-change " + (a ? signClass(a.change_pct) : "");
    var alert = $("chart-alert");
    alert.hidden = !(a && a.last_error);
    alert.title = a && a.last_error ? "Falha na fonte de dados: " + a.last_error : "";

    var name = $("chart-name");
    name.textContent = a ? displayName(a.name, a.symbol) : "";
    name.title = name.textContent;
    var indices = $("chart-indices");
    clear(indices);
    (a && Array.isArray(a.indices) ? a.indices : []).forEach(function (code) {
      var tag = el("span", "tag", INDEX_LABEL[code] || code);
      tag.title = "Compõe o índice " + (INDEX_LABEL[code] || code);
      indices.appendChild(tag);
    });
    var toggle = $("watch-toggle");
    toggle.hidden = !a;
    if (a) {
      var watching = a.watch !== false;
      toggle.dataset.watch = String(watching);
      toggle.setAttribute("aria-pressed", String(watching));
      toggle.textContent = watching ? "Na watchlist" : "Adicionar à watchlist";
      toggle.title = watching ? "Clique para tirar " + a.symbol + " da watchlist" : "Acompanhar " + a.symbol + " na watchlist";
    }
  }

  function setRecLoading(on) {
    var card = $("rec-card");
    card.classList.toggle("is-loading", on);
    card.setAttribute("aria-busy", String(on));
  }

  function factorRaw(f) {
    if (!isNum(f.raw)) return "";
    if (f.key === "momentum" || f.key === "dist_sma200") return "valor bruto " + fmtPct(f.raw, 1);
    if (f.key === "trend") return "estatística t " + fmtSigned(f.raw, 2);
    if (f.key === "reversal") return "z-score " + fmtSigned(f.raw, 2);
    return "valor bruto " + fmtSigned(f.raw, 2);
  }

  function divergingBar(value) {
    var bar = el("div", "dbar");
    if (isNum(value) && value !== 0) {
      var v = Math.max(-1, Math.min(1, value));
      var fill = el("i", v > 0 ? "pos" : "neg");
      var width = Math.abs(v) * 50;
      fill.style.width = width + "%";
      fill.style.left = (v > 0 ? 50 : 50 - width) + "%";
      bar.appendChild(fill);
    }
    return bar;
  }

  function renderFactors(factors) {
    var root = $("rec-factors");
    clear(root);
    (Array.isArray(factors) ? factors : []).forEach(function (f) {
      if (!f) return;
      var row = el("div", "factor");
      row.dataset.factor = f.key || "";
      var label = el("span", "factor-label", f.label || f.key || "");
      if (isNum(f.weight)) label.appendChild(el("small", "", "peso " + fmtShare(f.weight, 0)));
      row.appendChild(label);
      row.appendChild(el("span", "factor-value " + signClass(f.normalized), fmtSigned(f.normalized, 2)));
      row.appendChild(divergingBar(f.normalized));
      var raw = factorRaw(f);
      if (raw) row.appendChild(el("span", "factor-raw", raw));
      root.appendChild(row);
    });
  }

  function btRow(body, label, a, b, fmt) {
    var tr = el("tr");
    tr.appendChild(el("td", "", label));
    tr.appendChild(el("td", "", fmt(a)));
    tr.appendChild(el("td", "", fmt(b)));
    body.appendChild(tr);
  }

  function renderBacktest(bt) {
    var excess = $("rec-excess"), body = $("rec-bt-body"), meta = $("rec-bt-meta");
    clear(excess); clear(body); meta.textContent = "";
    if (!bt) return;
    var x = bt.excess || {};
    excess.appendChild(document.createTextNode("Excesso de crescimento (log) sobre buy & hold: "));
    excess.appendChild(el("b", signClass(x.mean), fmtPct(x.mean, 1) + " a.a."));
    excess.appendChild(document.createTextNode(" · IC 95%: "));
    excess.appendChild(el("b", "", fmtPct(x.ci_low, 1) + " a " + fmtPct(x.ci_high, 1)));
    if (EVIDENCE_EXPLAIN[bt.evidence]) {
      excess.appendChild(document.createElement("br"));
      excess.appendChild(el("span", "muted", EVIDENCE_EXPLAIN[bt.evidence]));
    }
    var s = bt.strategy || {}, h = bt.buy_hold || {};
    btRow(body, "Retorno a.a.", s.ann_return, h.ann_return, function (v) { return fmtPct(v, 1); });
    btRow(body, "Volatilidade a.a.", s.ann_vol, h.ann_vol, function (v) { return fmtShare(v, 1); });
    btRow(body, "Sharpe", s.sharpe, h.sharpe, function (v) { return fmtNum(v, 2); });
    btRow(body, "Drawdown máx.", s.max_drawdown, h.max_drawdown, function (v) { return fmtPct(v, 1); });
    var parts = [];
    if (bt.start && bt.end) parts.push(fmtDate(bt.start) + " a " + fmtDate(bt.end));
    if (isNum(bt.trades)) parts.push(bt.trades + (bt.trades === 1 ? " operação" : " operações"));
    if (isNum(bt.time_in_market)) parts.push(fmtShare(bt.time_in_market, 0) + " do tempo posicionado");
    if (isNum(bt.hit_rate)) parts.push(fmtShare(bt.hit_rate, 0) + " de acerto");
    meta.textContent = parts.join(" · ");
  }

  // analysis pode ser null (falha ao carregar) ou ter só os campos de identificação.
  function renderRec(analysis, summary) {
    var verdictEl = $("rec-verdict"), evidenceEl = $("rec-evidence");
    var message = $("rec-message"), sourceErr = $("rec-source-error");
    var marker = $("rec-score-marker");
    var ok = !!analysis && analysis.status === "ok";
    renderSwing(analysis);

    var lastError = summary && summary.last_error;
    sourceErr.hidden = !lastError;
    sourceErr.textContent = lastError
      ? "Falha na última atualização da fonte: " + lastError + ". "
        + (analysis && analysis.candles > 0 ? "O que aparece aqui são os dados já armazenados." : "Não há dados armazenados para este ativo.")
      : "";

    if (!analysis) {
      verdictEl.textContent = DASH; verdictEl.dataset.verdict = "";
      evidenceEl.textContent = summary ? "análise indisponível no momento" : DASH; evidenceEl.dataset.evidence = "";
      message.hidden = true;
      $("rec-score").textContent = DASH; $("rec-score").className = "score-value"; marker.hidden = true;
      $("rec-body").hidden = true;
      drawEquity([]);
      return;
    }

    if (!ok) {
      var n = isNum(analysis.candles) ? analysis.candles : 0;
      verdictEl.textContent = VERDICT_LABEL.insuficiente; verdictEl.dataset.verdict = "insuficiente";
      evidenceEl.textContent = "sem avaliação estatística"; evidenceEl.dataset.evidence = "";
      message.textContent = n < MIN_CANDLES
        ? "Este ativo tem " + fmtNum(n, 0) + (n === 1 ? " candle diário" : " candles diários")
          + " — menos de 300 candles, o mínimo para calcular score, veredito e backtest."
        : "O histórico deste ativo (" + fmtNum(n, 0) + " candles) ainda não permite calcular score e backtest.";
      message.hidden = false;
      $("rec-score").textContent = DASH; $("rec-score").className = "score-value"; marker.hidden = true;
      $("rec-body").hidden = true;
      drawEquity([]);
      return;
    }

    var verdict = VERDICT_LABEL[analysis.verdict] ? analysis.verdict : "";
    verdictEl.textContent = verdict ? VERDICT_LABEL[verdict] : (analysis.verdict || DASH);
    verdictEl.dataset.verdict = verdict;

    var evidence = analysis.backtest ? analysis.backtest.evidence : null;
    var known = !!EVIDENCE_LABEL[evidence];
    evidenceEl.textContent = known ? EVIDENCE_LABEL[evidence] : (evidence || "evidência não informada");
    evidenceEl.dataset.evidence = known ? evidence : "";

    message.hidden = true;
    var scoreEl = $("rec-score");
    scoreEl.textContent = fmtSigned(analysis.score, 1);
    scoreEl.className = "score-value " + signClass(analysis.score);
    if (isNum(analysis.score)) {
      marker.style.left = Math.max(0, Math.min(100, (analysis.score + 100) / 2)) + "%";
      marker.hidden = false;
    } else {
      marker.hidden = true;
    }

    $("rec-body").hidden = false;
    renderFactors(analysis.factors);
    $("rec-vol").textContent = fmtShare(analysis.volatility, 1);
    var dd = $("rec-dd");
    dd.textContent = fmtPct(analysis.drawdown, 1);
    dd.className = signClass(analysis.drawdown);
    renderBacktest(analysis.backtest);
    drawEquity(analysis.equity);
  }

  // ------------------------------------------------- curto prazo (swing)
  function setRecTab(tab) {
    state.recTab = tab === "swing" ? "swing" : "position";
    var swing = state.recTab === "swing";
    $("rec-tab-position").setAttribute("aria-selected", String(!swing));
    $("rec-tab-swing").setAttribute("aria-selected", String(swing));
    $("rec-position").hidden = swing;
    $("swing-card").hidden = !swing;
  }

  function evidenceDot(evidence) {
    var dot = el("i", "ev-dot");
    dot.dataset.evidence = evidence || "";
    dot.setAttribute("aria-hidden", "true");
    return dot;
  }

  function swingStateText(s, analysis) {
    if (s.state === "sinal") {
      var where = "Sinal no " + candleText(analysis && analysis.as_of, true);
      return analysis && analysis.session_open === true
        ? where + " — pregão em andamento — o sinal só vale no fechamento"
        : where + " — compra na próxima abertura";
    }
    if (s.state === "posicao") {
      var p = s.position || {};
      var days = isNum(p.days) ? fmtNum(p.days, 0) + (p.days === 1 ? " pregão" : " pregões") : "alguns pregões";
      if (p.exit_pending) return "Em posição há " + days + " — saída na próxima abertura";
      return "Em posição há " + days + (isNum(p.ret) ? " (" + fmtPct(p.ret, 1) + ")" : "");
    }
    return "Sem sinal";
  }

  function swingStat(parent, label, value, cls) {
    var box = el("span");
    box.appendChild(el("small", "", label));
    box.appendChild(el("b", cls || "", value));
    parent.appendChild(box);
  }

  // Um bloco por setup. É um <button>: clicar seleciona o setup e desenha as
  // marcações no gráfico diário. Estado e evidência têm o mesmo peso visual.
  function swingBlock(s, analysis) {
    var currency = analysis.currency;
    var stats = s.stats || {};
    var block = el("button", "swing-setup");
    block.type = "button";
    block.dataset.setup = s.key || "";
    block.dataset.state = s.state === "sinal" || s.state === "posicao" ? s.state : "nenhum";
    var picked = state.swingSetup === s.key;
    block.setAttribute("aria-pressed", String(picked));

    var top = el("span", "swing-top");
    var label = el("span", "swing-label", s.label || s.key || "");
    label.appendChild(el("span", "swing-pick", picked ? "marcado no gráfico" : "ver no gráfico"));
    top.appendChild(label);
    if (s.description) top.appendChild(el("span", "swing-desc", s.description));
    block.appendChild(top);

    block.appendChild(el("span", "swing-state", swingStateText(s, analysis)));
    if (block.dataset.state === "posicao" && s.position) {
      var p = s.position, bits = [];
      if (p.entry_date) bits.push("entrada em " + fmtDate(String(p.entry_date)) + (isNum(p.entry_price) ? " a " + fmtMoney(p.entry_price, currency) : ""));
      if (isNum(p.ret)) bits.push("retorno até agora " + fmtPct(p.ret, 1));
      if (bits.length) block.appendChild(el("span", "swing-pos", bits.join(" · ")));
    }

    var known = !!SWING_EVIDENCE_LABEL[stats.evidence];
    var ev = el("span", "swing-ev");
    ev.dataset.evidence = known ? stats.evidence : "";
    ev.appendChild(evidenceDot(known ? stats.evidence : ""));
    ev.appendChild(el("span", "", known ? SWING_EVIDENCE_LABEL[stats.evidence] : "evidência não informada"));
    block.appendChild(ev);

    var ci = el("span", "swing-ci");
    ci.appendChild(document.createTextNode("Excesso médio por operação sobre segurar: "));
    ci.appendChild(el("b", signClass(stats.mean_excess), fmtPct(stats.mean_excess, 2)));
    ci.appendChild(document.createTextNode(" · IC 95%: "));
    ci.appendChild(el("b", "", isNum(stats.ci_low) && isNum(stats.ci_high)
      ? fmtPct(stats.ci_low, 2) + " a " + fmtPct(stats.ci_high, 2) : DASH));
    if (stats.evidence === "amostra_insuficiente") ci.appendChild(document.createTextNode(" (menos de 20 operações)"));
    block.appendChild(ci);

    var grid = el("span", "swing-stats");
    swingStat(grid, "Operações", isNum(stats.trades) ? fmtNum(stats.trades, 0) : DASH);
    swingStat(grid, "Taxa de acerto", fmtShare(stats.win_rate, 0));
    swingStat(grid, "Retorno médio líquido", fmtPct(stats.mean_net, 2), signClass(stats.mean_net));
    swingStat(grid, "Duração média", isNum(stats.avg_days) ? fmtNum(stats.avg_days, 1) + " pregões" : DASH);
    block.appendChild(grid);
    return block;
  }

  function contextItem(parent, label, value, hint, cls) {
    var box = el("div");
    box.appendChild(el("dt", "", label));
    var dd = el("dd", cls || "", value);
    if (hint && value !== DASH) dd.appendChild(el("small", "", " " + hint));
    box.appendChild(dd);
    parent.appendChild(box);
  }

  function renderSwing(analysis) {
    var root = $("swing-setups"), msg = $("swing-message"), ctxBlock = $("swing-context-block"), ctx = $("swing-context");
    clear(root); clear(ctx);
    var swing = analysis && analysis.status === "ok" && analysis.swing && Array.isArray(analysis.swing.setups) ? analysis.swing : null;
    swingData = swing;
    if (!swing) {
      state.swingSetup = null;
      msg.textContent = !analysis
        ? "Análise de curto prazo indisponível no momento."
        : "Curto prazo indisponível: o histórico diário deste ativo é insuficiente (mínimo de 300 candles) para avaliar os setups.";
      msg.hidden = false;
      ctxBlock.hidden = true;
      applyMarkers();
      return;
    }
    msg.hidden = true;
    if (state.swingSetup && !currentSetup()) state.swingSetup = null;
    swing.setups.forEach(function (s) { if (s) root.appendChild(swingBlock(s, analysis)); });

    var c = swing.context || {};
    contextItem(ctx, "ATR (14)", fmtShare(c.atr_pct, 1), "do preço");
    contextItem(ctx, "Faixa esperada, 5 pregões", isNum(c.range_5d) ? "±" + fmtShare(c.range_5d, 1) : DASH);
    contextItem(ctx, "Volume relativo", isNum(c.rel_volume) ? fmtNum(c.rel_volume, 2) + "×" : DASH, "a média de 20");
    contextItem(ctx, "Da máxima de 20 pregões", fmtPct(c.dist_high20, 1), "", signClass(c.dist_high20));
    contextItem(ctx, "Da mínima de 20 pregões", fmtPct(c.dist_low20, 1), "", signClass(c.dist_low20));
    ctxBlock.hidden = false;
    applyMarkers();
  }

  function pickSetup(key) {
    state.swingSetup = state.swingSetup === key ? null : key;  // clicar de novo tira as marcações
    $("swing-setups").querySelectorAll(".swing-setup").forEach(function (node) {
      var on = node.dataset.setup === state.swingSetup;
      node.setAttribute("aria-pressed", String(on));
      var pick = node.querySelector(".swing-pick");
      if (pick) pick.textContent = on ? "marcado no gráfico" : "ver no gráfico";
    });
    applyMarkers();
  }

  // ---------------------------------------------------------------- notícias
  var newsToken = 0;
  var newsFor = null;   // id do ativo cujas notícias estão na tela (ou a caminho)
  var NEWS_EMPTY = "Nenhuma notícia encontrada para este ativo.";

  function renderNews(data) {
    var list = $("news-list"), empty = $("news-empty");
    clear(list);
    var items = (data && Array.isArray(data.items) ? data.items : []).filter(function (n) {
      return n && typeof n.title === "string" && n.title;
    });
    $("news-stale").hidden = !(data && data.stale);
    empty.textContent = NEWS_EMPTY;
    empty.hidden = items.length > 0;
    items.forEach(function (n, i) {
      var li = el("li", "news-item");
      var a = el("a", "", n.title);
      a.dataset.news = String(i);
      // Só http(s): nada de javascript:, data: ou caminho relativo vindo da fonte.
      if (typeof n.url === "string" && /^https?:\/\//i.test(n.url)) a.href = n.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      li.appendChild(a);
      var ago = fmtAgo(n.published_at);
      var meta = el("span", "news-meta", [n.source, ago].filter(function (x) { return !!x; }).join(" · "));
      var when = fmtDateTime(n.published_at);
      if (when) meta.title = "Publicada em " + when;
      li.appendChild(meta);
      list.appendChild(li);
    });
  }

  function loadNews(id) {
    var token = ++newsToken;
    newsFor = id;
    var panel = $("news-panel"), loading = $("news-loading"), empty = $("news-empty");
    clear($("news-list"));
    $("news-stale").hidden = true;
    empty.hidden = true;
    if (id === null) { panel.hidden = true; loading.hidden = true; return Promise.resolve(); }
    var a = findAsset(id);
    $("news-symbol").textContent = a ? "· " + a.symbol : "";
    panel.hidden = false;
    panel.setAttribute("aria-busy", "true");
    loading.hidden = false;
    return api("/api/assets/" + id + "/news").then(function (data) {
      if (token !== newsToken) return;
      loading.hidden = true;
      panel.setAttribute("aria-busy", "false");
      renderNews(data);
    }, function (err) {
      if (token !== newsToken) return;
      loading.hidden = true;
      panel.setAttribute("aria-busy", "false");
      empty.textContent = "Não foi possível carregar as notícias agora.";
      empty.hidden = false;
      if (window.console && !(err instanceof ApiError)) console.error(err);
    });
  }

  // ---------------------------------------------------------------- intraday
  var intradayTimer = 0;
  var candlesAt = 0;  // quando os candles em exibição foram pedidos
  var candlesBusy = false;  // recarga silenciosa em voo: não empilha outra por cima

  function renderIntradayNote(payload, asset, errorText) {
    var note = $("intraday-note");
    if (!isIntraday(selInterval)) { note.hidden = true; note.textContent = ""; return; }
    note.hidden = false;
    if (errorText) { note.textContent = errorText; note.dataset.kind = "error"; return; }
    if (!payload) { note.textContent = "Carregando intraday…"; note.dataset.kind = "plain"; return; }
    var parts = [];
    var crypto = !!asset && asset.market === "CRYPTO";
    // A fonte não informa o atraso: a idade do último candle é o que o mostra.
    if (isNum(payload.last_bar_time)) {
      var age = Date.now() / 1000 - payload.last_bar_time;
      var bar = new Date(payload.last_bar_time * 1000);
      var clock = new Intl.DateTimeFormat(LOCALE, { hour: "2-digit", minute: "2-digit" }).format(bar);
      if (age < INTRADAY_FRESH_S) {
        parts.push("último candle " + clock + " (" + fmtAge(age) + ")");
      } else {
        parts.push("último candle " + new Intl.DateTimeFormat(LOCALE, { day: "2-digit", month: "2-digit" }).format(bar) + " " + clock);
        parts.push(crypto ? "sem candles recentes" : "mercado fechado");
      }
    }
    if (!crypto) {
      var delay = isNum(payload.delay_minutes) && payload.delay_minutes > 0
        ? " (atraso informado: " + fmtNum(payload.delay_minutes, 0) + " min)" : "";
      parts.push("Cotação pode vir com atraso" + delay);
      if (asset && asset.market === "B3") parts.push("atraso típico de 15 min na B3");
      parts.push("Preços intraday sem ajuste por proventos");
    }
    parts.push("atualiza a cada 60 s");
    note.textContent = parts.join(" · ");
    note.dataset.kind = crypto ? "plain" : "warn";
  }

  function intradayUnavailable(err) {
    return err instanceof ApiError && err.status === 422;
  }

  // Recarga silenciosa só dos candles (o cartão de recomendação é diário).
  function reloadCandles() {
    var id = state.selectedId, interval = selInterval, token = detailToken;
    if (id === null || !isIntraday(interval) || candlesBusy) return Promise.resolve();
    candlesBusy = true;
    var same = function () { return token === detailToken && state.selectedId === id && selInterval === interval; };
    candlesAt = Date.now();
    return api("/api/assets/" + id + "/candles?interval=" + encodeURIComponent(interval)).then(function (payload) {
      candlesBusy = false;
      if (!same()) return;
      state.interval = interval;
      drawCandles(payload, state.candleCount === 0);
      loadedKey = id + "|" + interval;
      renderIntradayNote(payload, findAsset(id));
    }, function (err) {
      candlesBusy = false;
      if (!same()) return;
      if (intradayUnavailable(err)) {
        renderIntradayNote(null, null, state.candleCount > 0
          ? err.message + " — o gráfico mostra os últimos dados carregados" : err.message);
      }
    });
  }

  function intradayTick() {
    if (document.hidden || state.tab !== "chart") return;
    reloadCandles();
  }

  function armIntraday() {
    window.clearInterval(intradayTimer);
    intradayTimer = isIntraday(selInterval) ? window.setInterval(intradayTick, INTRADAY_RELOAD_MS) : 0;
  }

  // Ao voltar para a aba (do navegador ou do app), não espera o próximo ciclo.
  function catchUpIntraday() {
    if (document.hidden || state.tab !== "chart" || !isIntraday(selInterval)) return;
    if (Date.now() - candlesAt >= INTRADAY_RELOAD_MS) reloadCandles();
  }

  function clearDetail() {
    detailToken++;
    loadedKey = "";
    detailStamp = "";
    renderChartHeader(null);
    $("chart-asof").textContent = "";
    state.swingSetup = null;
    state.interval = selInterval;
    drawCandles({ candles: [], indicators: {} }, false);
    setOverlay(state.opening ? "Buscando dados de " + state.opening.symbol + "…"
      : state.assetsLoaded ? "Busque um ativo ou adicione um à watchlist para ver o gráfico." : "");
    renderRec(null, null);
    renderIntradayNote(null, null, isIntraday(selInterval) ? "Nenhum ativo selecionado." : "");
    loadNews(null);
    setRecLoading(false);
  }

  function loadDetail() {
    var id = state.selectedId;
    if (id === null) { clearDetail(); return Promise.resolve(); }
    var token = ++detailToken;
    var interval = selInterval;
    var key = id + "|" + interval;
    var fresh = key !== loadedKey;
    var newAsset = String(loadedKey).split("|")[0] !== String(id);
    var summary = findAsset(id);

    renderChartHeader(summary);
    if (newAsset) {
      setRecLoading(true);
      setOverlay("Carregando…");
      state.swingSetup = null;   // marcações são do ativo anterior
      swingData = null;
      applyMarkers();
    }
    // Pelo id e não por "ativo novo": numa troca rápida A→B→A o gráfico de A ainda
    // está desenhado, mas as notícias pedidas por último são as de B.
    if (newsFor !== id) loadNews(id);
    if (fresh && isIntraday(interval)) renderIntradayNote(null, summary);
    candlesAt = Date.now();

    var candlesReq = api("/api/assets/" + id + "/candles?interval=" + encodeURIComponent(interval));
    var analysisReq = api("/api/assets/" + id + "/analysis");

    return Promise.all([
      candlesReq.then(function (v) { return { ok: true, value: v }; }, function (e) { return { ok: false, error: e }; }),
      analysisReq.then(function (v) { return { ok: true, value: v }; }, function (e) { return { ok: false, error: e }; }),
    ]).then(function (results) {
      if (token !== detailToken) return;
      var c = results[0], a = results[1];
      var gone = [c, a].some(function (r) { return !r.ok && r.error && r.error.status === 404; });
      if (gone) {
        state.selectedId = null;
        if (state.opened && state.opened.id === id) state.opened = null;
        return loadAssets().then(loadDetail);
      }
      var now = findAsset(id) || summary;
      state.interval = interval;
      detailStamp = now && now.last_refresh ? now.last_refresh : "";

      if (c.ok) {
        drawCandles(c.value, fresh);
        loadedKey = key;
        renderIntradayNote(c.value, now);
      } else if (isIntraday(interval) && intradayUnavailable(c.error)) {
        // Intraday indisponível para este ativo: gráfico vazio com a mensagem, sem faixa de erro.
        drawCandles({ candles: [], indicators: {} }, false);
        loadedKey = key;
        setOverlay(c.error.message);
        renderIntradayNote(null, now, c.error.message);
      } else {
        report(c.error);
        if (fresh) {
          loadedKey = "";
          drawCandles({ candles: [], indicators: {} }, false);
          setOverlay("Não foi possível carregar os candles.");
          renderIntradayNote(null, now, isIntraday(interval) ? "Não foi possível carregar os candles intraday." : "");
        }
      }

      if (a.ok) {
        renderRec(a.value, now);
        // Análise insuficiente não traz `session_open`: vale o do resumo do ativo.
        var live = !!a.value && (a.value.status === "ok" ? a.value.session_open === true : !!now && now.session_open === true);
        $("chart-asof").textContent = a.value && a.value.as_of
          ? candleText(a.value.as_of) + (live ? " (pregão em andamento)" : "") : "";
      } else {
        report(a.error);
        if (newAsset) { renderRec(null, now); $("chart-asof").textContent = ""; }
      }
      setRecLoading(false);
    });
  }

  function selectAsset(id, force) {
    if (!findAsset(id)) return;
    var changed = state.selectedId !== id;
    // Uma escolha explícita vence qualquer abertura sob demanda ainda em curso.
    var wasOpening = !!state.opening;
    openToken++;
    state.opening = null;
    state.selectedId = id;
    if (state.opened && state.opened.id !== id) state.opened = null;  // o aberto só vive enquanto selecionado
    persistSelection();
    renderWatchlist();
    if (force || changed || wasOpening || loadedKey.split("|")[0] !== String(id)) loadDetail().catch(report);
  }

  function setInterval_(interval) {
    if (INTERVALS.indexOf(interval) < 0) return;
    var changed = selInterval !== interval;
    selInterval = interval;
    INTERVALS.forEach(function (i) { $("interval-" + i).setAttribute("aria-pressed", String(i === interval)); });
    armIntraday();
    if (!changed) return;
    applyMarkers();            // fora do diário as marcações somem na hora
    renderIntradayNote(null, null);
    loadDetail().catch(report);
  }

  // ---------------------------------------------- abrir ativo sob demanda
  // Abre (criando no servidor se preciso) um papel do catálogo sem pôr na
  // watchlist. quiet = restauração na carga da página: falha não vira aviso.
  function openAsset(symbol, market, quiet) {
    var token = ++openToken;
    state.opening = { symbol: symbol, market: market };
    if (!quiet) showAddError("");
    setOverlay("Buscando dados de " + symbol + "…");
    return api("/api/assets/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: symbol, market: market }),
    }).then(function (summary) {
      if (token !== openToken) return null;
      state.opening = null;
      if (!summary || !isNum(summary.id)) throw new ApiError(500, "resposta inesperada do servidor");
      if (summary.watch) {
        var ready = watchAsset(summary.id) ? Promise.resolve() : loadAssets();
        return ready.then(function () {
          if (token === openToken) selectAsset(summary.id, true);  // o usuário pode ter escolhido outro no meio
        });
      }
      state.opened = summary;
      selectAsset(summary.id, true);
      return null;
    }).catch(function (err) {
      if (token !== openToken) return null;
      state.opening = null;
      if (quiet) storageSet(OPENED_KEY, "");
      else if (err instanceof ApiError) showAddError("Não foi possível abrir " + symbol + ": " + err.message);
      else { showAddError("Não foi possível abrir " + symbol + " agora."); report(err); }
      // Nada mudou no estado: volta a mostrar o que estava selecionado.
      if (state.selectedId === null) { pickDefault(); renderWatchlist(); }
      return loadDetail().catch(report);
    });
  }

  // -------------------------------------------------------------- screener
  // Ordenação, filtros e paginação são do servidor; aqui só se desenha a página.
  var screenerToken = 0;
  var screenerTimer = 0;
  var screenerReady = null;   // "ready" do último progresso visto (índice sendo montado)
  var SCREENER_COLS = 16;
  var SCREENER_POLL_MS = 5000;
  var SCREENER_METHOD = "Evidência agregada usa a composição atual do índice (viés de sobrevivência) e trata classes "
    + "do mesmo emissor como papéis separados. Com três setups em centenas de papéis, alguns saem 'favoráveis' por acaso.";

  function screenerScope() { return $("screener-scope").value || "watchlist"; }

  function settle(promise) {
    return promise.then(function (v) { return { ok: true, value: v }; }, function (e) { return { ok: false, error: e }; });
  }

  function numCell(tr, value, text, colored) {
    tr.appendChild(el("td", "num" + (colored ? " " + signClass(value) : ""), text));
  }

  function setupChips(td, row) {
    var setups = row.setups;
    var signalText = "sinal no " + candleText(row.as_of, true)
      + (row.session_open === true ? " (pregão em andamento — o sinal só vale no fechamento)" : "");
    var any = false;
    Object.keys(SETUP_SHORT).concat(Object.keys(setups || {}).filter(function (k) { return !SETUP_SHORT[k]; })).forEach(function (key) {
      var info = setups && setups[key];
      if (!info || !SETUP_STATE_SHORT[info.state]) return;
      any = true;
      var evidence = SWING_EVIDENCE_LABEL[info.evidence] ? info.evidence : "";
      var evText = evidence ? SWING_EVIDENCE_LABEL[evidence] : "evidência não informada";
      var chip = el("span", "setup-chip");
      chip.dataset.setup = key;
      chip.dataset.state = info.state;
      chip.dataset.evidence = evidence;
      chip.title = (SETUP_SHORT[key] || key) + ": " + (info.state === "sinal" ? signalText : "em posição") + " — " + evText + " neste ativo";
      chip.appendChild(el("span", "", SETUP_SHORT[key] || key));
      chip.appendChild(el("small", "", SETUP_STATE_SHORT[info.state]));
      // Evidência escrita ao lado do sinal (não só um ponto colorido nem só no title).
      var ev = el("span", "chip-ev");
      ev.dataset.evidence = evidence;
      ev.appendChild(evidenceDot(evidence));
      var shortText = el("span", "", evidence ? SWING_EVIDENCE_SHORT[evidence] : "evid. n/d");
      shortText.setAttribute("aria-hidden", "true");
      ev.appendChild(shortText);
      ev.appendChild(el("span", "sr-only", evText));
      chip.appendChild(ev);
      td.appendChild(chip);
    });
    if (!any) td.appendChild(el("span", "muted", DASH));
  }

  function renderScreener(emptyText) {
    var sc = state.screener;
    var table = $("ranking-table");
    var body = table.tBodies[0];
    clear(body);
    table.querySelectorAll("thead th").forEach(function (th) {
      var btn = th.querySelector("[data-sort]");
      if (btn && btn.dataset.sort === sc.sort) {
        th.setAttribute("aria-sort", sc.order === "asc" ? "ascending" : "descending");
      } else {
        th.removeAttribute("aria-sort");
      }
    });

    var pages = Math.max(1, Math.ceil(sc.total / sc.pageSize));
    $("screener-page").textContent = "página " + fmtNum(sc.page, 0) + " de " + fmtNum(pages, 0)
      + " · " + fmtNum(sc.total, 0) + (sc.total === 1 ? " papel" : " papéis");
    $("screener-prev").disabled = sc.page <= 1;
    $("screener-next").disabled = sc.page >= pages;

    if (!sc.rows.length) {
      var tr = el("tr");
      var td = el("td", "empty", emptyText || "Nenhum papel com dados suficientes neste filtro.");
      td.colSpan = SCREENER_COLS;
      tr.appendChild(td);
      body.appendChild(tr);
      return;
    }
    var first = (sc.page - 1) * sc.pageSize;
    sc.rows.forEach(function (r, i) {
      var tr = el("tr");
      tr.dataset.assetId = String(r.id);
      tr.dataset.symbol = r.symbol;
      tr.dataset.market = r.market;
      tr.tabIndex = 0;
      tr.title = "Abrir " + r.symbol + " no gráfico";
      tr.appendChild(el("td", "num muted", first + i + 1));
      tr.appendChild(el("td", "sym", r.symbol));
      var rowName = displayName(r.name, r.symbol);
      var nameTd = el("td", "name", rowName || DASH);
      if (rowName) nameTd.title = rowName;
      tr.appendChild(nameTd);
      tr.appendChild(el("td", "", marketLabel(r.market)));
      numCell(tr, r.price, isNum(r.price) ? fmtNum(r.price, priceDigits(r.price)) : DASH, false);
      numCell(tr, r.change_pct, fmtPct(r.change_pct), true);
      numCell(tr, r.score, fmtSigned(r.score, 1), true);
      var vTd = el("td");
      var verdict = VERDICT_LABEL[r.verdict] ? r.verdict : "insuficiente";
      var badge = el("span", "badge", VERDICT_SHORT[verdict]);
      badge.dataset.verdict = verdict;
      vTd.appendChild(badge);
      tr.appendChild(vTd);
      var eTd = el("td", "ev", EVIDENCE_LABEL[r.evidence] || r.evidence || DASH);
      eTd.dataset.evidence = EVIDENCE_LABEL[r.evidence] ? r.evidence : "";
      tr.appendChild(eTd);
      var sTd = el("td", "setups");
      setupChips(sTd, r);
      tr.appendChild(sTd);
      numCell(tr, r.momentum, fmtSigned(r.momentum, 2), true);
      numCell(tr, r.trend, fmtSigned(r.trend, 2), true);
      numCell(tr, r.dist_sma200, fmtSigned(r.dist_sma200, 2), true);
      numCell(tr, r.reversal, fmtSigned(r.reversal, 2), true);
      numCell(tr, r.volatility, fmtShare(r.volatility, 1), false);
      numCell(tr, r.drawdown, fmtPct(r.drawdown, 1), true);
      body.appendChild(tr);
    });
  }

  function sumRow(card, label, value) {
    var row = el("div", "sum-row");
    row.appendChild(el("span", "", label));
    row.appendChild(el("b", "", value));
    card.appendChild(row);
  }

  // Faixa de resumo: amplitude do escopo e, por setup, quantos estão ativos hoje
  // com a evidência agregada (todas as operações de todos os papéis) e o IC.
  function renderScreenerSummary(sum) {
    var root = $("screener-summary");
    clear(root);
    if (!sum) { root.hidden = true; return; }
    root.hidden = false;

    var breadth = el("div", "sum-card");
    breadth.appendChild(el("div", "sum-title", "Amplitude"));
    sumRow(breadth, "Papéis analisados", isNum(sum.count) ? fmtNum(sum.count, 0) : DASH);
    sumRow(breadth, "Acima da média de 200", fmtShare(sum.pct_above_sma200, 1));
    var verdicts = el("div", "sum-verdicts");
    var v = sum.verdicts || {};
    ["comprar", "manter", "vender"].forEach(function (key) {
      var badge = el("span", "badge", VERDICT_SHORT[key] + " " + (isNum(v[key]) ? fmtNum(v[key], 0) : DASH));
      badge.dataset.verdict = key;
      verdicts.appendChild(badge);
    });
    breadth.appendChild(verdicts);
    root.appendChild(breadth);

    (Array.isArray(sum.setups) ? sum.setups : []).forEach(function (s) {
      if (!s) return;
      var pooled = s.pooled || {};
      var card = el("div", "sum-card sum-setup");
      card.dataset.setup = s.key || "";
      card.appendChild(el("div", "sum-title", s.label || s.key || ""));
      sumRow(card, "Ativos hoje", isNum(s.active) ? fmtNum(s.active, 0) : DASH);
      var known = !!SWING_EVIDENCE_LABEL[pooled.evidence];
      var ev = el("div", "sum-ev");
      ev.dataset.evidence = known ? pooled.evidence : "";
      ev.appendChild(evidenceDot(known ? pooled.evidence : ""));
      ev.appendChild(el("span", "", known ? SWING_EVIDENCE_LABEL[pooled.evidence] : "evidência não informada"));
      card.appendChild(ev);
      var ci = el("div", "sum-detail");
      ci.appendChild(document.createTextNode("excesso médio "));
      ci.appendChild(el("b", signClass(pooled.mean_excess), fmtPct(pooled.mean_excess, 2)));
      ci.appendChild(document.createTextNode(" · IC 95% "));
      ci.appendChild(el("b", "", isNum(pooled.ci_low) && isNum(pooled.ci_high)
        ? fmtPct(pooled.ci_low, 2) + " a " + fmtPct(pooled.ci_high, 2) : DASH));
      if (pooled.evidence === "amostra_insuficiente") ci.appendChild(document.createTextNode(" (menos de 100 operações)"));
      card.appendChild(ci);
      // No escopo, "acerto" é ficar acima de segurar o papel — não é retorno positivo.
      card.appendChild(el("div", "sum-detail", (isNum(pooled.trades) ? fmtNum(pooled.trades, 0) : DASH)
        + " operações no escopo · " + fmtShare(pooled.win_rate, 0) + " acima de segurar"));
      root.appendChild(card);
    });
    root.appendChild(el("p", "sum-method", SCREENER_METHOD));
  }

  function renderScreenerProgress(p) {
    var node = $("screener-progress");
    // `ready` conta todo membro já processado (com linha, sem histórico ou com falha): chega a `total` e a consulta para.
    var building = !!p && isNum(p.total) && isNum(p.ready) && p.ready < p.total;
    var parts = [];
    if (building) {
      parts.push("montando o índice: " + fmtNum(p.ready, 0) + " de " + fmtNum(p.total, 0)
        + " papéis — a tabela e o resumo crescem conforme os papéis são analisados.");
    }
    if (p && isNum(p.insufficient) && p.insufficient > 0) parts.push(fmtNum(p.insufficient, 0) + " sem histórico suficiente");
    if (p && isNum(p.failed) && p.failed > 0) parts.push(fmtNum(p.failed, 0) + " com falha na fonte");
    node.textContent = parts.join(" · ");
    node.dataset.state = building ? "building" : "done";
    node.hidden = !parts.length;
    return building;
  }

  function renderScreenerNote(scope, updatedAt, errorText, staleRows) {
    var note = $("ranking-note");
    clear(note);
    if (errorText) { note.textContent = errorText; return; }
    note.appendChild(document.createTextNode(
      "Fatores normalizados de −1 a +1. Clique numa linha para abrir o ativo no gráfico. Selos de setup trazem a evidência no histórico do próprio ativo:"));
    var legend = el("span", "ev-legend");
    SWING_EVIDENCE_ORDER.forEach(function (key) {
      var item = el("span");
      item.appendChild(evidenceDot(key));
      item.appendChild(document.createTextNode(
        SWING_EVIDENCE_SHORT[key] === SWING_EVIDENCE_LEGEND[key] ? SWING_EVIDENCE_LEGEND[key]
          : SWING_EVIDENCE_SHORT[key] + " = " + SWING_EVIDENCE_LEGEND[key]));
      legend.appendChild(item);
    });
    note.appendChild(legend);
    var tail = [];
    var when = updatedAt ? fmtDateTime(updatedAt) : "";
    if (when) tail.push("Análise de " + when + ".");
    if (isNum(staleRows) && staleRows > 0) {
      tail.push(fmtNum(staleRows, 0) + (staleRows === 1 ? " papel" : " papéis") + " com dados do pregão anterior.");
    }
    if (scope === "watchlist") {
      var market = $("ranking-market").value;
      var out = state.assets.filter(function (a) { return (!market || a.market === market) && a.status !== "ok"; });
      if (out.length) tail.push("Fora do screener por dados insuficientes: " + out.map(function (a) { return a.symbol; }).join(", ") + ".");
    }
    if (tail.length) note.appendChild(document.createTextNode("· " + tail.join(" ")));
  }

  // Enquanto o índice é montado, consulta só o progresso; a tabela é recarregada
  // quando o número de papéis prontos muda (não a cada ciclo, para não roubar o foco).
  function pollScreener(token, scope) {
    window.clearTimeout(screenerTimer);
    screenerTimer = window.setTimeout(function () {
      if (token !== screenerToken || state.tab !== "ranking") return;
      if (document.hidden) { pollScreener(token, scope); return; }
      api("/api/screener/progress?scope=" + encodeURIComponent(scope)).then(function (p) {
        if (token !== screenerToken || state.tab !== "ranking") return;
        if (p && p.ready !== screenerReady) { loadScreener(); return; }
        if (renderScreenerProgress(p)) pollScreener(token, scope);
      }, function () {
        if (token === screenerToken) pollScreener(token, scope);
      });
    }, SCREENER_POLL_MS);
  }

  function loadScreener() {
    var token = ++screenerToken;
    window.clearTimeout(screenerTimer);
    var sc = state.screener;
    var scope = screenerScope();
    var isIndex = scope !== "watchlist";
    var q = ["scope=" + encodeURIComponent(scope), "sort=" + encodeURIComponent(sc.sort), "order=" + encodeURIComponent(sc.order),
      "page=" + sc.page, "page_size=" + sc.pageSize];
    var filtered = false;
    [["market", "ranking-market"], ["verdict", "screener-verdict"], ["evidence", "screener-evidence"], ["setup", "screener-setup"]]
      .forEach(function (f) {
        var value = $(f[1]).value;
        if (value) { q.push(f[0] + "=" + encodeURIComponent(value)); filtered = true; }
      });

    return Promise.all([
      settle(api("/api/screener?" + q.join("&"))),
      settle(api("/api/screener/summary?scope=" + encodeURIComponent(scope))),
      isIndex ? settle(api("/api/screener/progress?scope=" + encodeURIComponent(scope))) : Promise.resolve({ ok: true, value: null }),
    ]).then(function (res) {
      if (token !== screenerToken) return null;
      var rows = res[0], sum = res[1], prog = res[2];
      var progress = prog.ok ? prog.value : null;
      var building = renderScreenerProgress(progress);
      screenerReady = progress ? progress.ready : null;
      renderScreenerSummary(sum.ok ? sum.value : null);

      if (rows.ok) {
        var data = rows.value || {};
        sc.rows = Array.isArray(data.rows) ? data.rows : [];
        sc.total = isNum(data.total) ? data.total : sc.rows.length;
        var pages = Math.max(1, Math.ceil(sc.total / sc.pageSize));
        if (sc.page > pages) { sc.page = pages; return loadScreener(); }  // a lista encolheu
        renderScreener(filtered ? "Nenhum papel neste filtro."
          : building ? "Nenhum papel analisado ainda — o índice está sendo montado."
          : isIndex ? "Nenhum papel analisado neste índice ainda. A composição é carregada em segundo plano."
          : "Nenhum ativo da watchlist com dados suficientes.");
        renderScreenerNote(scope, data.updated_at, "", data.stale_rows);
      } else {
        report(rows.error);
        if (!isNetworkFailure(rows.error)) {
          sc.rows = []; sc.total = 0;
          renderScreener("Não foi possível montar o screener.");
          renderScreenerNote(scope, null, rows.error.message);
        }
      }
      if (building) pollScreener(token, scope);
      return null;
    });
  }

  function screenerFilterChanged() {
    state.screener.page = 1;
    loadScreener();
  }

  // Um índice é de um mercado só: o filtro de mercado só faz sentido na watchlist.
  function screenerScopeChanged() {
    var market = $("ranking-market");
    market.value = "";
    market.disabled = screenerScope() !== "watchlist";
    market.title = market.disabled ? "Filtro de mercado vale só para a watchlist" : "";
    screenerFilterChanged();
  }

  // -------------------------------------------------------------- carteira
  var portfolioToken = 0;

  function heatColor(v) {
    if (!isNum(v)) return "";
    var a = Math.min(1, Math.abs(v)) * 0.85;
    return "rgba(" + (v >= 0 ? HEAT_POS : HEAT_NEG) + ", " + a.toFixed(3) + ")";
  }

  function renderPortfolio(data) {
    var weightsEl = $("portfolio-weights"), statsEl = $("portfolio-stats"), corrEl = $("portfolio-correlation");
    clear(weightsEl); clear(statsEl); clear(corrEl);

    var weights = Array.isArray(data.weights) ? data.weights : [];
    var max = weights.reduce(function (m, w) { return isNum(w.weight) && w.weight > m ? w.weight : m; }, 0);
    var dup = Object.create(null);
    weights.forEach(function (w) { dup[w.symbol] = (dup[w.symbol] || 0) + 1; });
    weights.forEach(function (w) {
      var row = el("div", "weight-row");
      row.dataset.symbol = w.symbol;
      row.dataset.assetId = String(w.id);
      var name = dup[w.symbol] > 1 ? w.symbol + " (" + w.market + ")" : w.symbol;
      var company = displayName(w.name, w.symbol);
      var idCell = el("span", "w-id");
      idCell.title = name + (company ? " · " + company : "") + " · " + marketLabel(w.market);
      idCell.appendChild(el("span", "w-sym", name));
      if (company) idCell.appendChild(el("span", "w-name", company));
      row.appendChild(idCell);
      var bar = el("span", "w-bar");
      var fill = el("i");
      fill.style.width = (max > 0 && isNum(w.weight) ? Math.max(0, w.weight / max) * 100 : 0) + "%";
      bar.appendChild(fill);
      row.appendChild(bar);
      row.appendChild(el("span", "w-val", fmtShare(w.weight, 1)));
      weightsEl.appendChild(row);
    });

    var s = data.stats || {};
    var stat = function (label, text, cls) {
      var box = el("div");
      box.appendChild(el("dt", "", label));
      box.appendChild(el("dd", cls || "", text));
      statsEl.appendChild(box);
    };
    stat("Retorno anual", fmtPct(s.ann_return, 1), signClass(s.ann_return));
    stat("Volatilidade anual", fmtShare(s.ann_vol, 1));
    stat("Sharpe", fmtNum(s.sharpe, 2));
    stat("Drawdown máximo", fmtPct(s.max_drawdown, 1), signClass(s.max_drawdown));
    if (isNum(data.weeks)) stat("Semanas em comum", fmtNum(data.weeks, 0));
    $("portfolio-note").textContent = data.note || "";
    $("portfolio-note").hidden = !data.note;

    var corr = data.correlation || {};
    var labels = Array.isArray(corr.labels) ? corr.labels : [];
    var matrix = Array.isArray(corr.matrix) ? corr.matrix : [];
    var thead = el("thead"), headRow = el("tr");
    headRow.appendChild(el("th", "", ""));
    labels.forEach(function (label) {
      var th = el("th", "", label);
      th.scope = "col";
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    corrEl.appendChild(thead);
    var tbody = el("tbody");
    labels.forEach(function (label, i) {
      var tr = el("tr");
      var th = el("th", "", label);
      th.scope = "row";
      tr.appendChild(th);
      labels.forEach(function (other, j) {
        var v = Array.isArray(matrix[i]) ? matrix[i][j] : null;
        var td = el("td", "", isNum(v) ? fmtNum(v, 2) : DASH);
        td.style.backgroundColor = heatColor(v);
        td.title = label + " × " + other + ": " + (isNum(v) ? fmtSigned(v, 2) : DASH);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    corrEl.appendChild(tbody);
  }

  function loadPortfolio() {
    var token = ++portfolioToken;
    var params = ["method=" + encodeURIComponent($("portfolio-method").value)];
    var market = $("portfolio-market").value;
    if (market) params.push("market=" + encodeURIComponent(market));
    var errEl = $("portfolio-error"), content = $("portfolio-content");
    return api("/api/portfolio?" + params.join("&")).then(function (data) {
      if (token !== portfolioToken) return;
      hideIfPresent("portfolio-loading");
      errEl.hidden = true; errEl.textContent = "";
      content.hidden = false;
      renderPortfolio(data || {});
    }, function (err) {
      if (token !== portfolioToken) return;
      if (isNetworkFailure(err)) { report(err); return; }
      hideIfPresent("portfolio-loading");
      errEl.textContent = "Não foi possível montar a carteira: " + err.message + ".";
      errEl.hidden = false;
      content.hidden = true;
    });
  }

  // ------------------------------------------------------------------ abas
  var TABS = ["chart", "ranking", "portfolio"];

  function loadTabData() {
    if (state.tab === "ranking") return loadScreener();
    if (state.tab === "portfolio") return loadPortfolio();
    return Promise.resolve();
  }

  function setTab(tab) {
    if (TABS.indexOf(tab) < 0) return;
    state.tab = tab;
    TABS.forEach(function (t) {
      $("tab-" + t).setAttribute("aria-selected", String(t === tab));
      $("view-" + t).hidden = t !== tab;
    });
    if (tab !== "ranking") window.clearTimeout(screenerTimer);
    if (tab === "chart") catchUpIntraday();
    loadTabData();
  }

  // ------------------------------------------------------- ciclo de dados
  function reloadAll() {
    return loadAssets().then(function () {
      return Promise.all([loadDetail(), loadTabData()]);
    }).catch(report);
  }

  var openedToken = 0;
  var openedBusy = false;  // reabertura em voo: não empilha outra por cima

  // O ativo aberto fora da watchlist não vem em /api/assets: o resumo dele (preço,
  // variação, veredito) é renovado reabrindo-o. Só troca o resumo; não mexe em
  // seleção, busca nem sobreposições, e desiste se o usuário mudou algo no meio.
  function refreshOpened() {
    var o = state.opened;
    if (!o || state.selectedId !== o.id || state.opening || openedBusy) return Promise.resolve(false);
    if (o.status === "insuficiente") return Promise.resolve(false);  // reabrir refaria a análise a cada ciclo, à toa
    var token = ++openedToken, guard = openToken;
    openedBusy = true;
    return api("/api/assets/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: o.symbol, market: o.market }),
    }).then(function (summary) {
      openedBusy = false;
      if (token !== openedToken || guard !== openToken || state.opened !== o || state.selectedId !== o.id) return false;
      if (!summary || summary.id !== o.id || summary.watch) return false;  // promovido em outra aba: /api/assets cuida
      state.opened = summary;
      return true;
    }, function () { openedBusy = false; return false; });  // falha aqui fica calada: o resumo antigo continua valendo
  }

  function autoRefresh() {
    if (document.hidden) return;
    loadAssets().then(refreshOpened).then(function () {
      var a = findAsset(state.selectedId);
      var stamp = a && a.last_refresh ? a.last_refresh : "";
      if (state.selectedId !== null && (stamp !== detailStamp || loadedKey === "")) return loadDetail();
      renderChartHeader(a);
      return null;
    }).catch(report);
  }

  function requestRefresh() {
    var btn = $("refresh-btn");
    if (btn.disabled) return;
    btn.disabled = true;
    btn.textContent = "Atualizando…";
    var done = function () { btn.disabled = false; btn.textContent = "Atualizar dados"; };
    api("/api/refresh", { method: "POST" }).then(function () {
      window.setTimeout(function () { reloadAll().then(done, done); }, 5000);
    }, function (err) {
      showNetError(err, isNetworkFailure(err)
        ? "Não foi possível pedir a atualização dos dados: sem resposta do servidor."
        : "Não foi possível pedir a atualização dos dados: " + err.message);
      done();
    });
  }

  // ------------------------------------------------- adicionar / remover
  function showAddError(text) {
    var node = $("add-error");
    node.textContent = text || "";
    node.hidden = !text;
  }

  function addAsset(event) {
    event.preventDefault();
    var input = $("add-symbol"), btn = $("add-submit");
    var symbol = input.value.trim();
    if (!symbol) { showAddError("Informe um símbolo."); input.focus(); return; }
    if (symbol.length > 32) { showAddError("símbolo inválido"); input.focus(); return; }  // limite da API
    if (btn.disabled) return;
    cancelSearch();
    showAddError("");
    btn.disabled = true;
    btn.textContent = "Adicionando…";
    api("/api/assets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: symbol, market: $("add-market").value }),
    }).then(function (created) {
      input.value = "";
      showAddError("");
      return loadAssets().then(function () {
        if (created && watchAsset(created.id)) selectAsset(created.id);
        renderChartHeader(findAsset(state.selectedId));
        return loadTabData();
      });
    }).catch(function (err) {
      // 422 (símbolo/mercado), 409 (já está) e 502 (fonte fora do ar) trazem o motivo em detail.
      if (err instanceof ApiError && err.status >= 400) showAddError(err.message);
      else { showAddError("Não foi possível adicionar agora. Tente de novo."); report(err); }
    }).then(function () {
      btn.disabled = false;
      btn.textContent = "Adicionar";
    });
  }

  // keepView (botão do cabeçalho): o ativo sai da watchlist mas continua na tela.
  function removeAsset(id, button, keepView) {
    if (button) button.disabled = true;
    showAddError("");
    var before = findAsset(id);
    // Papel de índice não é apagado no servidor, só sai da watchlist: pode seguir selecionado.
    var survives = !!before && Array.isArray(before.indices) && before.indices.length > 0;
    return api("/api/assets/" + id, { method: "DELETE" }).catch(function (err) {
      if (!(err instanceof ApiError && err.status === 404)) throw err;  // já não existe: só recarrega
      survives = false;
    }).then(function () {
      var wasSelected = state.selectedId === id;
      var reopen = null;
      if (wasSelected && survives) {
        var copy = {};
        Object.keys(before).forEach(function (k) { copy[k] = before[k]; });
        copy.watch = false;
        state.opened = copy;
        persistSelection();
      } else if (wasSelected) {
        state.selectedId = null;
        // Apagado no servidor: para continuar na tela, abre de novo sob demanda.
        if (keepView && before) reopen = openAsset(before.symbol, before.market);
      }
      return loadAssets().then(function () {
        if (reopen) return reopen;
        if (wasSelected && survives) { renderChartHeader(findAsset(id)); return null; }
        if (wasSelected) { persistSelection(); return loadDetail(); }
        return null;
      }).then(loadTabData);
    }).catch(function (err) {
      if (button && !keepView) button.disabled = false;
      report(err);
    }).then(function () {
      if (button && keepView) button.disabled = false;
    });
  }

  function toggleWatch() {
    var a = findAsset(state.selectedId), btn = $("watch-toggle");
    if (!a || btn.disabled) return;
    if (a.watch !== false) { removeAsset(a.id, btn, true); return; }
    btn.disabled = true;
    showAddError("");
    api("/api/assets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: a.symbol, market: a.market }),
    }).catch(function (err) {
      if (err instanceof ApiError && err.status === 409) return null;  // já estava: só recarrega
      throw err;
    }).then(function (created) {
      return loadAssets().then(function () {
        if (created && created.id !== a.id && state.selectedId === a.id && watchAsset(created.id)) selectAsset(created.id);
        else persistSelection();
        return loadTabData();
      });
    }).catch(function (err) {
      if (err instanceof ApiError && err.status > 0) {
        showNetError(err, "Não foi possível adicionar " + a.symbol + " à watchlist: " + err.message);
      } else report(err);
    }).then(function () {
      btn.disabled = false;
      renderChartHeader(findAsset(state.selectedId));
    });
  }

  // ------------------------------------------------------ busca no catálogo
  var search = { token: 0, timer: 0, items: [], active: -1, open: false, busy: false, busyTimer: 0, inflight: null };
  var SEARCH_DEBOUNCE_MS = 200;
  // A busca pode ir à rede e levar segundos. O aviso "buscando…" só entra se a
  // resposta demorar mais que isto, para não piscar a cada tecla na busca local.
  // O atraso vale a partir do estado ocioso: com uma requisição ainda sem resposta,
  // digitar outra tecla não reinicia a contagem nem tira o aviso da tela.
  var SEARCH_BUSY_AFTER_MS = 150;

  // Volta ao estado ocioso: cancela a requisição em voo e tira o aviso.
  function searchIdle() {
    if (search.inflight) { try { search.inflight.abort(); } catch (e) { /* já encerrada */ } }
    search.inflight = null;
    window.clearTimeout(search.busyTimer);
    search.busyTimer = 0;
    search.busy = false;
    var node = $("search-results").querySelector(".search-busy");
    if (node) node.parentNode.removeChild(node);
  }

  function closeSearch() {
    search.open = false;
    search.active = -1;
    $("search-results").hidden = true;
    var input = $("add-symbol");
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  }

  // Cancela busca pendente e respostas em trânsito (ex.: ao enviar o formulário).
  function cancelSearch() {
    window.clearTimeout(search.timer);
    search.token++;
    search.items = [];
    searchIdle();
    closeSearch();
  }

  function setSearchActive(index) {
    var nodes = $("search-results").querySelectorAll(".search-item");
    search.active = index;
    nodes.forEach(function (node, i) { node.setAttribute("aria-selected", String(i === index)); });
    var input = $("add-symbol");
    if (index >= 0 && nodes[index]) {
      input.setAttribute("aria-activedescendant", nodes[index].id);
      if (nodes[index].scrollIntoView) nodes[index].scrollIntoView({ block: "nearest" });
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  }

  function renderSearch(query) {
    var root = $("search-results");
    clear(root);
    search.items.forEach(function (r, i) {
      var li = el("li", "search-item");
      li.id = "search-opt-" + i;
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", "false");
      li.dataset.symbol = r.symbol;
      li.dataset.market = r.market;
      li.appendChild(el("span", "search-sym", r.symbol));
      var kind = el("span", "search-kind");
      kind.appendChild(el("span", "tag", marketLabel(r.market)));
      if (r.kind) kind.appendChild(document.createTextNode(r.kind));
      li.appendChild(kind);
      li.appendChild(el("span", "search-name", displayName(r.name, r.symbol)));
      var indices = (Array.isArray(r.indices) ? r.indices : []).map(function (c) { return INDEX_LABEL[c] || c; });
      li.appendChild(el("span", "search-idx", indices.join(" · ")));
      li.title = "Abrir " + r.symbol + " no gráfico (sem adicionar à watchlist)";
      root.appendChild(li);
    });
    if (search.busy) {
      // Fica acima dos resultados anteriores, que continuam na lista até a resposta chegar.
      var busy = el("li", "search-busy", "buscando…");
      busy.setAttribute("role", "status");
      root.insertBefore(busy, root.firstChild);
    } else if (!search.items.length) {
      root.appendChild(el("li", "search-empty",
        "Nenhum papel encontrado para “" + query + "”. Tente o código, ex.: BBAS3. "
        + "Para buscar o símbolo direto na fonte, escolha o mercado e use Adicionar."));
    }
    root.hidden = false;
    search.open = true;
    search.active = -1;
    var input = $("add-symbol");
    input.setAttribute("aria-expanded", "true");
    input.removeAttribute("aria-activedescendant");
  }

  function runSearch() {
    var query = $("add-symbol").value.trim();
    var token = ++search.token;
    if (!query) { search.items = []; searchIdle(); closeSearch(); return; }

    // A resposta da consulta anterior seria descartada: cancela para não esperar por ela.
    if (search.inflight) { try { search.inflight.abort(); } catch (e) { /* já encerrada */ } }
    var controller = typeof AbortController === "function" ? new AbortController() : {};
    search.inflight = controller;
    if (!search.busy && !search.busyTimer) {
      search.busyTimer = window.setTimeout(function () {
        search.busyTimer = 0;
        if (!search.inflight) return;
        search.busy = true;
        if (document.activeElement === $("add-symbol")) renderSearch($("add-symbol").value.trim());
      }, SEARCH_BUSY_AFTER_MS);
    }

    api("/api/search?q=" + encodeURIComponent(query), controller.signal ? { signal: controller.signal } : undefined).then(function (list) {
      if (token !== search.token) return;
      search.inflight = null;  // já respondeu: nada a cancelar
      searchIdle();
      search.items = (Array.isArray(list) ? list : []).filter(function (r) {
        return r && typeof r.symbol === "string" && typeof r.market === "string";
      });
      if (document.activeElement === $("add-symbol")) renderSearch(query);
    }, function () {
      // Requisição cancelada (token antigo) ou falha: a busca é acessória, fica calada.
      if (token === search.token) { search.inflight = null; searchIdle(); search.items = []; closeSearch(); }
    });
  }

  function chooseSearch(index) {
    var item = search.items[index];
    if (!item) return;
    $("add-symbol").value = "";
    cancelSearch();
    setTab("chart");
    openAsset(item.symbol, item.market);
  }

  function searchKeydown(event) {
    var count = search.items.length;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (!count) return;
      event.preventDefault();
      if (!search.open) { renderSearch($("add-symbol").value.trim()); }
      var step = event.key === "ArrowDown" ? 1 : -1;
      var next = search.active < 0 ? (step > 0 ? 0 : count - 1) : (search.active + step + count) % count;
      setSearchActive(next);
    } else if (event.key === "Enter") {
      // Com um resultado destacado, Enter abre o ativo; sem destaque, o formulário
      // segue o caminho de sempre (adicionar o que foi digitado à watchlist).
      if (search.open && search.active >= 0) { event.preventDefault(); chooseSearch(search.active); }
    } else if (event.key === "Escape") {
      // Invalida também a busca pendente ou em voo, para a lista não reabrir sozinha.
      if (search.open) event.preventDefault();
      window.clearTimeout(search.timer);
      search.token++;
      searchIdle();
      closeSearch();
    }
  }

  // ------------------------------------------------------------------ tema
  function setTheme(theme) {
    state.theme = theme === "light" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", state.theme);
    storageSet(THEME_KEY, state.theme);
    applyChartTheme();
    renderLegends(null);
  }

  // ------------------------------------------------------------------ init
  function bind() {
    TABS.forEach(function (t) {
      $("tab-" + t).addEventListener("click", function () { setTab(t); });
    });
    INTERVALS.forEach(function (i) {
      $("interval-" + i).addEventListener("click", function () { setInterval_(i); });
    });
    document.querySelectorAll("[data-overlay]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var key = btn.dataset.overlay;
        state.overlays[key] = !state.overlays[key];
        applyOverlays();
      });
    });

    $("watchlist").addEventListener("click", function (event) {
      var target = event.target instanceof Element ? event.target : null;
      if (!target) return;
      var item = target.closest("[data-asset-id]");
      if (!item) return;
      var id = Number(item.dataset.assetId);
      var rm = target.closest(".remove-asset");
      if (rm) { event.stopPropagation(); removeAsset(id, rm); return; }
      selectAsset(id);
    });

    $("add-form").addEventListener("submit", addAsset);
    var searchInput = $("add-symbol"), searchList = $("search-results");
    searchInput.addEventListener("input", function () {
      showAddError("");
      window.clearTimeout(search.timer);
      search.timer = window.setTimeout(runSearch, SEARCH_DEBOUNCE_MS);
    });
    searchInput.addEventListener("keydown", searchKeydown);
    searchInput.addEventListener("focus", function () {
      if (search.items.length && searchInput.value.trim()) renderSearch(searchInput.value.trim());
    });
    searchInput.addEventListener("blur", function () { window.setTimeout(closeSearch, 120); });
    // mousedown não tira o foco do campo; a escolha acontece no click.
    searchList.addEventListener("mousedown", function (event) { event.preventDefault(); });
    searchList.addEventListener("click", function (event) {
      var item = event.target instanceof Element ? event.target.closest(".search-item") : null;
      if (!item) return;
      chooseSearch(Array.prototype.indexOf.call(searchList.querySelectorAll(".search-item"), item));
    });

    $("watch-toggle").addEventListener("click", toggleWatch);
    $("rec-tab-position").addEventListener("click", function () { setRecTab("position"); });
    $("rec-tab-swing").addEventListener("click", function () { setRecTab("swing"); });
    $("swing-setups").addEventListener("click", function (event) {
      var block = event.target instanceof Element ? event.target.closest(".swing-setup") : null;
      if (block && block.dataset.setup) pickSetup(block.dataset.setup);
    });
    document.addEventListener("visibilitychange", catchUpIntraday);

    var rankingTable = $("ranking-table");
    rankingTable.tHead.addEventListener("click", function (event) {
      var btn = event.target instanceof Element ? event.target.closest("[data-sort]") : null;
      if (!btn) return;
      var key = btn.dataset.sort, sc = state.screener;
      if (sc.sort === key) {
        sc.order = sc.order === "asc" ? "desc" : "asc";
      } else {
        sc.sort = key;
        sc.order = key === "symbol" ? "asc" : "desc";
      }
      screenerFilterChanged();
    });
    var openRow = function (event) {
      var row = event.target instanceof Element ? event.target.closest("tr[data-asset-id]") : null;
      if (!row) return;
      if (event.type === "keydown" && event.key !== "Enter") return;
      var id = Number(row.dataset.assetId);
      setTab("chart");
      // Da watchlist: seleção direta. Papel de índice fora dela: abre sob demanda.
      if (watchAsset(id)) selectAsset(id);
      else openAsset(row.dataset.symbol, row.dataset.market);
    };
    rankingTable.tBodies[0].addEventListener("click", openRow);
    rankingTable.tBodies[0].addEventListener("keydown", openRow);
    $("screener-scope").addEventListener("change", screenerScopeChanged);
    ["ranking-market", "screener-verdict", "screener-evidence", "screener-setup"].forEach(function (id) {
      $(id).addEventListener("change", screenerFilterChanged);
    });
    $("screener-prev").addEventListener("click", function () {
      if (state.screener.page > 1) { state.screener.page--; loadScreener(); }
    });
    $("screener-next").addEventListener("click", function () {
      state.screener.page++;
      loadScreener();
    });

    $("portfolio-method").addEventListener("change", loadPortfolio);
    $("portfolio-market").addEventListener("change", loadPortfolio);

    $("theme-toggle").addEventListener("click", function () {
      setTheme(state.theme === "dark" ? "light" : "dark");
    });
    $("refresh-btn").addEventListener("click", requestRefresh);
    $("net-retry").addEventListener("click", function () {
      hideNetError();
      reloadAll();
    });
  }

  function init() {
    bind();
    var chartsReady = false;
    try { chartsReady = createCharts(); } catch (e) { if (window.console) console.error(e); }
    applyOverlays();
    if (!chartsReady) setOverlay("A biblioteca de gráficos não carregou. Recarregue a página.");
    setRecTab(state.recTab);
    // Ativo aberto fora da watchlist na visita anterior: reabre sob demanda. Marcar
    // "opening" antes da primeira carga impede a seleção padrão de piscar na tela.
    var saved = readOpened();
    if (saved) state.opening = saved;
    reloadAll();
    if (saved) openAsset(saved.symbol, saved.market, true);
    window.setInterval(autoRefresh, 60000);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
