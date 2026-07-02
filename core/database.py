# =========================
# DATABASE LAYER (SQLite) -- cache fundamental
# =========================
# Versi web-only. Modul ini sekarang HANYA menyimpan cache data fundamental
# (PE, PBV, ROE, dst). Tabel akun/watchlist/alert pada versi bot Telegram lama
# sudah dihapus karena fitur tersebut tidak dipakai pada aplikasi web ini.
#
# Catatan desain yang dipertahankan dari versi lama:
# - Satu koneksi per-thread (bukan buka/tutup file tiap panggilan) supaya
#   ringan saat banyak permintaan bersamaan.
# - PRAGMA synchronous=NORMAL aman dipakai bersama mode WAL dan jauh lebih
#   cepat daripada default FULL.
# - Semua query memakai placeholder "?" (parameterized) untuk mencegah injeksi.

import json
import sqlite3
import threading
from contextlib import contextmanager

from core.config import DATABASE_PATH

_local = threading.local()


def _get_connection() -> sqlite3.Connection:
    """Koneksi SQLite per-thread (dibuat sekali, lalu dipakai ulang)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn = conn
    return conn


@contextmanager
def get_db():
    """Context manager transaksi: commit otomatis, rollback bila ada error."""
    conn = _get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


_ensured = False


def _ensure_fundamental_cache():
    """Buat tabel cache bila belum ada. Dipanggil lazy sebelum akses pertama,
    jadi modul tidak butuh langkah inisialisasi global terpisah."""
    global _ensured
    if _ensured:
        return
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS fundamental_cache (
                ticker        TEXT PRIMARY KEY,
                data_json     TEXT NOT NULL,
                cached_at     TEXT DEFAULT (datetime('now'))
            )
        ''')
    _ensured = True


def get_cached_fundamental_db(ticker: str, max_age_days: int = 7) -> dict | None:
    """Ambil data fundamental dari cache bila ada dan belum lebih tua dari
    max_age_days. Mengembalikan None bila tidak ada / basi (caller lalu
    mengambil data baru dari yfinance dan menyimpannya kembali).

    max_age_days=7: data fundamental berubah lambat (laporan keuangan per
    kuartal), sehingga tujuh hari adalah kompromi wajar antara kesegaran data
    dan pengurangan beban permintaan ke yfinance."""
    _ensure_fundamental_cache()
    with get_db() as conn:
        row = conn.execute('''
            SELECT data_json, cached_at FROM fundamental_cache
            WHERE ticker = ? AND cached_at > datetime('now', ?)
        ''', (ticker, f'-{max_age_days} days')).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["data_json"])
        except (json.JSONDecodeError, TypeError):
            return None  # cache korup -- diperlakukan sebagai cache miss


def save_fundamental_cache_db(ticker: str, data: dict):
    """Simpan/perbarui data fundamental ke cache (timpa cache lama)."""
    _ensure_fundamental_cache()
    with get_db() as conn:
        conn.execute('''
            INSERT INTO fundamental_cache (ticker, data_json, cached_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(ticker) DO UPDATE SET
                data_json = excluded.data_json,
                cached_at = excluded.cached_at
        ''', (ticker, json.dumps(data)))
