// Tela 'dados': tabela + formulário gerados a partir do /api/meta.
import { api } from "./api.js";
import { el } from "./dom.js";

const EDITAVEIS = ["contas", "medicoes", "casinhas", "testes"];
const SOMENTE_LEITURA = ["herois", "habilidades", "pivos"];
const LIMITE_TEXTO = 60;

const app = document.getElementById("app");
let meta = {};
const cacheRefs = {};      // tabela referida -> linhas (buscadas uma vez por carga)
let aba = "contas";
let editando = null;       // linha em edição (null = cadastro novo)
let mensagem = null;       // {texto, erro}

async function linhasDe(tabela) {
  if (!cacheRefs[tabela]) cacheRefs[tabela] = await api.get(`api/${tabela}`);
  return cacheRefs[tabela];
}

function rotuloRef(tabela, id) {
  if (id == null || id === "") return "";
  const linha = (cacheRefs[tabela] || []).find((l) => l.id === id);
  const exibir = meta[tabela]?.exibir;
  return linha && exibir && linha[exibir] != null ? String(linha[exibir]) : `#${id}`;
}

function textoCelula(col, v) {
  if (v == null || v === "") return "";
  if (col.campo === "bool") return v ? "sim" : "não";
  if (col.campo.startsWith("ref:")) return rotuloRef(col.campo.slice(4), v);
  return String(v);
}

function celula(col, v) {
  const txt = textoCelula(col, v);
  if (txt.length <= LIMITE_TEXTO) return el("td", {}, txt);
  const td = el("td", { class: "longo", title: txt, tabindex: "0" }, txt.slice(0, LIMITE_TEXTO) + "…");
  let aberto = false;
  const alternar = () => {
    aberto = !aberto;
    td.textContent = aberto ? txt : txt.slice(0, LIMITE_TEXTO) + "…";
    td.classList.toggle("aberto", aberto);
  };
  td.addEventListener("click", alternar);
  td.addEventListener("keydown", (e) => { if (e.key === "Enter") alternar(); });
  return td;
}

async function campoForm(col, valor) {
  const nome = `f_${col.nome}`;
  const rotulo = el("label", { for: nome }, col.rotulo);
  let controle;
  if (col.campo === "textarea") {
    controle = el("textarea", { id: nome, name: col.nome, rows: "3" });
    controle.value = valor ?? "";
  } else if (col.campo === "bool") {
    controle = el("input", { id: nome, name: col.nome, type: "checkbox" });
    controle.checked = !!valor;
    return el("div", { class: "campo campo-bool" }, controle, rotulo);
  } else if (col.campo.startsWith("select:") || col.campo.startsWith("ref:")) {
    controle = el("select", { id: nome, name: col.nome }, el("option", { value: "" }, "—"));
    let opcoes;
    if (col.campo.startsWith("ref:")) {
      const t = col.campo.slice(4);
      await linhasDe(t);
      opcoes = cacheRefs[t].map((l) => [String(l.id), rotuloRef(t, l.id)]);
    } else {
      opcoes = col.campo.slice(7).split(",").map((o) => [o, o]);
    }
    for (const [v, t] of opcoes) controle.append(el("option", { value: v }, t));
    controle.value = valor == null ? "" : String(valor);
  } else {
    const tipo = col.campo === "number" ? "number" : col.campo === "date" ? "date" : "text";
    controle = el("input", { id: nome, name: col.nome, type: tipo });
    if (tipo === "number") controle.step = "any";
    controle.value = valor ?? "";
  }
  return el("div", { class: "campo" }, rotulo, controle);
}

function lerForm(form, colunas) {
  const dados = {};
  for (const col of colunas) {
    const c = form.elements[col.nome];
    if (col.campo === "bool") dados[col.nome] = c.checked ? 1 : 0;
    else if (col.campo === "number") dados[col.nome] = c.value === "" ? "" : Number(c.value);
    else if (col.campo.startsWith("ref:")) dados[col.nome] = c.value === "" ? "" : Number(c.value);
    else dados[col.nome] = c.value;
  }
  return dados;
}

async function montarForm(tabela) {
  const colunas = meta[tabela].colunas;
  const form = el("form", { class: "form-dados" });
  const campos = el("div", { class: "campos" });
  for (const col of colunas) campos.append(await campoForm(col, editando?.[col.nome]));
  const aviso = el("p", { class: "erro", role: "alert" });
  const botoes = el("div", { class: "linha-form" },
    el("button", { type: "submit" }, editando ? "Salvar alterações" : "Cadastrar"));
  if (editando) {
    botoes.append(el("button", { type: "button", class: "secundario", onclick: () => { editando = null; mensagem = null; desenhar(); } }, "Cancelar edição"));
  }
  form.append(campos, aviso, botoes);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    aviso.textContent = "";
    try {
      const dados = lerForm(form, colunas);
      if (editando) await api.put(`api/${tabela}/${editando.id}`, dados);
      else await api.post(`api/${tabela}`, dados);
      mensagem = { texto: editando ? "Alterações salvas." : "Cadastrado.", erro: false };
      editando = null;
      delete cacheRefs[tabela];
      await desenhar();
    } catch (err) {
      aviso.textContent = err.message;
    }
  });
  return form;
}

async function apagar(tabela, linha) {
  if (!confirm(`Apagar o registro #${linha.id} de "${meta[tabela].rotulo}"? Não dá para desfazer.`)) return;
  try {
    await api.del(`api/${tabela}/${linha.id}`);
    mensagem = { texto: "Registro apagado.", erro: false };
    delete cacheRefs[tabela];
    if (editando?.id === linha.id) editando = null;
  } catch (err) {
    mensagem = { texto: err.message, erro: true };
  }
  await desenhar();
}

function tabelaDe(tabela, linhas) {
  const colunas = meta[tabela].colunas;
  const editavel = EDITAVEIS.includes(tabela);
  const cab = el("tr", {}, ...colunas.map((c) => el("th", { scope: "col" }, c.rotulo)));
  if (editavel) cab.append(el("th", { scope: "col" }, "Ações"));
  const corpo = el("tbody");
  for (const l of linhas) {
    const tr = el("tr", {}, ...colunas.map((c) => celula(c, l[c.nome])));
    if (editavel) {
      const acoes = el("td", { class: "acoes" });
      if (tabela === "medicoes") {
        acoes.append(el("a", { href: `sessao?editar=${l.id}` }, "Editar"));
      } else {
        acoes.append(el("button", { type: "button", class: "secundario", onclick: () => { editando = l; mensagem = null; desenhar(); } }, "Editar"));
      }
      acoes.append(" ", el("button", { type: "button", class: "secundario perigo", onclick: () => apagar(tabela, l) }, "Apagar"));
      tr.append(acoes);
    }
    corpo.append(tr);
  }
  if (!linhas.length) corpo.append(el("tr", {}, el("td", { colspan: String(colunas.length + 1), class: "suave" }, "Nenhum registro.")));
  return el("div", { class: "rolagem" }, el("table", { class: "tabela-dados" }, el("thead", {}, cab), corpo));
}

async function importar(entrada, saida) {
  const arquivo = entrada.files[0];
  if (!arquivo) return;
  saida.className = "suave";
  saida.textContent = "Importando…";
  try {
    const corpo = new FormData();
    corpo.append("arquivo", arquivo);
    const resp = await fetch("api/importar/catalogo", { method: "POST", body: corpo });
    const json = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const d = json.detail;
      throw new Error(d ? (typeof d === "string" ? d : JSON.stringify(d)) : `Erro ${resp.status}`);
    }
    saida.className = "ok";
    saida.textContent = `Importado: ${json.novos} novos, ${json.atualizados} atualizados.`;
    for (const k of Object.keys(cacheRefs)) delete cacheRefs[k];
    entrada.value = "";
    await desenhar(saida.textContent);
  } catch (err) {
    saida.className = "erro";
    saida.textContent = err.message;
  }
}

async function desenhar(textoImport) {
  const tabela = aba;
  const abas = el("div", { class: "abas", role: "tablist" });
  for (const t of [...EDITAVEIS, ...SOMENTE_LEITURA]) {
    const b = el("button", { type: "button", role: "tab", class: "aba", "aria-pressed": String(t === tabela),
      onclick: () => { aba = t; editando = null; mensagem = null; desenhar(); } }, meta[t].rotulo);
    abas.append(b);
  }
  const painel = el("section", { class: "painel dados" }, el("h2", {}, meta[tabela].rotulo), abas);
  if (mensagem) painel.append(el("p", { class: mensagem.erro ? "erro" : "ok", role: "status" }, mensagem.texto));
  try {
    const linhas = await linhasDe(tabela);
    for (const col of meta[tabela].colunas) {
      if (col.campo.startsWith("ref:")) await linhasDe(col.campo.slice(4));
    }
    if (aba !== tabela) return;  // trocou de aba durante a carga
    if (EDITAVEIS.includes(tabela)) {
      painel.append(el("h3", {}, editando ? `Editando #${editando.id}` : "Cadastrar novo"));
      if (tabela === "medicoes" && !editando) {
        painel.append(el("p", { class: "suave" }, "Para várias medições de uma vez, use a tela ", el("a", { href: "sessao" }, "Nova sessão"), "."));
      }
      painel.append(await montarForm(tabela));
    } else {
      painel.append(el("p", { class: "suave" }, "Catálogo somente leitura."));
    }
    if (tabela === "herois") {
      const entrada = el("input", { type: "file", accept: ".json,application/json" });
      const saida = el("span", { role: "status" }, textoImport || "");
      if (textoImport) saida.className = "ok";
      const botao = el("button", { type: "button", onclick: () => entrada.files[0] ? importar(entrada, saida) : entrada.click() }, "Importar catálogo");
      entrada.addEventListener("change", () => importar(entrada, saida));
      painel.append(el("div", { class: "linha-form" }, botao, entrada, saida));
    }
    painel.append(el("p", { class: "suave" }, `${linhas.length} registro(s).`), tabelaDe(tabela, linhas));
  } catch (err) {
    painel.append(el("p", { class: "erro", role: "alert" }, err.message));
  }
  app.replaceChildren(painel);
}

async function iniciar() {
  try {
    meta = await api.get("api/meta");
    await desenhar();
  } catch (err) {
    app.replaceChildren(el("p", { class: "erro", role: "alert" }, `Não foi possível carregar: ${err.message}`));
  }
}
iniciar();
