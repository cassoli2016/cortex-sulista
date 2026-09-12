/* Service worker do APP DO MOTORISTA — SÓ NOTIFICAÇÃO, SEM CACHE.

   `docs/APP_MOTORISTA.md` adiou o PWA com uma razão que continua de pé:
   service worker que faz cache serve uma versão velha do app para sempre, sem
   sintoma e sem jeito de o motorista limpar. Este NÃO escuta `fetch` — toda
   página e toda chamada da API continuam indo à rede como antes. O que ele faz
   é receber o aviso (`push`) e, no toque, abrir o app na aba certa.
   Há teste que reprova um `fetch` neste arquivo.

   Escopo `/motorista`: é registrado pelo `motorista.html` e não alcança o
   painel, que tem o `sw.js` dele. */
self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (e) { e.waitUntil(self.clients.claim()); });

self.addEventListener('push', function (e) {
  var d = {};
  try { d = e.data ? e.data.json() : {}; } catch (err) { d = {}; }
  e.waitUntil(self.registration.showNotification(d.title || 'Motorista Sulista', {
    body: d.body || '',
    tag: d.tag || 'motorista',
    renotify: true,
    icon: '/static/icon-192.png',
    badge: '/static/icon-192.png',
    data: { url: d.url || '/motorista' }
  }));
});

self.addEventListener('notificationclick', function (e) {
  e.notification.close();
  var alvo = (e.notification.data && e.notification.data.url) || '/motorista';
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    .then(function (cs) {
      for (var i = 0; i < cs.length; i++) {
        var c = cs[i];
        if (c.url.indexOf('/motorista') >= 0 && 'focus' in c) {
          if ('navigate' in c) { c.navigate(alvo).catch(function () {}); }
          return c.focus();
        }
      }
      return self.clients.openWindow(alvo);
    }));
});
