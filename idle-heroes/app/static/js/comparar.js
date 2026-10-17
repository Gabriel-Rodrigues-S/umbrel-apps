// Tela 'comparar': escolha de herói·conta, gráfico de evolução e ficha lado a lado.
import { api } from "./api.js";
import {
  TIERS, serie, marcoTransicao, linhasFicha, formatarDuracao, dataBR, dataBRDeMs, ms, dias, diaZero,
} from "./logica.js";

const ATRIBUTOS = [
  ["poder", "Poder"], ["ataque", "Ataque"], ["hp", "HP"],
  ["armadura", "Armadura"], ["velocidade", "Velocidade"], ["arvore", "Nível da árvore"],
];
const MODOS = [["dia0", "Tempo de conta (dia 0)"], ["datas", "Datas reais"]];
const CORES = ["#4c6ef5", "#f76707", "#2f9e44", "#ae3ec9", "#e03131", "#1098ad", "#f59f00", "#868e96"];
const CHAVE_SALVA = "ih-comparar";

const estado = { selecionados: [], extras: [], campo: "poder", modo: "dia0", itens: [] };
const cores = new Map();
let contas = [], herois = [], paresComMedicao = [], grafico = null, pedido = 0;

const $ = (sel) => document.querySelector(sel);
function el(tag, attrs = {}, ...filhos) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  for (const f of filhos) if (f != null) e.append(f);
  return e;
}
const nomeDe = (lista, id) => (lista.find((x) => x.id === id) || {}).nome || `#${id}`;
const rotuloPar = (chave) => {
  const [c, h] = chave.split(":").map(Number);
  return `${nomeDe(herois, h)} · ${nomeDe(contas, c)}`;
};
function corDe(chave) {
  if (!cores.has(chave)) cores.set(chave, CORES[cores.size % CORES.length]);
  return cores.get(chave);
}

function salvar() {
  try {
    localStorage.setItem(CHAVE_SALVA, JSON.stringify({ s: estado.selecionados, e: estado.extras, c: estado.campo }));
  } catch (_) { /* sem armazenamento: tudo bem */ }
}
function restaurar() {
  try {
    const d = JSON.parse(localStorage.getItem(CHAVE_SALVA) || "null");
    if (d) return d;
  } catch (_) { /* ignora */ }
  return null;
}

// --- Montagem da tela ---

function montar() {
  $("#app").replaceChildren(
    el("section", { class: "painel escolha", "aria-labelledby": "t-escolha" },
      el("h2", { id: "t-escolha" }, "Herói · conta"),
      el("div", { id: "lista-pares", class: "lista-pares" }),
      el("details", { class: "adicionar" },
        el("summary", {}, "Adicionar outro herói"),
        el("div", { class: "linha-form" },
          el("label", {}, "Conta", el("select", { id: "add-conta" })),
          el("label", {}, "Herói", el("select", { id: "add-heroi" })),
          el("button", { type: "button", onclick: adicionar }, "Adicionar")))),
    el("section", { class: "painel grafico", "aria-labelledby": "t-grafico" },
      el("div", { class: "controles" },
        el("h2", { id: "t-grafico" }, "Evolução"),
        el("label", {}, "Atributo ", el("select", { id: "campo", onchange: (e) => { estado.campo = e.target.value; salvar(); desenhar(); } })),
        el("div", { class: "modos", role: "group", "aria-label": "Eixo do tempo" },
          ...MODOS.map(([v, r]) => el("button", { type: "button", "data-modo": v, onclick: () => trocarModo(v) }, r)))),
      el("ul", { id: "avisos", class: "avisos" }),
      el("div", { class: "area-grafico" }, el("canvas", { id: "canvas" })),
      el("p", { id: "vazio-grafico", class: "suave", hidden: "" })),
    el("section", { class: "painel ficha", "aria-labelledby": "t-ficha" },
      el("h2", { id: "t-ficha" }, "Ficha (última medição)"),
      el("div", { id: "ficha", class: "rolagem" })),
  );
  $("#campo").append(...ATRIBUTOS.map(([v, r]) => el("option", { value: v }, r)));
  $("#campo").value = estado.campo;
  $("#add-conta").append(...contas.map((c) => el("option", { value: c.id }, c.nome)));
  $("#add-heroi").append(...herois.map((h) => el("option", { value: h.id }, h.nome)));
  marcarModo();
}

function listarPares() {
  const todos = [...paresComMedicao, ...estado.extras.filter((k) => !paresComMedicao.includes(k))];
  const caixa = $("#lista-pares");
  if (!todos.length) {
    caixa.replaceChildren(el("p", { class: "suave" }, "Nenhuma medição cadastrada ainda."));
    return;
  }
  caixa.replaceChildren(...todos.map((chave) => {
    const cb = el("input", { type: "checkbox", value: chave, onchange: alternar });
    cb.checked = estado.selecionados.includes(chave);
    const sem = paresComMedicao.includes(chave) ? null : el("small", { class: "suave" }, " (sem medições)");
    return el("label", { class: "par" }, cb,
      el("span", { class: "amostra", style: `background:${corDe(chave)}` }), rotuloPar(chave), sem);
  }));
}

function alternar(e) {
  const chave = e.target.value;
  estado.selecionados = e.target.checked
    ? [...estado.selecionados, chave]
    : estado.selecionados.filter((k) => k !== chave);
  salvar();
  carregar();
}

function adicionar() {
  const chave = `${$("#add-conta").value}:${$("#add-heroi").value}`;
  if (chave.includes("::") || chave.startsWith(":") || chave.endsWith(":")) return;
  if (!paresComMedicao.includes(chave) && !estado.extras.includes(chave)) estado.extras.push(chave);
  if (!estado.selecionados.includes(chave)) estado.selecionados.push(chave);
  salvar();
  listarPares();
  carregar();
}

function trocarModo(modo) {
  estado.modo = modo;
  marcarModo();
  desenhar();
}
function marcarModo() {
  for (const b of document.querySelectorAll("[data-modo]")) b.setAttribute("aria-pressed", String(b.dataset.modo === estado.modo));
}

// --- Dados ---

async function carregar() {
  const n = ++pedido;
  if (!estado.selecionados.length) {
    estado.itens = [];
    desenhar();
    return;
  }
  try {
    const itens = await api.get(`api/comparacao?pares=${estado.selecionados.join(",")}`);
    if (n !== pedido) return; // chegou uma resposta mais nova
    estado.itens = itens;
  } catch (err) {
    if (n !== pedido) return;
    estado.itens = [];
    $("#avisos").replaceChildren(el("li", { class: "erro" }, `Erro ao carregar: ${err.message}`));
    return;
  }
  desenhar();
}

// --- Gráfico ---

// Trecho "sem medições" na base do gráfico, de 'inicio' até o primeiro ponto (sem valor de y).
const pluginSemMedicoes = {
  id: "semMedicoes",
  afterDatasetsDraw(chart) {
    const { ctx, chartArea: area, scales: { x } } = chart;
    ctx.save();
    chart.data.datasets.forEach((ds, i) => {
      const { inicio, pontos } = ds.extra;
      if (inicio == null || !pontos.length || inicio >= pontos[0].x) return;
      const y = area.bottom - 6 - i * 7;
      const x0 = Math.max(x.getPixelForValue(inicio), area.left), x1 = x.getPixelForValue(pontos[0].x);
      ctx.globalAlpha = 0.45;
      ctx.strokeStyle = ds.borderColor;
      ctx.lineWidth = 3;
      ctx.setLineDash([6, 5]);
      ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke();
      if (x1 - x0 > 90) {
        ctx.setLineDash([]);
        ctx.globalAlpha = 0.75;
        ctx.fillStyle = ds.borderColor;
        ctx.font = "12px system-ui, sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("sem medições", (x0 + x1) / 2, y - 8);
      }
    });
    // Marco de Transição sem ponto no atributo: losango na base, sem valor de y.
    chart.data.datasets.forEach((ds, i) => {
      const m = ds.extra.marcoSolto;
      if (m == null) return;
      const px = x.getPixelForValue(m), y = area.bottom - 6 - i * 7;
      if (px < area.left || px > area.right) return;
      ctx.globalAlpha = 1;
      ctx.setLineDash([]);
      ctx.fillStyle = ds.borderColor;
      ctx.beginPath();
      ctx.moveTo(px, y - 6); ctx.lineTo(px + 6, y); ctx.lineTo(px, y + 6); ctx.lineTo(px - 6, y);
      ctx.closePath(); ctx.fill();
    });
    ctx.restore();
  },
};

// Faixas de fundo dos tiers da árvore.
const pluginTiers = {
  id: "tiers",
  beforeDatasetsDraw(chart) {
    if (estado.campo !== "arvore") return;
    const { ctx, chartArea: area, scales: { y } } = chart;
    const cor = getComputedStyle(document.documentElement).getPropertyValue("--suave").trim() || "#888";
    ctx.save();
    TIERS.forEach((t, i) => {
      const topo = y.getPixelForValue(t.ate + 1), base = y.getPixelForValue(t.de);
      ctx.globalAlpha = i % 2 ? 0.05 : 0.11;
      ctx.fillStyle = cor;
      ctx.fillRect(area.left, topo, area.right - area.left, base - topo);
      ctx.globalAlpha = 0.8;
      ctx.font = "12px system-ui, sans-serif";
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      ctx.fillText(t.nome, area.right - 6, (topo + base) / 2);
    });
    ctx.restore();
  },
};

function conjuntos() {
  return estado.itens.map((item) => {
    const chave = `${item.conta.id}:${item.heroi.id}`;
    const s = serie(item, estado.campo, estado.modo);
    const marco = marcoTransicao(item);
    let marcoSolto = null;
    if (marco) {
      const p = s.pontos.find((pt) => pt.data === marco.data);
      if (p) p.marco = marco.rotulo;
      else if (diaZero(item).data) marcoSolto = estado.modo === "dia0" ? dias(diaZero(item).data, marco.data) : ms(marco.data);
    }
    const cor = corDe(chave);
    return {
      label: rotuloPar(chave),
      data: s.pontos,
      borderColor: cor,
      backgroundColor: cor,
      clip: 10, // marco na borda não fica cortado
      pointRadius: s.pontos.map((p) => (p.marco ? 8 : 4)),
      pointStyle: s.pontos.map((p) => (p.marco ? "rectRot" : "circle")),
      extra: { inicio: s.inicio, pontos: s.pontos, avisos: s.avisos, marco, marcoSolto },
    };
  });
}

const nomeCampo = () => ATRIBUTOS.find(([v]) => v === estado.campo)[1].toLowerCase();

function formatarX(v) {
  return estado.modo === "dia0" ? formatarDuracao(v) : dataBRDeMs(v);
}

function opcoes(dados) {
  const xs = dados.flatMap((d) => [...d.data.map((p) => p.x), ...(d.extra.inicio != null && d.data.length ? [d.extra.inicio] : [])]);
  const arvore = estado.campo === "arvore";
  return {
    responsive: true, maintainAspectRatio: false, animation: false,
    parsing: false, interaction: { mode: "nearest", intersect: false },
    scales: {
      x: {
        type: "linear",
        min: xs.length ? Math.min(...xs) : undefined,
        max: xs.length ? Math.max(...xs) : undefined,
        ticks: { callback: formatarX, maxRotation: 0, autoSkip: true, maxTicksLimit: 6, includeBounds: false },
        title: { display: true, text: estado.modo === "dia0" ? "Tempo de conta" : "Data da medição" },
      },
      // Árvore começa abaixo de 0 para o trecho "sem medições" não parecer nível 0.
      y: arvore ? { min: -12, max: 120, ticks: { stepSize: 20, callback: (v) => (v < 0 ? "" : v) } } : { beginAtZero: false },
    },
    plugins: {
      legend: { position: "bottom" },
      tooltip: {
        callbacks: {
          title: (ctx) => (ctx[0] ? `${dataBR(ctx[0].raw.data)} · ${formatarX(ctx[0].raw.x)}` : ""),
          label: (ctx) => `${ctx.dataset.label}: ${ctx.raw.y.toLocaleString("pt-BR")}`,
          afterLabel: (ctx) => ctx.raw.marco || "",
        },
      },
    },
  };
}

function desenhar() {
  const dados = conjuntos();
  const avisos = dados.flatMap((d) => [
    ...d.extra.avisos.map((a) => `${d.label}: ${a}`),
    ...(d.extra.marcoSolto != null ? [`${d.label}: ${d.extra.marco.rotulo} (sem ${nomeCampo()} medido nesse dia; losango na base)`] : []),
    ...(d.data.length ? [] : [`${d.label}: sem medições deste atributo`]),
  ]);
  $("#avisos").replaceChildren(...avisos.map((a) => el("li", {}, a)));
  const vazio = $("#vazio-grafico");
  vazio.hidden = estado.itens.length > 0;
  vazio.textContent = "Marque ao menos um herói · conta para ver o gráfico.";
  if (grafico) grafico.destroy();
  grafico = new Chart($("#canvas"), { type: "line", data: { datasets: dados }, options: opcoes(dados), plugins: [pluginTiers, pluginSemMedicoes] });
  desenharFicha();
}

// --- Ficha ---

function desenharFicha() {
  const caixa = $("#ficha");
  if (!estado.itens.length) {
    caixa.replaceChildren(el("p", { class: "suave" }, "Nada escolhido."));
    return;
  }
  const cab = el("tr", {}, el("th", { scope: "col" }, ""), ...estado.itens.map((i) => {
    const chave = `${i.conta.id}:${i.heroi.id}`;
    return el("th", { scope: "col" }, el("span", { class: "amostra", style: `background:${corDe(chave)}` }), rotuloPar(chave));
  }));
  const corpo = el("tbody");
  let grupo = null;
  for (const l of linhasFicha(estado.itens)) {
    if (l.grupo !== grupo) {
      grupo = l.grupo;
      corpo.append(el("tr", { class: "grupo" }, el("th", { colspan: estado.itens.length + 1, scope: "colgroup" }, grupo)));
    }
    corpo.append(el("tr", l.difere ? { class: "difere" } : {}, el("th", { scope: "row" }, l.rotulo), ...l.valores.map((v) => el("td", {}, v))));
  }
  caixa.replaceChildren(el("table", {}, el("thead", {}, cab), corpo));
}

// --- Início ---

async function iniciar() {
  const css = getComputedStyle(document.documentElement);
  Chart.defaults.color = css.getPropertyValue("--suave").trim();
  Chart.defaults.borderColor = css.getPropertyValue("--borda").trim();
  let medicoes;
  try {
    [contas, herois, medicoes] = await Promise.all([api.get("api/contas"), api.get("api/herois"), api.get("api/medicoes")]);
  } catch (err) {
    $("#app").replaceChildren(el("p", { class: "painel erro" }, `Erro ao carregar dados: ${err.message}`));
    return;
  }
  // Pares com medição, ordenados por herói e depois conta.
  paresComMedicao = [...new Set(medicoes.map((m) => `${m.conta_id}:${m.heroi_id}`))]
    .sort((a, b) => rotuloPar(a).localeCompare(rotuloPar(b), "pt-BR"));
  const validos = new Set(contas.flatMap((c) => herois.map((h) => `${c.id}:${h.id}`)));
  const salvo = restaurar();
  if (salvo) {
    estado.extras = (salvo.e || []).filter((k) => validos.has(k));
    estado.selecionados = (salvo.s || []).filter((k) => validos.has(k));
    if (ATRIBUTOS.some(([v]) => v === salvo.c)) estado.campo = salvo.c;
  } else if (paresComMedicao.length) {
    // Primeira visita: o primeiro herói em todas as contas em que foi medido.
    const heroi = paresComMedicao[0].split(":")[1];
    estado.selecionados = paresComMedicao.filter((k) => k.split(":")[1] === heroi);
  }
  for (const k of [...paresComMedicao, ...estado.extras]) corDe(k);
  montar();
  listarPares();
  carregar();
}

iniciar();
