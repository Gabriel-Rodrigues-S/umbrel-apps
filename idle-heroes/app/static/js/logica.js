// Lógica pura da interface (sem DOM, sem Chart): importável pelo Node nos testes.

const DIA_MS = 86400000;

// Tiers da árvore: nível mínimo e máximo de cada um.
export const TIERS = [
  { nome: "T1", de: 20, ate: 39 },
  { nome: "T2", de: 40, ate: 59 },
  { nome: "T3", de: 60, ate: 79 },
  { nome: "T4", de: 80, ate: 99 },
  { nome: "T5", de: 100, ate: 120 },
];

const AVISO_DESCONHECIDA = "Data de criação da conta desconhecida: dia 0 = primeira medição";
const AVISO_ANTERIOR = "Há medição anterior à data de criação da conta";
const AVISO_APROXIMADA = "Data de criação da conta aproximada: dia 0 estimado";

// "AAAA-MM-DD" -> ms (UTC), sem depender do fuso.
export function ms(data) {
  const [a, m, d] = data.split("-").map(Number);
  return Date.UTC(a, m - 1, d);
}

export function dias(de, ate) {
  return Math.round((ms(ate) - ms(de)) / DIA_MS);
}

// "AAAA-MM-DD" -> "dd/mm/aaaa".
export function dataBR(data) {
  const [a, m, d] = data.split("-");
  return `${d}/${m}/${a}`;
}

// ms (UTC) -> "dd/mm/aaaa".
export function dataBRDeMs(valor) {
  return dataBR(new Date(valor).toISOString().slice(0, 10));
}

// Ano = 365 dias, mês = 30 dias; negativo ganha "-" na frente.
export function formatarDuracao(n) {
  if (n < 0) return "-" + formatarDuracao(-n);
  n = Math.round(n);
  const anos = Math.floor(n / 365);
  const meses = Math.floor((n % 365) / 30);
  const partes = [];
  if (anos) partes.push(anos === 1 ? "1 ano" : `${anos} anos`);
  if (meses) partes.push(meses === 1 ? "1 mês" : `${meses} meses`);
  if (!partes.length) return n === 1 ? "1 dia" : `${n} dias`;
  return partes.join(" e ");
}

export function tier(nivel) {
  if (nivel == null || nivel < 20) return null;
  return `T${Math.min(Math.floor(nivel / 20), 5)}`;
}

export function diaZero(item) {
  if (item.conta && item.conta.criada_em) {
    return { data: item.conta.criada_em, origem: "conta", aproximada: !!item.conta.criada_em_aproximada };
  }
  if (item.medicoes && item.medicoes.length) {
    return { data: item.medicoes[0].data, origem: "primeira_medicao", aproximada: false };
  }
  return { data: null, origem: null, aproximada: false };
}

// Pontos só das medições com o campo preenchido; nunca inventa valor.
export function serie(item, campo, modo) {
  const zero = diaZero(item);
  const avisos = [];
  const pontos = [];
  for (const m of item.medicoes || []) {
    if (m[campo] == null) continue;
    const x = modo === "dia0" ? dias(zero.data, m.data) : ms(m.data);
    pontos.push({ x, y: m[campo], data: m.data });
  }
  // Datas reais: cada linha começa na primeira medição (sem trecho nem avisos de dia 0).
  const inicio = modo === "dia0" && zero.data ? 0 : null;
  if (modo === "dia0") {
    if (zero.origem === "primeira_medicao") avisos.push(AVISO_DESCONHECIDA);
    if (zero.aproximada) avisos.push(AVISO_APROXIMADA);
    if (zero.origem === "conta" && pontos.some((p) => p.x < 0)) avisos.push(AVISO_ANTERIOR);
  }
  return { pontos, inicio, avisos };
}

export function marcoTransicao(item) {
  const medicoes = item.medicoes || [];
  const comData = medicoes.find((m) => m.transicao_em);
  if (comData) return { data: comData.transicao_em, rotulo: `Transição em ${dataBR(comData.transicao_em)}` };
  const i = medicoes.findIndex((m) => m.transicao == 1);
  if (i < 0) return null;
  const data = medicoes[i].data;
  const antesNao = medicoes.slice(0, i).some((m) => m.transicao === 0);
  return { data, rotulo: antesNao ? "Transição" : `Transição já desbloqueada em ${dataBR(data)}` };
}

const VAZIO = "—";
const ddmm = (data) => dataBR(data).slice(0, 5);
const milhar = (v) => String(v).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
const texto = (v) => (v == null || v === "" ? VAZIO : String(v));
const RESSONANCIA = { todas: "todas as peças", parcial: "parcial", nenhuma: "nenhuma" };

function numero(item, campo) {
  const u = item.ultimo_numero && item.ultimo_numero[campo];
  if (!u) return VAZIO;
  const sufixo = u.data !== item.ultima.data ? ` (${ddmm(u.data)})` : "";
  return milhar(u.valor) + sufixo;
}

function arvore(nivel) {
  if (nivel == null) return VAZIO;
  if (nivel === 0) return "sem árvore";
  const t = tier(nivel);
  return t ? `${nivel} (${t})` : String(nivel);
}

function transicao(m) {
  if (m.transicao == null) return VAZIO;
  if (m.transicao == 0) return "não";
  return m.transicao_em ? `sim (em ${dataBR(m.transicao_em)})` : "sim";
}

function tempoDeConta(item) {
  const zero = diaZero(item);
  if (zero.origem !== "conta") return "data da conta desconhecida";
  return (zero.aproximada ? "~" : "") + formatarDuracao(dias(zero.data, item.ultima.data));
}

function inquilinos(casinhas) {
  if (!casinhas || !casinhas.length) return VAZIO;
  return casinhas
    .map((c) => (c.inquilino ? c.inquilino + (c.transferencia_pct != null ? ` (${c.transferencia_pct}%)` : "") : VAZIO))
    .join(", ");
}

// Grupos e linhas da ficha; cada linha: (item) -> texto.
const FICHA = [
  ["Números", [
    ["Poder", (i) => numero(i, "poder")],
    ["Ataque", (i) => numero(i, "ataque")],
    ["HP", (i) => numero(i, "hp")],
    ["Armadura", (i) => numero(i, "armadura")],
    ["Velocidade", (i) => numero(i, "velocidade")],
  ]],
  ["Progresso", [
    ["Transição do Destino", (i) => transicao(i.ultima)],
    ["Árvore", (i) => arvore(i.ultima.arvore)],
    ["Núcleo de origem", (i) => texto(i.ultima.nucleo)],
    ["Sublimação", (i) => texto(i.ultima.sublimacao)],
    ["Grimório", (i) => texto(i.ultima.grimorio)],
  ]],
  ["Equipamento", [
    ["Equipamento", (i) => texto(i.ultima.equipamento)],
    ["Estrelas", (i) => texto(i.ultima.equip_estrelas)],
    ["Ressonância", (i) => texto(RESSONANCIA[i.ultima.equip_ressonancia] ?? i.ultima.equip_ressonancia)],
    ["Artefato", (i) => texto(i.ultima.artefato)],
  ]],
  ["Casinhas", [
    ["Quantidade", (i) => String((i.casinhas || []).length)],
    ["Inquilinos", (i) => inquilinos(i.casinhas)],
  ]],
  ["Tempo", [
    ["Medido em", (i) => dataBR(i.ultima.data)],
    ["Tempo de conta", tempoDeConta],
  ]],
];

export function linhasFicha(itens) {
  const linhas = [];
  for (const [grupo, campos] of FICHA) {
    for (const [rotulo, valor] of campos) {
      const valores = itens.map((i) => (i.ultima ? valor(i) : "sem medições"));
      linhas.push({ grupo, rotulo, valores, difere: itens.length > 1 && new Set(valores).size > 1 });
    }
  }
  return linhas;
}

// Mesmas listas de app/db.py: números são da data medida; estado vale até mudar.
export const NUMEROS = ["poder", "ataque", "hp", "armadura", "velocidade"];
export const ESTADO = ["transicao", "transicao_em", "arvore", "nucleo", "sublimacao", "grimorio",
  "equipamento", "equip_estrelas", "equip_ressonancia", "artefato"];

const vazio = (v) => v == null || v === "";

// Estado herdado da última medição; números dela só viram dica (placeholder).
export function preencher(ultima) {
  const valores = {}, dicas = {};
  if (!ultima) return { valores, dicas };
  for (const c of ESTADO) valores[c] = ultima[c] ?? null;
  for (const c of NUMEROS) dicas[c] = ultima[c] ?? null;
  return { valores, dicas };
}

// Item do POST /api/sessao: estado sempre; número só se digitado; limpo vira null.
export function montarItem(heroi_id, valores, editados, limpos) {
  const item = { heroi_id };
  for (const c of ESTADO) if (!vazio(valores[c])) item[c] = valores[c];
  // Número mexido à mão e esvaziado apaga o gravado (null); intocado não entra.
  for (const c of NUMEROS) if (editados.has(c)) item[c] = vazio(valores[c]) ? null : valores[c];
  for (const c of limpos) item[c] = null;
  return item;
}
