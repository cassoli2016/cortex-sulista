/* Service worker do Córtex Sulista — recebe os pushes (Web Push) e abre o
   painel ao tocar na notificação. Não faz cache (o app é servido do disco). */
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
  let d = {};
  try { d = event.data ? event.data.json() : {}; } catch (_) { d = {}; }
  const title = d.title || 'Córtex Sulista';
  event.waitUntil(self.registration.showNotification(title, {
    body: d.body || '',
    icon: '/static/favicon.png',
    badge: '/static/favicon.png',
    data: { url: d.url || '/' },
    tag: 'cortex-digest',      // um push substitui o anterior (não empilha)
    renotify: true,
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    .then((cs) => {
      for (const c of cs) {
        if ('focus' in c) { if (c.navigate) { try { c.navigate(url); } catch (_) {} } return c.focus(); }
      }
      if (self.clients.openWindow) return self.clients.openWindow(url);
    }));
});
