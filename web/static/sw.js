/* RANAH SAHAM service worker.
   Strategi: cache "shell" aplikasi agar bisa dibuka cepat / offline, TAPI
   JANGAN pernah cache data live (/api/*) karena harga & analisis sensitif waktu. */
const CACHE = 'ranahsaham-v24';
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
  // Shell & aset statis: STALE-WHILE-REVALIDATE (permintaan user "biar enak
  // dipakai"). Sebelumnya network-first -> tiap buka aplikasi tetap MENUNGGU
  // unduh HTML 145KB dulu. Sekarang: sajikan dari cache SEKETIKA (buka kedua
  // & seterusnya INSTAN), lalu revalidasi ke jaringan DI BALIK LAYAR utk
  // update berikutnya. Tradeoff sadar: user melihat versi SEBELUMNYA sampai
  // reload berikutnya -- update tetap sampai (revalidasi mengisi cache utk
  // load berikutnya; bump CACHE saat perubahan penting menghapus cache lama).
  e.respondWith(
    caches.match(e.request).then((cached) => {
      const fromNetwork = fetch(e.request).then((r) => {
        // hanya cache respons sukses penuh (200) -- jangan simpan error/partial
        if (r && r.status === 200) {
          const cp = r.clone();
          caches.open(CACHE).then((c) => c.put(e.request, cp)).catch(() => {});
        }
        return r;
      }).catch(() => null);
      if (cached) {
        e.waitUntil(fromNetwork);                    // revalidasi tetap jalan walau respons sudah dikirim
        return cached;                               // <-- instan
      }
      // belum ada di cache (kunjungan pertama / aset baru): tunggu jaringan,
      // fallback ke shell '/' kalau offline.
      return fromNetwork.then((r) => r || caches.match('/'));
    })
  );
});
