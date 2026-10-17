// Tela 'sessao': várias medições (heróis de uma conta) numa data só.
import { api } from "./api.js";
import { el } from "./dom.js";
import { preencher, montarItem, NUMEROS, dataBR } from "./logica.js";

const GRUPOS = [
  ["Números (só o que você digitar)", NUMEROS],
  ["Progresso", ["transicao", "transicao_em", "arvore", "nucleo", "sublimacao", "grimorio"]],
  ["Equipamento", ["equipamento", "equip_estrelas", "equip_ressonancia", "artefato"]],
  ["Notas (não herdadas)", ["notas"]],
];

const hoje = () => {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
};

const estado = { conta: null, data: hoje(), ids: [], cartoes: new Map() };
let contas = [], herois = [], colunas = {}, medicoes = [], pedido = 0, edicao = null;

const $ = (sel) => document.querySelector(sel);
const nomeDe = (lista, id) => (lista.find((x) => x.id === id) || {}).nome || `#${id}`;

function msg(texto, erro = false) {
  $("#resultado").replaceChildren(el("p", { class: erro ? "erro" : "ok", role: erro ? "alert" : "status" }, texto));
}

function montar() {
  $("#app").replaceChildren(
    el("section", { class: "painel sessao-escolha", "aria-labelledby": "t-esc" },
      el("h2", { id: "t-esc" }, "Sessão"),
      el("div", { class: "linha-form" },
        el("label", {}, "Conta", el("select", { id: "conta", onchange: (e) => { estado.conta = Number(e.target.value); trocarConta(); } })),
        el("label", {}, "Data", el("input", { id: "data", type: "date", onchange: (e) => { estado.data = e.target.value; atualizar(); } }))),
      el("h3", {}, "Heróis"),
      el("div", { id: "lista-herois", class: "lista-pares" }),
      el("details", { class: "adicionar" },
        el("summary", {}, "Adicionar outro herói"),
        el("div", { class: "linha-form" },
          el("label", {}, "Herói", el("select", { id: "add-heroi" })),
          el("button", { type: "button", onclick: adicionar }, "Adicionar")))),
    el("section", { class: "painel sessao-cartoes", "aria-labelledby": "t-car" },
      el("h2", { id: "t-car" }, "Medições da sessão"),
      el("div", { id: "cartoes" }),
      el("div", { class: "barra-salvar" },
        el("button", { type: "button", id: "salvar", onclick: salvar }, "Salvar sessão"),
        el("div", { id: "resultado" }))),
  );
  $("#conta").append(...contas.map((c) => el("option", { value: c.id }, c.nome)));
  $("#add-heroi").append(...herois.map((h) => el("option", { value: h.id }, h.nome)));
  $("#conta").value = estado.conta ?? "";
  $("#data").value = estado.data;
}

// Heróis com medição na conta, depois os adicionados à mão.
function candidatos() {
  const com = [...new Set(medicoes.filter((m) => m.conta_id === estado.conta).map((m) => m.heroi_id))];
  const todos = [...com, ...estado.ids.filter((id) => !com.includes(id))];
  return todos.sort((a, b) => nomeDe(herois, a).localeCompare(nomeDe(herois, b), "pt-BR"));
}

function listarHerois() {
  const lista = candidatos();
  $("#lista-herois").replaceChildren(...(lista.length
    ? lista.map((id) => {
      const cb = el("input", { type: "checkbox", value: id, onchange: alternar });
      cb.checked = estado.cartoes.has(id);
      return el("label", { class: "par" }, cb, nomeDe(herois, id));
    })
    : [el("p", { class: "suave" }, "Nenhum herói com medição nesta conta: adicione um abaixo.")]));
}

function alternar(e) {
  const id = Number(e.target.value);
  if (e.target.checked) estado.cartoes.set(id, novoCartao());
  else estado.cartoes.delete(id);
  carregar();
}

function adicionar() {
  const id = Number($("#add-heroi").value);
  if (!id) return;
  if (!estado.ids.includes(id)) estado.ids.push(id);
  if (!estado.cartoes.has(id)) estado.cartoes.set(id, novoCartao());
  listarHerois();
  carregar();
}

function trocarConta() {
  estado.cartoes.clear();
  estado.ids = [];
  listarHerois();
  carregar();
}

function atualizar() {
  for (const c of estado.cartoes.values()) rebase(c);
  desenharCartoes();
}

// --- Dados ---

function novoCartao() {
  return { itens: null, base: null, existente: null, valores: {}, dicas: {}, tocados: new Set(), editados: new Set(), limpos: new Set() };
}

// Última medição até a data escolhida é a base da herança; a da própria data, se houver, é a existente.
function rebase(c) {
  const meds = (c.itens && c.itens.medicoes) || [];
  const ate = meds.filter((m) => m.data <= estado.data);
  c.base = ate.length ? ate[ate.length - 1] : null;
  c.existente = meds.find((m) => m.data === estado.data) || null;
  const { valores, dicas } = preencher(c.base);
  c.dicas = dicas;
  // O que a pessoa mexeu fica; o resto acompanha a herança.
  for (const k of Object.keys(c.valores)) if (!c.tocados.has(k)) delete c.valores[k];
  for (const [k, v] of Object.entries(valores)) if (!c.tocados.has(k)) c.valores[k] = v;
}

// propagar: quem chama trata o erro (senão a mensagem de erro é mostrada aqui).
async function carregar(propagar = false) {
  const n = ++pedido;
  const ids = [...estado.cartoes.keys()];
  if (ids.length) {
    try {
      const itens = await api.get(`api/comparacao?pares=${ids.map((h) => `${estado.conta}:${h}`).join(",")}`);
      if (n !== pedido) return;
      for (const it of itens) {
        const c = estado.cartoes.get(it.heroi.id);
        if (c) { c.itens = it; rebase(c); }
      }
    } catch (err) {
      if (propagar) throw err;
      if (n === pedido) msg(`Erro ao carregar: ${err.message}`, true);
      return;
    }
  }
  desenharCartoes();
}

// --- Cartões ---

function dicaDe(c, nome) {
  return c.dicas[nome] != null ? `última: ${c.dicas[nome]}` : "";
}

function campoEntrada(c, nome) {
  const col = colunas[nome];
  const tipo = col.campo;
  const mudou = (e) => {
    c.tocados.add(nome);
    if (NUMEROS.includes(nome)) c.editados.add(nome);
    const bruto = e.target.value;
    // Esvaziar à mão apaga o valor gravado (null); preencher de novo desfaz.
    if (bruto === "") c.limpos.add(nome); else c.limpos.delete(nome);
    c.valores[nome] = bruto === "" ? null
      : (tipo === "number" || tipo === "bool") ? Number(bruto) : bruto;
    e.target.classList.toggle("limpo", bruto === "");
    if (bruto !== "") e.target.setAttribute("placeholder", dicaDe(c, nome));
    else e.target.setAttribute("placeholder", "será apagado");
  };
  const atual = c.valores[nome];
  const texto = atual == null ? "" : String(atual);
  let entrada;
  if (tipo === "bool") {
    entrada = el("select", { onchange: mudou }, el("option", { value: "" }, "—"), el("option", { value: "0" }, "não"), el("option", { value: "1" }, "sim"));
  } else if (tipo.startsWith("select:")) {
    entrada = el("select", { onchange: mudou }, el("option", { value: "" }, "—"),
      ...tipo.slice(7).split(",").map((o) => el("option", { value: o }, o)));
  } else if (tipo === "textarea") {
    entrada = el("textarea", { rows: "2", oninput: mudou });
  } else {
    entrada = el("input", { type: tipo === "number" ? "number" : tipo === "date" ? "date" : "text", oninput: mudou });
    const dica = c.dicas[nome];
    if (dica != null) entrada.setAttribute("placeholder", `última: ${dica}`);
  }
  entrada.value = texto;
  if (c.limpos.has(nome)) { entrada.classList.add("limpo"); entrada.setAttribute("placeholder", "será apagado"); }
  const limpar = el("button", { type: "button", class: "secundario", "aria-label": `Limpar ${col.rotulo}`, onclick: () => {
    c.tocados.add(nome);
    c.limpos.add(nome);
    c.valores[nome] = null;
    entrada.value = "";
    entrada.classList.add("limpo");
    entrada.setAttribute("placeholder", "será apagado");
  } }, "limpar");
  return el("div", { class: "campo" }, el("label", {}, col.rotulo, entrada), limpar);
}

function cartao(id, c) {
  const aviso = c.existente
    ? el("p", { class: "aviso" }, `Já existe medição deste herói nesta data (${dataBR(estado.data)}) — salvar vai atualizar`)
    : null;
  const base = c.base
    ? el("p", { class: "suave" }, `Estado herdado da medição de ${dataBR(c.base.data)}`)
    : el("p", { class: "suave" }, "Sem medição anterior: nada herdado");
  return el("article", { class: "cartao-heroi" },
    el("h3", {}, nomeDe(herois, id)),
    aviso, base,
    ...GRUPOS.map(([titulo, nomes]) => el("fieldset", {},
      el("legend", {}, titulo),
      el("div", { class: "campos" }, ...nomes.filter((n) => colunas[n]).map((n) => campoEntrada(c, n))))));
}

function desenharCartoes() {
  const caixa = $("#cartoes");
  if (!estado.cartoes.size) {
    caixa.replaceChildren(el("p", { class: "suave" }, "Marque os heróis medidos nesta sessão."));
    return;
  }
  caixa.replaceChildren(...[...estado.cartoes].map(([id, c]) => cartao(id, c)));
}

// --- Salvar ---

async function salvar() {
  if (!estado.conta || !estado.data) return msg("Escolha a conta e a data.", true);
  if (!estado.cartoes.size) return msg("Marque ao menos um herói.", true);
  const herois_ = [...estado.cartoes].map(([id, c]) => {
    const item = montarItem(id, c.valores, c.editados, c.limpos);
    const nota = c.valores.notas;
    if (nota != null && nota !== "" && !c.limpos.has("notas")) item.notas = nota;
    return item;
  });
  const botao = $("#salvar");
  botao.disabled = true;
  try {
    const r = await api.post("api/sessao", { conta_id: estado.conta, data: estado.data, herois: herois_ });
    const c = r.criadas.length, a = r.atualizadas.length;
    msg(`Sessão salva: ${c} ${c === 1 ? "criada" : "criadas"}, ${a} ${a === 1 ? "atualizada" : "atualizadas"}.`);
    // Gravou: a partir daqui erro de recarga não pode virar "Não salvou".
    try {
      medicoes = await api.get("api/medicoes");
      for (const x of estado.cartoes.values()) { x.tocados.clear(); x.editados.clear(); x.limpos.clear(); x.valores = {}; }
      listarHerois();
      await carregar(true);
    } catch (err) {
      msg(`Sessão salva (${c} ${c === 1 ? "criada" : "criadas"}, ${a} ${a === 1 ? "atualizada" : "atualizadas"}), mas não consegui recarregar a tela: ${err.message}`, true);
    }
  } catch (err) {
    msg(`Não salvou: ${err.message}`, true);
  } finally {
    botao.disabled = false;
  }
}

// --- Início ---

async function iniciar() {
  try {
    const [meta, c, h, m] = await Promise.all([
      api.get("api/meta"), api.get("api/contas"), api.get("api/herois"), api.get("api/medicoes"),
    ]);
    colunas = Object.fromEntries(meta.medicoes.colunas.map((x) => [x.nome, x]));
    contas = c; herois = h; medicoes = m;
    const editar = new URLSearchParams(location.search).get("editar");
    if (editar) {
      edicao = await api.get(`api/medicoes/${encodeURIComponent(editar)}`);
      estado.conta = edicao.conta_id;
      estado.data = edicao.data;
      estado.ids = [edicao.heroi_id];
      const card = novoCartao();
      // Corrigir: os números da própria medição vêm como valores, não só dicas.
      for (const k of [...NUMEROS, "notas"]) if (edicao[k] != null) { card.valores[k] = edicao[k]; card.tocados.add(k); if (NUMEROS.includes(k)) card.editados.add(k); }
      estado.cartoes.set(edicao.heroi_id, card);
    } else {
      estado.conta = contas.length ? contas[0].id : null;
    }
    montar();
    listarHerois();
    if (edicao) msg(`Corrigindo a medição #${edicao.id}: ${nomeDe(herois, edicao.heroi_id)} em ${dataBR(edicao.data)}.`);
    await carregar();
  } catch (err) {
    $("#app").replaceChildren(el("p", { class: "erro" }, `Erro ao carregar: ${err.message}`));
  }
}

iniciar();
