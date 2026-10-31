// Service worker do app de alertas.
// O texto da notificação vem pronto do servidor (genérico): o SW nunca monta texto próprio
// e não guarda nada em cache (nem dados da API).
// Sem rede (Tailscale desligado, DNS bloqueado), abrir o app devolve a página fixa abaixo em vez
// da tela preta do iOS. Ela é escrita aqui mesmo: nenhum dado de alerta fica no aparelho.

const PAGINA_SEM_CONEXAO = `<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<title>Alertas</title>
<style>
:root { --chao:#F4F5F7; --superficie:#FFFFFF; --texto:#15181D; --suave:#555D69; --borda:#E1E4E9;
        --destaque:#1D5AA6; --sobre-destaque:#FFFFFF; }
@media (prefers-color-scheme: dark) {
  :root { --chao:#0F1216; --superficie:#171B21; --texto:#E8EBEF; --suave:#9AA3AF; --borda:#2A3039;
          --destaque:#7FB0EE; --sobre-destaque:#0F1216; }
}
* { box-sizing: border-box; }
body { margin:0; min-height:100vh; background:var(--chao); color:var(--texto);
       font-family:-apple-system, system-ui, "Segoe UI", sans-serif; display:flex; align-items:center;
       justify-content:center; padding:max(24px, env(safe-area-inset-top)) 16px 24px; }
main { max-width:420px; width:100%; background:var(--superficie); border:1px solid var(--borda);
       border-radius:16px; padding:24px; }
h1 { font-size:20px; margin:0 0 8px; }
p { color:var(--suave); line-height:1.45; margin:0 0 12px; }
ul { color:var(--suave); line-height:1.45; margin:0 0 20px; padding-left:20px; }
button { font:inherit; font-weight:600; border:0; border-radius:10px; padding:12px 16px; width:100%;
         background:var(--destaque); color:var(--sobre-destaque); }
</style></head>
<body><main>
<h1>Não foi possível carregar</h1>
<p>O aparelho não alcançou o servidor. Confira:</p>
<ul>
<li>se o Tailscale está ligado;</li>
<li>se a Retransmissão Privada do iCloud está desligada (no iPhone).</li>
</ul>
<button type="button" onclick="location.reload()">Tentar de novo</button>
</main></body></html>`;

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

// Só a abertura de página passa por aqui; respostas do servidor (inclusive 403) seguem iguais.
self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return;
  event.respondWith(
    fetch(event.request).catch(
      () => new Response(PAGINA_SEM_CONEXAO, {
        status: 503,
        headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" },
      })
    )
  );
});

self.addEventListener("push", (event) => {
  const corpo = event.data ? event.data.text() : "";
  event.waitUntil(self.registration.showNotification("Alertas", { body: corpo, icon: "/static/icone-192.png" }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((janelas) => {
      for (const j of janelas) {
        if ("focus" in j) return j.focus();
      }
      return self.clients.openWindow("/");
    })
  );
});
