/* Radar Quant — frontend em módulo único, sem build e sem dependências além
   da Lightweight Charts (vendor/). Todo texto vindo da API entra no DOM por
   textContent. */
(function () {
  "use strict";

  // ------------------------------------------------------------------ tema
  // Roda antes do <body> existir para não piscar o tema errado.
  var THEME_KEY = "radar-quant:theme";
  var SELECTED_KEY = "radar-quant:selected";

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
    selectedId: null,
    interval: "1d",
    candleCount: 0,
    overlays: { sma20: true, sma50: true, sma200: true, bb: false },
    ranking: { rows: [], sortKey: "score", sortDir: "desc" },
  };
  window.__radar = { state: state };

  var MIN_CANDLES = 300;
  var INTERVALS = ["1d", "1wk", "1mo"];
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

  function fmtDateTime(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return new Intl.DateTimeFormat(LOCALE, {
      day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
    }).format(d);
  }

  function signClass(v) {
    if (!isNum(v) || v === 0) return "";
    return v > 0 ? "pos" : "neg";
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
    if (typeof t === "number") return new Date(t * 1000).toISOString().slice(0, 10);
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

  function toMap(points) {
    var map = Object.create(null);
    (points || []).forEach(function (pt) { if (pt && isNum(pt.value)) map[pt.time] = pt.value; });
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
    var rows = (payload && Array.isArray(payload.candles) ? payload.candles : []).filter(function (c) {
      return c && typeof c.time === "string" && isNum(c.open) && isNum(c.high) && isNum(c.low) && isNum(c.close);
    });
    var ind = (payload && payload.indicators) || {};
    var times = rows.map(function (c) { return c.time; });

    chartData = { times: times, candle: Object.create(null), ind: {} };
    rows.forEach(function (c) { chartData.candle[c.time] = c; });
    ["sma20", "sma50", "sma200", "bb_upper", "bb_lower", "rsi14", "macd", "macd_signal", "macd_hist"].forEach(function (k) {
      chartData.ind[k] = toMap(ind[k]);
    });

    state.candleCount = rows.length;
    if (!charts) { setOverlay("A biblioteca de gráficos não carregou. Recarregue a página."); return; }

    var last = rows.length ? rows[rows.length - 1].close : NaN;
    chartDigits = priceDigits(last);
    var s = charts.series;
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
      var span = { "1d": 180, "1wk": 156, "1mo": 120 }[state.interval] || 180;
      showRange({ from: Math.max(rows.length - span, 0) - 0.5, to: rows.length + 2.5 });
    }
    setOverlay(rows.length ? "" : "Sem dados de preço para este ativo.");
    renderLegends(null);
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

    priceLg.appendChild(el("b", "", fmtDate(key)));
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
  function findAsset(id) {
    for (var i = 0; i < state.assets.length; i++) if (state.assets[i].id === id) return state.assets[i];
    return null;
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
      return [a.id, a.symbol, a.market, a.currency, a.price, a.change_pct, a.status, a.verdict, a.evidence, a.last_error];
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
      if (state.selectedId !== null && !findAsset(state.selectedId)) state.selectedId = null;
      if (state.selectedId === null && state.assets.length) {
        var stored = Number(storageGet(SELECTED_KEY));
        state.selectedId = findAsset(stored) ? stored : state.assets[0].id;
      }
      renderWatchlist();
      renderDataStatus();
      return state.assets;
    });
  }

  // ------------------------------------------------------- ativo em foco
  var detailToken = 0;
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
    excess.appendChild(document.createTextNode("Excesso sobre buy & hold: "));
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

  function clearDetail() {
    detailToken++;
    loadedKey = "";
    detailStamp = "";
    renderChartHeader(null);
    $("chart-asof").textContent = "";
    drawCandles({ candles: [], indicators: {} }, false);
    setOverlay(state.assetsLoaded ? "Adicione um ativo à watchlist para ver o gráfico." : "");
    renderRec(null, null);
    setRecLoading(false);
  }

  function loadDetail() {
    var id = state.selectedId;
    if (id === null) { clearDetail(); return Promise.resolve(); }
    var token = ++detailToken;
    var interval = state.interval;
    var key = id + "|" + interval;
    var fresh = key !== loadedKey;
    var newAsset = String(loadedKey).split("|")[0] !== String(id);
    var summary = findAsset(id);

    renderChartHeader(summary);
    if (newAsset) {
      setRecLoading(true);
      setOverlay("Carregando…");
    }

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
        return loadAssets().then(loadDetail);
      }
      var now = findAsset(id) || summary;
      detailStamp = now && now.last_refresh ? now.last_refresh : "";

      if (c.ok) {
        drawCandles(c.value, fresh);
        loadedKey = key;
      } else {
        report(c.error);
        if (fresh) {
          loadedKey = "";
          drawCandles({ candles: [], indicators: {} }, false);
          setOverlay("Não foi possível carregar os candles.");
        }
      }

      if (a.ok) {
        renderRec(a.value, now);
        $("chart-asof").textContent = a.value && a.value.as_of ? "fechamento de " + fmtDate(a.value.as_of) : "";
      } else {
        report(a.error);
        if (newAsset) { renderRec(null, now); $("chart-asof").textContent = ""; }
      }
      setRecLoading(false);
    });
  }

  function selectAsset(id) {
    if (!findAsset(id)) return;
    var changed = state.selectedId !== id;
    state.selectedId = id;
    storageSet(SELECTED_KEY, String(id));
    renderWatchlist();
    if (changed || loadedKey.split("|")[0] !== String(id)) loadDetail().catch(report);
  }

  function setInterval_(interval) {
    if (INTERVALS.indexOf(interval) < 0) return;
    var changed = state.interval !== interval;
    state.interval = interval;
    INTERVALS.forEach(function (i) { $("interval-" + i).setAttribute("aria-pressed", String(i === interval)); });
    if (changed) loadDetail().catch(report);
  }

  // --------------------------------------------------------------- ranking
  var rankingToken = 0;
  var TEXT_SORT = { symbol: 1, market: 1, verdict: 1, evidence: 1 };

  function sortedRanking() {
    var key = state.ranking.sortKey, dir = state.ranking.sortDir === "asc" ? 1 : -1;
    return state.ranking.rows.slice().sort(function (a, b) {
      var x = a[key], y = b[key];
      if (TEXT_SORT[key]) return dir * String(x || "").localeCompare(String(y || ""), LOCALE);
      var xn = isNum(x), yn = isNum(y);
      if (!xn && !yn) return 0;
      if (!xn) return 1;
      if (!yn) return -1;
      return dir * (x - y);
    });
  }

  function numCell(tr, value, text, colored) {
    tr.appendChild(el("td", "num" + (colored ? " " + signClass(value) : ""), text));
  }

  function renderRanking() {
    var table = $("ranking-table");
    var body = table.tBodies[0];
    clear(body);
    table.querySelectorAll("thead th").forEach(function (th) {
      var btn = th.querySelector("[data-sort]");
      if (btn && btn.dataset.sort === state.ranking.sortKey) {
        th.setAttribute("aria-sort", state.ranking.sortDir === "asc" ? "ascending" : "descending");
      } else {
        th.removeAttribute("aria-sort");
      }
    });
    var rows = sortedRanking();
    if (!rows.length) {
      var tr = el("tr");
      var td = el("td", "empty", "Nenhum ativo com dados suficientes neste filtro.");
      td.colSpan = 12;
      tr.appendChild(td);
      body.appendChild(tr);
      return;
    }
    rows.forEach(function (r, i) {
      var tr = el("tr");
      tr.dataset.assetId = String(r.id);
      tr.dataset.symbol = r.symbol;
      tr.tabIndex = 0;
      tr.title = "Abrir " + r.symbol + " no gráfico";
      tr.appendChild(el("td", "num muted", i + 1));
      tr.appendChild(el("td", "sym", r.symbol));
      tr.appendChild(el("td", "", marketLabel(r.market)));
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
      numCell(tr, r.momentum, fmtSigned(r.momentum, 2), true);
      numCell(tr, r.trend, fmtSigned(r.trend, 2), true);
      numCell(tr, r.dist_sma200, fmtSigned(r.dist_sma200, 2), true);
      numCell(tr, r.reversal, fmtSigned(r.reversal, 2), true);
      numCell(tr, r.volatility, fmtShare(r.volatility, 1), false);
      numCell(tr, r.drawdown, fmtPct(r.drawdown, 1), true);
      body.appendChild(tr);
    });
  }

  function renderRankingNote(market) {
    var ranked = Object.create(null);
    state.ranking.rows.forEach(function (r) { ranked[r.id] = true; });
    var out = state.assets.filter(function (a) { return (!market || a.market === market) && !ranked[a.id]; });
    var base = "Fatores normalizados de −1 a +1. Clique numa linha para abrir o ativo no gráfico.";
    $("ranking-note").textContent = out.length
      ? base + " Fora do ranking por dados insuficientes: " + out.map(function (a) { return a.symbol; }).join(", ") + "."
      : base;
  }

  function loadRanking() {
    var token = ++rankingToken;
    var market = $("ranking-market").value;
    var url = "/api/ranking" + (market ? "?market=" + encodeURIComponent(market) : "");
    return api(url).then(function (rows) {
      if (token !== rankingToken) return;
      state.ranking.rows = Array.isArray(rows) ? rows : [];
      renderRanking();
      renderRankingNote(market);
    }, function (err) {
      if (token !== rankingToken) return;
      report(err);
      if (!isNetworkFailure(err)) {
        state.ranking.rows = [];
        renderRanking();
        $("ranking-note").textContent = err.message;
      }
    });
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
      var sym = el("span", "w-sym", name);
      sym.title = name + " · " + marketLabel(w.market);
      row.appendChild(sym);
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
    if (state.tab === "ranking") return loadRanking();
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
    loadTabData();
  }

  // ------------------------------------------------------- ciclo de dados
  function reloadAll() {
    return loadAssets().then(function () {
      return Promise.all([loadDetail(), loadTabData()]);
    }).catch(report);
  }

  function autoRefresh() {
    if (document.hidden) return;
    loadAssets().then(function () {
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
    if (btn.disabled) return;
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
        if (created && findAsset(created.id)) selectAsset(created.id);
        return loadTabData();
      });
    }).catch(function (err) {
      if (err instanceof ApiError && err.status >= 400 && err.status < 500) showAddError(err.message);
      else { showAddError("Não foi possível adicionar agora. Tente de novo."); report(err); }
    }).then(function () {
      btn.disabled = false;
      btn.textContent = "Adicionar";
    });
  }

  function removeAsset(id, button) {
    if (button) button.disabled = true;
    showAddError("");
    api("/api/assets/" + id, { method: "DELETE" }).catch(function (err) {
      if (!(err instanceof ApiError && err.status === 404)) throw err;  // já não existe: só recarrega
    }).then(function () {
      var wasSelected = state.selectedId === id;
      if (wasSelected) state.selectedId = null;
      return loadAssets().then(function () {
        if (wasSelected) {
          if (state.selectedId !== null) storageSet(SELECTED_KEY, String(state.selectedId));
          return loadDetail();
        }
        return null;
      }).then(loadTabData);
    }).catch(function (err) {
      if (button) button.disabled = false;
      report(err);
    });
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
    $("add-symbol").addEventListener("input", function () { showAddError(""); });

    var rankingTable = $("ranking-table");
    rankingTable.tHead.addEventListener("click", function (event) {
      var btn = event.target instanceof Element ? event.target.closest("[data-sort]") : null;
      if (!btn) return;
      var key = btn.dataset.sort;
      if (state.ranking.sortKey === key) {
        state.ranking.sortDir = state.ranking.sortDir === "asc" ? "desc" : "asc";
      } else {
        state.ranking.sortKey = key;
        state.ranking.sortDir = TEXT_SORT[key] ? "asc" : "desc";
      }
      renderRanking();
    });
    var openRow = function (event) {
      var row = event.target instanceof Element ? event.target.closest("tr[data-asset-id]") : null;
      if (!row) return;
      if (event.type === "keydown" && event.key !== "Enter") return;
      var id = Number(row.dataset.assetId);
      setTab("chart");
      if (findAsset(id)) selectAsset(id);
      else loadAssets().then(function () { selectAsset(id); }).catch(report);
    };
    rankingTable.tBodies[0].addEventListener("click", openRow);
    rankingTable.tBodies[0].addEventListener("keydown", openRow);
    $("ranking-market").addEventListener("change", loadRanking);

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
    reloadAll();
    window.setInterval(autoRefresh, 60000);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
