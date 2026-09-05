# wa-bot

Sidecar WhatsApp Web (Baileys) yang dipakai `web` (FastAPI) untuk broadcast
sinyal screener + ringkasan kepemilikan ≥5% (X-15) ke grup WhatsApp.

WhatsApp Cloud API resmi TIDAK BISA kirim pesan ke grup, jadi service ini
mengotomasi WhatsApp Web memakai nomor pribadi/khusus bot -- di luar Ketentuan
Layanan resmi WhatsApp untuk otomasi, ada risiko kecil nomor logout/dibatasi.
Pakai nomor sekunder (bukan nomor utama), bukan nomor bisnis/organisasi besar.

## Setup awal (sekali saja)

1. Isi `.env` (lihat `.env.example` di root repo): `WA_BOT_SECRET` (string acak
   panjang, harus SAMA dgn yang dipakai `web`), `WA_GROUP_JID` **kosongkan
   dulu**.
2. `docker compose up -d wa-bot`
3. Lihat QR: `docker compose logs -f wa-bot` (QR ASCII di terminal), atau buka
   `GET /api/admin/whatsapp/qr` lewat browser (login sbg admin di web app --
   endpoint itu memproxy PNG dari service ini).
4. Scan QR dari HP: WhatsApp → Perangkat Tertaut → Tautkan Perangkat.
5. Setelah terhubung, buka `GET /api/admin/whatsapp/groups` (via web app,
   login admin) untuk melihat daftar grup yang bot ikuti beserta JID-nya
   (format `xxxxx@g.us`). Pastikan bot sudah jadi anggota grup target
   (invite dari HP seperti anggota biasa) SEBELUM langkah ini.
6. Isi `WA_GROUP_JID` di `.env` dengan JID grup target, `docker compose up -d
   wa-bot` lagi (restart) supaya env baru terbaca.

Sesi login tersimpan di volume `wa_auth` (mount ke `/data`) -- restart
container BIASA tidak perlu scan ulang. Scan ulang hanya perlu kalau logout
dari HP atau volume terhapus.

## Perintah di grup (interaktif)

Bot ikut MEMBACA pesan grup dan menjawab perintah berikut:

| Ketik | Balasan |
|---|---|
| kode emiten, mis. `BBCA` | analisis teknikal ringkas |
| `sinyal` | ringkasan Audit Sinyal |
| `screener` | saham lolos saringan breakout |
| `kepemilikan` / `x15` | filing kepemilikan ≥5% hari ini |
| `bantuan` | daftar perintah |

Logikanya TIDAK ada di sini: bot cuma meneruskan pesan ke app Python
(`POST /api/wa/command`, Bearer `WA_BOT_SECRET`) dan mengirim balasannya.
Karena itu `APP_BASE_URL` harus menunjuk app utama (default
`http://127.0.0.1:8000`) -- pastikan portnya sama dengan yang dipakai
`ranahsaham.service`.

Dua penjaga yang sengaja ada, jangan dilonggarkan tanpa alasan:

1. **Hanya nomor milik akun yang sudah di-approve yang dilayani.** Nomor lain
   dibalas sekali dengan ajakan mendaftar, lalu didiamkan beberapa jam. Tanpa
   ini, siapa pun yang diundang ke grup dapat seluruh data tanpa akun dan
   alur daftar→persetujuan admin jadi tidak ada gunanya.
2. **Jeda per-nomor + hanya perintah yang jelas yang disahut.** Obrolan biasa
   tidak pernah dibalas. Bot yang menyahut sepanjang hari jauh lebih mudah
   dianggap mesin oleh WhatsApp -- risiko nomor dibatasi naik seiring volume
   pesan, jadi menjawab lebih sering bukan sekadar berisik, tapi berbahaya.

## Endpoint (internal, Bearer `WA_BOT_SECRET`)

- `GET /status` -- status koneksi + apakah grup sudah dikonfigurasi.
- `GET /qr` -- PNG QR pairing (404 kalau sudah terhubung).
- `GET /groups` -- daftar grup yang diikuti bot (setup awal).
- `POST /send {text}` -- kirim teks ke `WA_GROUP_JID`.
- `GET /healthz` -- liveness check, tanpa auth.

Service ini TIDAK diekspos ke luar docker-compose network -- hanya `web`
yang bisa memanggilnya.
