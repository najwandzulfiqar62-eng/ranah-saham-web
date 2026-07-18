/* RANAH SAHAM service worker.
   Strategi: cache "shell" aplikasi agar bisa dibuka cepat / offline, TAPI
   JANGAN pernah cache data live (/api/*) karena harga & analisis sensitif waktu. */
const CACHE = 'ranahsaham-v4';
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
