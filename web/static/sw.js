/* RANAH SAHAM service worker.
   Strategi: cache "shell" aplikasi agar bisa dibuka cepat / offline, TAPI
   JANGAN pernah cache data live (/api/*) karena harga & analisis sensitif waktu. */
// v26 (2026-07-29): WAJIB dinaikkan tiap perubahan penting di index.html --
// lihat catatan strategi stale-while-revalidate di handler fetch di bawah.
// Kalau lupa, user tetap melihat UI versi LAMA walau server sudah menyajikan
// yang baru (persis yang terjadi pada perbaikan "satu saham, dua teori":
// backend & file di server sudah benar, tapi shell lama masih dari cache).
const CACHE = 'ranahsaham-v49';
// '/app.js' dan '/app.css' WAJIB ikut di-precache. Sejak keduanya dipisah dari
// index.html, tanpa ini pembukaan pertama (dan offline) kehilangan SELURUH
// logika aplikasi (halamannya tampil tapi mati total) atau SELURUH gayanya
// (halaman telanjang yang terlihat seperti aplikasi rusak).
const SHELL = ['/', '/app.css', '/app.js', '/manifest.json', '/icon-192.png', '/icon-512.png', '/apple-touch-icon.png'];

self.addEventListener('install', (e) => {
  // SATU PER SATU, bukan addAll. addAll gagal TOTAL kalau SATU aset saja
  // meleset (404, 429 dari rate limit, jaringan putus di tengah) -- dan
  // baris lama menelan kegagalan itu lalu tetap mengaktifkan SW. Hasilnya
  // cache KOSONG; begitu 'activate' menghapus cache versi lama, tidak ada
  // lagi apa pun yang bisa disajikan, dan yang dilihat user adalah HALAMAN
  // PUTIH yang menggantung lama. Sekarang aset yang gagal dilewati saja dan
  // sisanya tetap tersimpan.
  e.waitUntil((async () => {
    try {
      const c = await caches.open(CACHE);
      await Promise.all(SHELL.map((u) => c.add(u).catch(() => null)));
    } catch (_) { /* cache tidak tersedia -> jalur jaringan tetap jalan */ }
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    // Cache versi baru diperiksa ISINYA dulu. Kalau precache tadi gagal
    // total, cache LAMA sengaja TIDAK dihapus -- lebih baik user melihat
    // versi kemarin daripada halaman putih. Cache lama akan terhapus sendiri
    // pada aktivasi berikutnya yang precache-nya berhasil.
    try {
      const c = await caches.open(CACHE);
      const isi = await c.keys();
      if (isi.length) {
        const ks = await caches.keys();
        await Promise.all(ks.map((k) => (k !== CACHE ? caches.delete(k) : null)));
      }
    } catch (_) { /* biarkan cache lama utuh */ }
    await self.clients.claim();
  })());
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
  e.respondWith((async () => {
    let cached = null;
    try { cached = await caches.match(e.request); } catch (_) { cached = null; }

    const fromNetwork = fetch(e.request).then((r) => {
      // hanya cache respons sukses penuh (200) -- jangan simpan error/partial
      if (r && r.status === 200) {
        const cp = r.clone();
        caches.open(CACHE).then((c) => c.put(e.request, cp)).catch(() => {});
      }
      return r;
    }).catch(() => null);

    if (cached) {
      e.waitUntil(fromNetwork);   // revalidasi tetap jalan walau respons sudah dikirim
      return cached;              // <-- instan
    }

    const dariJaringan = await fromNetwork;
    if (dariJaringan) return dariJaringan;

    let shell = null;
    try { shell = await caches.match('/'); } catch (_) { shell = null; }
    if (shell) return shell;

    // JANGAN PERNAH selesai dengan undefined. respondWith yang menerima
    // undefined menggagalkan navigasi, dan yang dilihat user adalah HALAMAN
    // PUTIH tanpa satu pun petunjuk -- kegagalan paling membingungkan yang
    // bisa dihasilkan service worker. Untuk navigasi, kirim halaman kecil
    // yang menjelaskan keadaannya dan mencoba lagi sendiri.
    if (e.request.mode === 'navigate') {
      return new Response(
        '<!doctype html><meta charset="utf-8">'
        + '<meta name="viewport" content="width=device-width,initial-scale=1">'
        + '<title>Ranah Saham</title>'
        + '<body style="margin:0;display:flex;align-items:center;justify-content:center;'
        + 'height:100vh;background:#0d1117;color:#c9d1d9;'
        + 'font-family:system-ui,-apple-system,sans-serif;text-align:center">'
        + '<div><p style="font-size:15px">Tidak bisa memuat aplikasi.</p>'
        + '<p style="font-size:13px;color:#8b949e">Periksa koneksi, lalu coba lagi.</p>'
        + '<button onclick="location.reload()" style="margin-top:12px;padding:10px 18px;'
        + 'border-radius:8px;border:1px solid #30363d;background:#161b22;color:#c9d1d9;'
        + 'font-size:14px">Coba lagi</button></div>'
        + '<script>setTimeout(function(){location.reload()},5000)<\/script>',
        { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } });
    }
    return new Response('', { status: 504, statusText: 'Gagal memuat' });
  })());
});
