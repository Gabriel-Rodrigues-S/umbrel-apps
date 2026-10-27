// Testes das funções puras de formatação (dados inventados). Rodar: node --test tests/js/
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  quando, subtitulo, contar, numeroDoResumo, ehResumo, periodoResumo, temExplicacao, diaRelativo,
  base64urlParaBytes, cabecalho,
} from "../../alertas/static/formato.js";

const AGORA = new Date(2026, 9, 27, 14, 30, 0); // 27/10/2026 14:30 (hora local)
const em = (a, m, d, h, mi, s = 0) => new Date(a, m - 1, d, h, mi, s).toISOString();
const al = (gravidade, lido = false, extra = {}) => ({ id: 1, origem: "gateway", gravidade, titulo: "t", detalhes: "", criado_em: "", lido, ...extra });

test("quando: menos de 1 h", () => {
  assert.equal(quando(em(2026, 10, 27, 14, 30, 0), AGORA), "agora");
  assert.equal(quando(em(2026, 10, 27, 14, 29, 30), AGORA), "agora");
  assert.equal(quando(em(2026, 10, 27, 14, 18), AGORA), "há 12 min");
  assert.equal(quando(em(2026, 10, 27, 13, 31), AGORA), "há 59 min");
});

test("quando: hoje, ontem e mais antigo", () => {
  assert.equal(quando(em(2026, 10, 27, 13, 30), AGORA), "hoje, 13:30");
  assert.equal(quando(em(2026, 10, 27, 8, 5), AGORA), "hoje, 08:05");
  assert.equal(quando(em(2026, 10, 26, 22, 31), AGORA), "ontem, 22:31");
  assert.equal(quando(em(2026, 10, 25, 9, 14), AGORA), "25/10, 09:14");
  assert.equal(quando(em(2026, 1, 3, 0, 0), AGORA), "03/01, 00:00");
});

test("quando: virada do dia e do mês", () => {
  const cedo = new Date(2026, 10, 1, 0, 10); // 01/11 00:10
  assert.equal(quando(em(2026, 10, 31, 23, 50), cedo), "há 20 min");
  assert.equal(quando(em(2026, 10, 31, 22, 0), cedo), "ontem, 22:00");
  assert.equal(diaRelativo(new Date(2026, 9, 30, 12, 0), cedo), "30/10");
});

test("quando: texto inválido não quebra", () => {
  assert.equal(quando("lixo", AGORA), "");
});

test("subtitulo", () => {
  assert.equal(subtitulo([]), "Tudo em dia");
  assert.equal(subtitulo([al("grave", true), al("normal", true)]), "Tudo em dia");
  assert.equal(subtitulo([al("normal")]), "1 não lido");
  assert.equal(subtitulo([al("grave")]), "1 não lido · 1 grave");
  assert.equal(subtitulo([al("grave"), al("normal"), al("normal")]), "3 não lidos · 1 grave");
  assert.equal(subtitulo([al("grave"), al("grave"), al("info")]), "3 não lidos · 2 graves");
  assert.equal(subtitulo([al("grave", true), al("normal"), al("normal")]), "2 não lidos");
});

test("contar ignora lidos", () => {
  assert.deepEqual(contar([al("grave", true), al("grave"), al("normal")]), { naoLidos: 2, graves: 1 });
});

test("resumo diário: número final de detalhes", () => {
  const d = "Tentativas com token ausente ou inválido nas últimas 24 h: 37";
  assert.equal(numeroDoResumo(d), 37);
  assert.equal(numeroDoResumo(d + "\n"), 37);
  assert.equal(numeroDoResumo("abc"), null);
  assert.equal(numeroDoResumo(""), null);
  assert.equal(ehResumo(al("info", false, { titulo: "Resumo diário", detalhes: d })), true);
  assert.equal(ehResumo(al("info", false, { titulo: "Resumo diário", detalhes: "sem número" })), false);
  assert.equal(ehResumo(al("info", false, { titulo: "Outro", detalhes: d })), false);
  assert.equal(ehResumo(al("normal", false, { titulo: "Resumo diário", detalhes: d })), false);
});

test("periodoResumo usa a data do próprio alerta", () => {
  assert.equal(periodoResumo(em(2026, 10, 27, 8, 0), AGORA), "Últimas 24 horas, até hoje às 08:00");
  assert.equal(periodoResumo(em(2026, 10, 26, 8, 0), AGORA), "Últimas 24 horas, até ontem às 08:00");
  assert.equal(periodoResumo(em(2026, 10, 20, 8, 0), AGORA), "Últimas 24 horas, até 20/10 às 08:00");
});

test("frase explicativa só para tentativa negada", () => {
  assert.equal(temExplicacao(al("grave", false, { titulo: "Tentativa negada: cliente claude" })), true);
  assert.equal(temExplicacao(al("normal", false, { titulo: "Rajada de tokens inválidos" })), false);
});

test("base64url para bytes", () => {
  assert.deepEqual([...base64urlParaBytes("AQID")], [1, 2, 3]);
  assert.deepEqual([...base64urlParaBytes("-_8")], [251, 255]);
});

test("cabecalho: falha no primeiro carregamento nunca diz que está tudo em dia", () => {
  const c = cabecalho({ tentou: true, falhou: true, alertas: [] });
  assert.deepEqual(c, { subtitulo: "Não foi possível carregar", mostrarVazia: false });
});

test("cabecalho: falha ao recarregar com dados antigos", () => {
  const c = cabecalho({ tentou: true, falhou: true, alertas: [al("normal", true)] });
  assert.deepEqual(c, { subtitulo: "Não foi possível carregar", mostrarVazia: false });
});

test("cabecalho: antes do primeiro carregamento fica vazio", () => {
  assert.deepEqual(cabecalho({ tentou: false, falhou: false, alertas: [] }), { subtitulo: "", mostrarVazia: false });
});

test("cabecalho: sucesso sem alertas e só com lidos", () => {
  assert.deepEqual(cabecalho({ tentou: true, falhou: false, alertas: [] }), { subtitulo: "Tudo em dia", mostrarVazia: true });
  assert.deepEqual(cabecalho({ tentou: true, falhou: false, alertas: [al("grave", true)] }), { subtitulo: "Tudo em dia", mostrarVazia: false });
  assert.deepEqual(cabecalho({ tentou: true, falhou: false, alertas: [al("grave")] }), { subtitulo: "1 não lido · 1 grave", mostrarVazia: false });
});
