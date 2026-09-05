# =========================
# KONFIGURASI
# =========================
# Semua nilai konfigurasi terpusat di sini agar mudah ditemukan dan diubah.
# Versi web-only: tidak ada token/konfigurasi Telegram.

import os

# Muat .env (kalau ada) ke os.environ SEBELUM baris os.environ.get() di
# bawah dibaca -- .env.example sudah menjanjikan alur "salin ke .env, isi
# nilainya", tapi sebelum ini TIDAK ADA kode yang benar2 memuatnya (cuma
# jalan di Railway krn platform itu set env var asli, bukan file .env).
# override=False -- env var yang sudah di-set eksplisit di shell/platform
# deployment TETAP menang, .env cuma fallback utk dev lokal.
from dotenv import load_dotenv
load_dotenv(override=False)

# ---- Database (cache fundamental + riwayat sinyal Top Pick) ----
# Satu file SQLite untuk semua kebutuhan penyimpanan lokal aplikasi ini --
# nama digeneralisasi dari "fundamental_cache.db" karena sekarang juga
# menyimpan tabel signal_history (lihat core/signal_history.py). Kalau
# DATABASE_URL sudah diset eksplisit di deployment lama, itu tetap dipakai
# apa adanya (tidak dipaksa migrasi nama file).
DATABASE_PATH = os.environ.get("DATABASE_URL", "ranah_saham.db")

# ---- Data Saham ----
# File Excel daftar emiten yang tercatat di BEI (kolom: Kode, Nama Perusahaan,
# Papan Pencatatan, dst). Diambil dari data/saham.xlsx.
SAHAM_XLSX_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "saham.xlsx")

# Papan pencatatan yang DI-EXCLUDE dari screening otomatis. "Pemantauan Khusus"
# adalah saham yang sedang diawasi BEI karena masalah likuiditas/keuangan/
# kepatuhan, sehingga diexclude agar hasil screening lebih aman.
EXCLUDED_PAPAN_PENCATATAN = {"Pemantauan Khusus"}

# Fallback bila data/saham.xlsx gagal dibaca (rusak/hilang). load_tickers()
# akan selalu mencetak peringatan jelas bila jatuh ke daftar ini, agar tidak
# tampak diam-diam bahwa screening hanya berjalan pada delapan saham.
FALLBACK_TICKERS = [
    "BBCA.JK", "BBRI.JK", "BMRI.JK", "TLKM.JK",
    "ASII.JK", "BRMS.JK", "MDKA.JK", "ANTM.JK"
]

# ---- Rate limiting / batching untuk panggilan ke Yahoo Finance ----
# Dipakai saat melakukan loop banyak ticker (screener) agar tidak membanjiri
# Yahoo Finance dan terkena rate-limit / pemblokiran IP.
YF_BATCH_SIZE = 40            # jumlah ticker per batch
YF_BATCH_DELAY_SECONDS = 0.8  # jeda antar batch

# Batas waktu per panggilan yfinance (fast_info & download) -- SEBELUMNYA
# tidak ada sama sekali, jadi kalau Yahoo Finance hang (bukan error, cuma
# lambat/tidak merespons), asyncio.to_thread() menunggu TANPA BATAS. Endpoint
# yang menggabungkan banyak panggilan sekaligus (mis. /api/signals mengambil
# harga live semua sinyal OPEN, /api/portofolio mode otomatis menganalisis
# puluhan kandidat) ikut tersangkut kalau SATU SAJA ticker macet -- baru
# gagal setelah request timeout di level browser/proxy, muncul sbg
# "Gagal memuat data." tanpa penjelasan (bug nyata, ditemukan 2026-07-27).
# Timeout mengubah hang jadi exception biasa, yang jalur error-handling yang
# SUDAH ADA di tiap pemanggil sanggup menangani (skip ticker itu, bukan
# menggantung selamanya).
YF_FETCH_TIMEOUT_SECONDS = 20

# ---- Forum komunitas ----
# Kode rahasia admin Forum (badge "Admin" + hak hapus thread/balasan).
# Diverifikasi di SERVER (web/app.py::_forum_is_admin, hmac.compare_digest)
# -- TIDAK PERNAH dipercaya dari klaim klien begitu saja, konsisten dgn
# prinsip "tidak ada kunci/token di sisi browser" (lihat web/app.py).
# Kosong = fitur admin forum nonaktif total (fail-closed) -- forum tetap
# jalan normal tanpa admin, cuma badge/hapus tidak pernah bisa didapat.
FORUM_ADMIN_SECRET = os.environ.get("FORUM_ADMIN_SECRET", "")

# ---- Akses aplikasi (akun gratis, approval admin) ----
# Admin awal dibuat otomatis saat aplikasi menyala bila dua variabel ini diisi.
# Jangan taruh nilainya di source control: isi di file .env pada server.
ACCESS_ADMIN_EMAIL = os.environ.get("ACCESS_ADMIN_EMAIL", "").strip().lower()
ACCESS_ADMIN_PASSWORD = os.environ.get("ACCESS_ADMIN_PASSWORD", "")
# Cookie sesi harus secure di domain HTTPS produksi. Untuk pengembangan lokal
# tanpa HTTPS saja, set ACCESS_COOKIE_SECURE=0 di .env lokal.
ACCESS_COOKIE_SECURE = os.environ.get("ACCESS_COOKIE_SECURE", "1") != "0"

# OAuth Google (opsional; tombol Google otomatis nonaktif bila kosong).
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get(
    "GOOGLE_REDIRECT_URI", "https://ranahsaham.com/api/access/google/callback"
).strip()

# ---- Broadcast sinyal ke grup WhatsApp (sidecar wa-bot/, lihat README-nya) ----
# WhatsApp Cloud API resmi tidak bisa kirim ke grup, jadi dipakai sidecar
# Node.js (Baileys, otomasi WhatsApp Web) terpisah -- lihat docker-compose.yml
# service "wa-bot". Kosong = fitur nonaktif diam-diam (send_wa_text fail-open,
# tidak pernah membuat app utama crash).
WA_BOT_URL = os.environ.get("WA_BOT_URL", "http://127.0.0.1:3901").rstrip("/")
WA_BOT_SECRET = os.environ.get("WA_BOT_SECRET", "")
# Jam kirim digest harian (WIB, format "HH:MM"), sebelum bursa buka 09:00.
WA_DAILY_SEND_TIME = os.environ.get("WA_DAILY_SEND_TIME", "08:30")
# Interval cek loop background (detik) -- tidak perlu presisi menit, cukup
# cek berkala sampai jam target terlewati.
WA_CHECK_INTERVAL_SECONDS = int(os.environ.get("WA_CHECK_INTERVAL_SECONDS", "300"))
