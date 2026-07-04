# =========================
# KONFIGURASI
# =========================
# Semua nilai konfigurasi terpusat di sini agar mudah ditemukan dan diubah.
# Versi web-only: tidak ada token/konfigurasi Telegram.

import os

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
