/* RANAH SAHAM service worker.
   Strategi: cache "shell" aplikasi agar bisa dibuka cepat / offline, TAPI
   JANGAN pernah cache data live (/api/*) karena harga & analisis sensitif waktu. */
const CACHE = 'ranahsaham-v15';
const SHELL = ['/', '/manifest.json', '/icon-192.png', '/icon-512.png', '/apple-touch-icon.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()).catch(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((ks) => Promise.all(ks.map((k) => (k !== CACHE ? caches.delete(k) : null))))
      .then(() => self.clients.claim())
  );
});

// ---------- Web Push: tampilkan notifikasi walau app tertutup ----------
self.addEventListener('push', (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = { body: e.data ? e.data.text() : '' }; }
  const title = d.title || 'Ranah Saham';
  e.waitUntil(self.registration.showNotification(title, {
    body: d.body || '',
    icon: '/icon-192.png',
    badge: '/icon-192.png',
    tag: d.tag || 'ranah',
    renotify: true,
    data: { url: d.url || '/' }
  }));
});
// Klik notifikasi -> fokus tab yang sudah ada, atau buka baru
self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || '/';
  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      for (const c of list) { if ('focus' in c) { c.focus(); return; } }
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});

self.addEventListener('fetch', (e) => {
  if (e.request.method !== 'GET') return;            // POST/DELETE (auth, watchlist) -> jaringan apa adanya
  const u = new URL(e.request.url);
  if (u.origin !== location.origin) return;          // pihak ketiga (CDN chart) -> jangan diintervensi
  if (u.pathname.startsWith('/api/')) return;        // data live -> selalu jaringan, tidak pernah di-cache
  // shell & aset statis: network-first, fallback cache (agar update tetap terbawa saat online)
  e.respondWith(
    fetch(e.request)
      .then((r) => {
        const cp = r.clone();
        caches.open(CACHE).then((c) => c.put(e.request, cp)).catch(() => {});
        return r;
      })
      .catch(() => caches.match(e.request).then((m) => m || caches.match('/')))
  );
});
