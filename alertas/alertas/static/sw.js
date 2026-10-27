// Service worker do app de alertas.
// O texto da notificação vem pronto do servidor (genérico): o SW nunca monta texto próprio
// e não guarda nada em cache (nem dados da API).

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

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
