// Executa o service worker num "self" falso e confere a página sem conexão. Rodar: node --test tests/js/
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const CODIGO = readFileSync(new URL("../../alertas/static/sw.js", import.meta.url), "utf8");

// Carrega o sw.js com um fetch controlado pelo teste e devolve o handler de "fetch".
function carregar(fetchFalso) {
  const handlers = {};
  const self = {
    addEventListener: (nome, fn) => { handlers[nome] = fn; },
    skipWaiting() {},
    clients: { claim() {} },
    registration: { showNotification() {} },
  };
  vm.runInNewContext(CODIGO, { self, fetch: fetchFalso, Response });
  return handlers.fetch;
}

// Simula um evento de fetch; devolve a resposta passada a respondWith (ou undefined se ignorado).
async function disparar(handler, mode) {
  let resposta;
  handler({ request: { mode, url: "https://exemplo.test/" }, respondWith: (p) => { resposta = p; } });
  return resposta === undefined ? undefined : await resposta;
}

test("sem rede: abrir o app mostra a página fixa com as dicas", async () => {
  const h = carregar(() => Promise.reject(new TypeError("Load failed")));
  const r = await disparar(h, "navigate");
  assert.equal(r.status, 503);
  assert.match(r.headers.get("content-type"), /text\/html/);
  assert.equal(r.headers.get("cache-control"), "no-store");
  const html = await r.text();
  assert.match(html, /Não foi possível carregar/);
  assert.match(html, /Tailscale/);
  assert.match(html, /Retransmissão Privada do iCloud/);
  assert.match(html, /Tentar de novo/);
});

test("com rede: a resposta do servidor passa sem mudança (inclusive 403)", async () => {
  const doServidor = new Response("negado", { status: 403 });
  const h = carregar(() => Promise.resolve(doServidor));
  const r = await disparar(h, "navigate");
  assert.equal(r, doServidor);
});

test("pedidos que não são abertura de página não passam pelo SW", async () => {
  const h = carregar(() => { throw new Error("não deveria buscar"); });
  for (const mode of ["cors", "same-origin", "no-cors"]) {
    assert.equal(await disparar(h, mode), undefined);
  }
});

test("a página fixa não carrega nada de fora", () => {
  assert.doesNotMatch(CODIGO, /<script[^>]+src=|<link[^>]+href=|@import|url\(/);
});
