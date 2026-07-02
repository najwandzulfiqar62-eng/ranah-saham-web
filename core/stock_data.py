# =========================
# STOCK DATA HELPERS
# =========================
# Modul ini menangani pemuatan daftar ticker dari data/saham.xlsx,
# plus helper kecil untuk membersihkan DataFrame hasil yfinance.
#
# PERUBAHAN dari main.py versi lama:
# - load_tickers() dulu fallback DIAM-DIAM ke 8 ticker hardcoded kalau
#   file Excel gagal dibaca, tanpa warning apapun. Sekarang akan selalu
#   print warning yang jelas, karena ini bug yang sempat membuat screener
#   secara tidak sengaja hanya menganalisis 8 saham padahal seharusnya
#   ratusan.
# - Parameter `llimit` dulu ada di signature tapi tidak pernah dipakai
#   di dalam fungsi. Sekarang benar-benar membatasi jumlah ticker yang
#   dikembalikan (berguna untuk testing/debugging supaya tidak menunggu
#   download data ratusan saham).
# - Saham dengan Papan Pencatatan "Pemantauan Khusus" otomatis di-exclude
#   sesuai keputusan produk (lihat core/config.py).
# - Hasil load_tickers() di-cache di memori, supaya tidak perlu membaca
#   ulang file Excel 957 baris setiap kali screener dipanggil. File Excel
#   ini jarang berubah (cuma saat ada saham baru listing/delisting), jadi
#   cache aman dipakai sepanjang proses bot berjalan.

import pandas as pd

from core.config import (
    SAHAM_XLSX_PATH,
    EXCLUDED_PAPAN_PENCATATAN,
    FALLBACK_TICKERS,
)

_ticker_cache = None  # cache di memori, diisi saat load_tickers() pertama kali dipanggil


def load_tickers(limit: int | None = None, force_reload: bool = False) -> list[str]:
    """Memuat daftar ticker saham IDX dari data/saham.xlsx.

    Args:
        limit: jika diisi, hanya mengembalikan N ticker pertama. Berguna
               untuk testing supaya tidak menunggu download data ratusan
               saham. None (default) = semua ticker.
        force_reload: jika True, baca ulang file Excel meski sudah ada
               cache. Berguna kalau file saham.xlsx baru diupdate.

    Returns:
        List ticker dengan suffix ".JK", contoh: ["BBCA.JK", "BBRI.JK", ...]
        Saham dengan Papan Pencatatan "Pemantauan Khusus" sudah di-exclude.
    """
    global _ticker_cache

    if _ticker_cache is None or force_reload:
        try:
            df = pd.read_excel(SAHAM_XLSX_PATH)
            df = df[~df["Papan Pencatatan"].isin(EXCLUDED_PAPAN_PENCATATAN)]
            tickers = df["Kode"].dropna().astype(str).tolist()
            _ticker_cache = [t + ".JK" for t in tickers]
            print(f"✅ Loaded {len(_ticker_cache)} ticker dari saham.xlsx "
                  f"(setelah exclude {EXCLUDED_PAPAN_PENCATATAN})")
        except Exception as e:
            # PENTING: dulu ini silent fallback tanpa warning sama sekali.
            # Sekarang selalu di-print supaya kalau ini terjadi di production,
            # langsung kelihatan di log -- bukan baru ketahuan belakangan
            # bahwa screening cuma jalan di 8 saham.
            print(f"⚠️ GAGAL membaca {SAHAM_XLSX_PATH}: {e}")
            print(f"⚠️ FALLBACK ke {len(FALLBACK_TICKERS)} ticker hardcoded saja!")
            _ticker_cache = FALLBACK_TICKERS

    if limit is not None:
        return _ticker_cache[:limit]
    return _ticker_cache


def fix_yf_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Meratakan MultiIndex column dari hasil yf.download.

    yfinance versi lama (<= 0.2.x) mengembalikan MultiIndex dengan level 0
    = nama kolom ('Open','High','Low','Close','Volume') dan level 1 = ticker.
    yfinance versi baru (>= 1.x) MEMBALIK urutan ini: level 0 = ticker,
    level 1 = nama kolom.

    Fungsi ini mendeteksi format mana yang aktif dan selalu mengekstrak
    level yang berisi KOLOM OHLCV, bukan nama ticker -- supaya kode
    downstream (calculate_rsi, dll) tidak crash dengan column berisi
    nama ticker sebagai string."""
    if not isinstance(df.columns, pd.MultiIndex):
        return df

    ohlcv = {"Open", "High", "Low", "Close", "Volume", "Adj Close"}

    # Cek level 0: kalau mayoritas nilainya OHLCV, ini format lama
    level0_vals = set(df.columns.get_level_values(0))
    if level0_vals & ohlcv:
        # Format lama: level 0 = OHLCV, langsung pakai
        df.columns = df.columns.get_level_values(0)
    else:
        # Format baru (yfinance >= 1.x): level 0 = ticker, level 1 = OHLCV
        level1_vals = set(df.columns.get_level_values(1))
        if level1_vals & ohlcv:
            df.columns = df.columns.get_level_values(1)
        else:
            # Fallback: ambil level 0, kemungkinan data sudah benar
            df.columns = df.columns.get_level_values(0)

    # Pastikan hanya ada satu kolom per nama (hapus duplikat jika ada)
    df = df.loc[:, ~df.columns.duplicated()]
    return df
