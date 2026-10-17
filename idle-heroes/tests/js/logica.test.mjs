// Testes das funções puras da tela de comparação (dados inventados).
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  dias, formatarDuracao, diaZero, faixaX, serie, marcoTransicao, linhasFicha, preencher, montarItem, NUMEROS, ESTADO,
} from "../../app/static/js/logica.js";

const NUMS = ["poder", "ataque", "hp", "armadura", "velocidade"];

// Monta uma medição com todos os campos vazios, exceto os informados.
function med(data, campos = {}) {
  const m = {
    conta_id: 1, heroi_id: 1, data, transicao: null, transicao_em: null, arvore: null,
    nucleo: null, sublimacao: null, grimorio: null, equipamento: null, equip_estrelas: null,
    equip_ressonancia: null, artefato: null, notas: null,
  };
  for (const c of NUMS) m[c] = null;
  return { ...m, ...campos };
}

// Monta um item no formato de /api/comparacao.
function item({ conta = {}, heroi = "Heroi A", medicoes = [], casinhas = [] } = {}) {
  const ultimo_numero = Object.fromEntries(NUMS.map((c) => [c, null]));
  for (const m of medicoes) for (const c of NUMS) if (m[c] != null) ultimo_numero[c] = { valor: m[c], data: m.data };
  return {
    conta: { id: 1, nome: "Conta X", criada_em: null, criada_em_aproximada: null, ...conta },
    heroi: { id: 1, nome: heroi },
    medicoes,
    ultima: medicoes.length ? medicoes[medicoes.length - 1] : null,
    ultimo_numero,
    casinhas,
  };
}

const linha = (linhas, rotulo) => linhas.find((l) => l.rotulo === rotulo);

test("dias entre datas", () => {
  assert.equal(dias("2022-08-11", "2026-10-17"), 1528);
  assert.equal(dias("2026-10-17", "2026-10-08"), -9);
});

test("formatarDuracao", () => {
  assert.equal(formatarDuracao(0), "0 dias");
  assert.equal(formatarDuracao(45), "1 mês");
  assert.equal(formatarDuracao(400), "1 ano e 1 mês");
  assert.equal(formatarDuracao(1528), "4 anos e 2 meses");
});

test("diaZero: conta, primeira medição, sem medições", () => {
  const c = item({ conta: { criada_em: "2022-08-11", criada_em_aproximada: 1 }, medicoes: [med("2026-10-08")] });
  assert.deepEqual(diaZero(c), { data: "2022-08-11", origem: "conta", aproximada: true });
  const p = item({ medicoes: [med("2026-10-08"), med("2026-10-17")] });
  assert.deepEqual(diaZero(p), { data: "2026-10-08", origem: "primeira_medicao", aproximada: false });
  assert.equal(diaZero(item()).data, null);
});

test("serie: medição com poder nulo não vira ponto", () => {
  const s = serie(item({ medicoes: [med("2026-10-08", { poder: 100 }), med("2026-10-17", { arvore: 37 })] }), "poder", "datas");
  assert.equal(s.pontos.length, 1);
  assert.equal(s.pontos[0].y, 100);
  assert.equal(s.pontos[0].x, Date.UTC(2026, 9, 8));
  assert.equal(s.pontos[0].data, "2026-10-08");
});

test("serie dia0 sem criada_em: começa em 0 e avisa", () => {
  const s = serie(item({ medicoes: [med("2026-10-08", { poder: 100 }), med("2026-10-18", { poder: 150 })] }), "poder", "dia0");
  assert.equal(s.pontos[0].x, 0);
  assert.equal(s.pontos[1].x, 10);
  assert.equal(s.inicio, 0);
  assert.ok(s.avisos.includes("Data de criação da conta desconhecida: dia 0 = primeira medição"));
});

test("serie dia0 com criada_em: início antes do primeiro ponto", () => {
  const s = serie(item({ conta: { criada_em: "2026-10-01" }, medicoes: [med("2026-10-08", { poder: 100 })] }), "poder", "dia0");
  assert.equal(s.inicio, 0);
  assert.equal(s.pontos[0].x, 7);
  assert.deepEqual(s.avisos, []);
  const d = serie(item({ conta: { criada_em: "2026-10-01" }, medicoes: [med("2026-10-08", { poder: 100 })] }), "poder", "datas");
  assert.equal(d.inicio, null);
});

test("serie datas: sem trecho e sem avisos de data da conta", () => {
  const meds = [med("2026-10-08", { poder: 100 }), med("2026-10-18", { poder: 150 })];
  const desc = serie(item({ medicoes: meds }), "poder", "datas");
  assert.equal(desc.inicio, null);
  assert.deepEqual(desc.avisos, []);
  const ap = serie(item({ conta: { criada_em: "2026-10-01", criada_em_aproximada: 1 }, medicoes: meds }), "poder", "datas");
  assert.equal(ap.inicio, null);
  assert.deepEqual(ap.avisos, []);
  const ant = serie(item({ conta: { criada_em: "2026-10-17" }, medicoes: meds }), "poder", "datas");
  assert.deepEqual(ant.avisos, []);
});

test("serie dia0: aviso de data aproximada", () => {
  const s = serie(item({ conta: { criada_em: "2026-10-01", criada_em_aproximada: 1 }, medicoes: [med("2026-10-08", { poder: 100 })] }), "poder", "dia0");
  assert.ok(s.avisos.includes("Data de criação da conta aproximada: dia 0 estimado"));
});

test("serie: medição antes de criada_em fica negativa e avisa", () => {
  const s = serie(item({ conta: { criada_em: "2026-10-17" }, medicoes: [med("2026-10-08", { poder: 100 })] }), "poder", "dia0");
  assert.equal(s.pontos[0].x, -9);
  assert.ok(s.avisos.includes("Há medição anterior à data de criação da conta"));
});

test("marcoTransicao: já desbloqueada desde a primeira medição", () => {
  const m = marcoTransicao(item({ medicoes: [med("2026-10-08", { transicao: 1 }), med("2026-10-17", { transicao: 1 })] }));
  assert.equal(m.data, "2026-10-08");
  assert.ok(m.rotulo.startsWith("Transição já desbloqueada em"));
  assert.equal(m.rotulo, "Transição já desbloqueada em 08/10/2026");
});

test("marcoTransicao: não e depois sim", () => {
  const m = marcoTransicao(item({ medicoes: [med("2026-10-08", { transicao: 0 }), med("2026-10-17", { transicao: 1 })] }));
  assert.deepEqual(m, { data: "2026-10-17", rotulo: "Transição" });
});

test("marcoTransicao: usa transicao_em quando existe", () => {
  const m = marcoTransicao(item({ medicoes: [med("2026-10-08", { transicao: 0 }), med("2026-10-17", { transicao: 1, transicao_em: "2026-10-12" })] }));
  assert.deepEqual(m, { data: "2026-10-12", rotulo: "Transição em 12/10/2026" });
  assert.equal(marcoTransicao(item({ medicoes: [med("2026-10-08", { transicao: 0 })] })), null);
  assert.equal(marcoTransicao(item()), null);
});

test("linhasFicha: árvore com tier e destaque", () => {
  const a = item({ medicoes: [med("2026-10-17", { arvore: 61 })] });
  const b = item({ conta: { id: 2, nome: "Conta Y" }, medicoes: [med("2026-10-17", { arvore: 37 })] });
  const l = linha(linhasFicha([a, b]), "Árvore");
  assert.deepEqual(l.valores, ["61 (T3)", "37 (T1)"]);
  assert.equal(l.difere, true);
  assert.equal(l.grupo, "Progresso");
  const sem = linha(linhasFicha([item({ medicoes: [med("2026-10-17", { arvore: 0 })] })]), "Árvore");
  assert.deepEqual(sem.valores, ["sem árvore"]);
});

test("linhasFicha: grupos na ordem do spec", () => {
  const grupos = [...new Set(linhasFicha([item({ medicoes: [med("2026-10-17")] })]).map((l) => l.grupo))];
  assert.deepEqual(grupos, ["Números", "Progresso", "Equipamento", "Casinhas", "Tempo"]);
});

test("linhasFicha: número de data anterior mostra a data", () => {
  const i = item({ medicoes: [med("2026-10-08", { poder: 100 }), med("2026-10-17", { arvore: 37 })] });
  const l = linhasFicha([i]);
  assert.ok(linha(l, "Poder").valores[0].endsWith(" (08/10)"));
  assert.equal(linha(l, "Ataque").valores[0], "—");
  assert.equal(linha(l, "Medido em").valores[0], "17/10/2026");
});

test("linhasFicha: tempo de conta aproximado e desconhecido", () => {
  const ap = item({ conta: { criada_em: "2022-08-11", criada_em_aproximada: 1 }, medicoes: [med("2026-10-17")] });
  const t = linha(linhasFicha([ap]), "Tempo de conta").valores[0];
  assert.ok(t.startsWith("~"));
  assert.equal(t, "~4 anos e 2 meses");
  const desc = linha(linhasFicha([item({ medicoes: [med("2026-10-17")] })]), "Tempo de conta").valores[0];
  assert.equal(desc, "data da conta desconhecida");
});

test("linhasFicha: item sem medições e um item só sem destaque", () => {
  const com = item({ medicoes: [med("2026-10-17", { poder: 100 })] });
  const vazio = item({ conta: { id: 2, nome: "Conta Y" } });
  const l = linhasFicha([com, vazio]);
  for (const x of l) assert.equal(x.valores[1], "sem medições");
  assert.equal(linha(l, "Poder").difere, true);
  assert.ok(linhasFicha([com]).every((x) => x.difere === false));
});

test("linhasFicha: casinhas com inquilinos", () => {
  const i = item({
    medicoes: [med("2026-10-17")],
    casinhas: [{ id: 1, nivel: 3, transferencia_pct: 12, inquilino: "Heroi B" }, { id: 2, nivel: 1, transferencia_pct: null, inquilino: null }],
  });
  const l = linhasFicha([i]);
  assert.equal(linha(l, "Quantidade").valores[0], "2");
  assert.equal(linha(l, "Inquilinos").valores[0], "Heroi B (12%), —");
});

test("preencher: estado vai para valores e números só para dicas", () => {
  const { valores, dicas } = preencher(med("2026-10-10", { poder: 500, hp: 90, arvore: 40, artefato: "Artefato Z" }));
  assert.equal(valores.arvore, 40);
  assert.equal(valores.artefato, "Artefato Z");
  assert.ok(!("poder" in valores));
  assert.deepEqual(Object.keys(valores).sort(), [...ESTADO].sort());
  assert.equal(dicas.poder, 500);
  assert.equal(dicas.hp, 90);
  assert.deepEqual(Object.keys(dicas).sort(), [...NUMEROS].sort());
});

test("preencher(null) devolve objetos vazios", () => {
  assert.deepEqual(preencher(null), { valores: {}, dicas: {} });
});

test("montarItem: número só entra se editado e preenchido", () => {
  const { valores } = preencher(med("2026-10-10", { poder: 500, arvore: 40 }));
  const sem = montarItem(7, valores, new Set(), new Set());
  assert.equal(sem.heroi_id, 7);
  assert.ok(!("poder" in sem));
  assert.equal(sem.arvore, 40);
  const com = montarItem(7, { ...valores, poder: 600, ataque: "" }, new Set(["poder", "ataque"]), new Set());
  assert.equal(com.poder, 600);
  assert.equal(com.ataque, null); // editado e esvaziado apaga o gravado
});

test("montarItem: campo limpo vira null", () => {
  const { valores } = preencher(med("2026-10-10", { artefato: "Artefato Z", arvore: 40 }));
  const item = montarItem(7, valores, new Set(), new Set(["artefato", "poder"]));
  assert.equal(item.artefato, null);
  assert.equal(item.poder, null);
  assert.equal(item.arvore, 40);
});

test("montarItem: número editado e esvaziado vira null; não editado fica de fora", () => {
  const item = montarItem(7, { poder: "", hp: 10 }, new Set(["poder"]), new Set());
  assert.equal(item.poder, null);
  assert.ok(!("hp" in item));
});

test("montarItem: estado esvaziado à mão (em limpos) vira null, mesmo com valor null", () => {
  const item = montarItem(7, { arvore: null, notas: null }, new Set(), new Set(["arvore", "notas"]));
  assert.equal(item.arvore, null);
  assert.equal(item.notas, null);
});

test("faixaX: lista vazia não fixa limites", () => {
  assert.deepEqual(faixaX([], "dia0"), { min: undefined, max: undefined, passo: undefined });
  assert.deepEqual(faixaX([], "datas"), { min: undefined, max: undefined, passo: undefined });
});

test("faixaX: um x só ganha folga (senão o gráfico fica vazio)", () => {
  assert.deepEqual(faixaX([0, 0], "dia0"), { min: -1, max: 1, passo: 1 });
  const d = Date.UTC(2026, 9, 17);
  assert.deepEqual(faixaX([d], "datas"), { min: d - 86400000, max: d + 86400000, passo: 86400000 });
});

test("faixaX: faixa curta marca de dia em dia; longa deixa o Chart.js escolher", () => {
  assert.deepEqual(faixaX([5, -3, 7], "dia0"), { min: -3, max: 7, passo: 1 });
  assert.deepEqual(faixaX([0, 400], "dia0"), { min: 0, max: 400, passo: undefined });
  const d = Date.UTC(2026, 9, 17);
  assert.equal(faixaX([d, d + 30 * 86400000], "datas").passo, undefined);
});
