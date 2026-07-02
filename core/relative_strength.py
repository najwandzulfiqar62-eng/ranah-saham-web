# =========================
# RELATIVE STRENGTH (KEKUATAN RELATIF VS IHSG/SEKTOR)
# =========================
# FITUR BARU. Mengukur apakah suatu saham bergerak lebih kuat ATAU lebih
# lemah dibanding pasar secara umum (IHSG) dan sektornya, dalam periode
# tertentu (default 20 hari, ~1 bulan trading).
#
# KEGUNAAN: membedakan "saham ini naik karena momentum market secara
# umum" vs "saham ini naik karena ada katalis spesifik di saham itu".
# Saham yang outperform IHSG + sektornya sekaligus biasanya punya alasan
# spesifik (bukan cuma ikut arus market), dan sebaliknya untunderperform.
#
# METODE: rasio return saham dibagi return benchmark dalam periode yang
# sama, dikonversi ke skor. RS > 0 berarti saham mengungguli benchmark,
# RS < 0 berarti tertinggal. Ini BUKAN RSI (Relative Strength Index,
# indikator momentum 0-100) -- istilah "relative strength" di sini punya
# arti finansial yang berbeda (relatif terhadap benchmark lain, bukan
# relatif terhadap histori harga saham itu sendiri). Penting untuk tidak
# tertukar dengan RSI yang sudah ada di core/indicators.py.

import pandas as pd

from core.market import SECTOR_MAP


def calculate_relative_strength(stock_df: pd.DataFrame, benchmark_df: pd.DataFrame,
                                   period_days: int = 20) -> dict | None:
    """Hitung relative strength saham vs satu benchmark (IHSG atau rata-
    rata sektor) dalam period_days terakhir.

    Returns None kalau data tidak cukup panjang untuk period_days yang
    diminta.
    """
    if len(stock_df) < period_days + 1 or len(benchmark_df) < period_days + 1:
        return None

    stock_start = float(stock_df["Close"].iloc[-(period_days + 1)])
    stock_end = float(stock_df["Close"].iloc[-1])
    stock_return = ((stock_end / stock_start) - 1) * 100

    bench_start = float(benchmark_df["Close"].iloc[-(period_days + 1)])
    bench_end = float(benchmark_df["Close"].iloc[-1])
    bench_return = ((bench_end / bench_start) - 1) * 100

    # RS sebagai selisih return (dalam poin persentase), lebih mudah
    # dipahami user awam dibanding rasio. RS = 0 artinya bergerak sama
    # persis dengan benchmark.
    rs_diff = stock_return - bench_return

    if rs_diff > 5:
        verdict = "OUTPERFORM KUAT 🟢🟢"
    elif rs_diff > 1:
        verdict = "OUTPERFORM 🟢"
    elif rs_diff > -1:
        verdict = "SEJALAN (NETRAL) ⚪"
    elif rs_diff > -5:
        verdict = "UNDERPERFORM 🔴"
    else:
        verdict = "UNDERPERFORM KUAT 🔴🔴"

    return {
        "period_days": period_days,
        "stock_return": round(stock_return, 2),
        "benchmark_return": round(bench_return, 2),
        "rs_diff": round(rs_diff, 2),
        "verdict": verdict,
    }


def find_sector_for_ticker(ticker_with_jk: str) -> str | None:
    """Cari nama sektor untuk suatu ticker, kalau terdaftar di SECTOR_MAP.
    Returns None kalau ticker tidak ada di SECTOR_MAP manapun (akan
    cukup sering terjadi karena SECTOR_MAP hanya berisi ~21 saham dari
    793 total -- ini diketahui dan caller harus menangani None secara
    graceful, bukan hanya menampilkan RS vs IHSG)."""
    for sector, tickers in SECTOR_MAP.items():
        if ticker_with_jk in tickers:
            return sector
    return None


def format_relative_strength_message(ticker_name: str, rs_vs_ihsg: dict | None,
                                       sector_name: str | None, rs_vs_sector: dict | None) -> str:
    """Format hasil calculate_relative_strength() (vs IHSG, dan opsional
    vs sektor) jadi pesan teks."""
    if rs_vs_ihsg is None:
        return f"❌ Data {ticker_name} atau IHSG tidak cukup untuk menghitung relative strength."

    msg = f"""
📊 *RELATIVE STRENGTH* - {ticker_name}
({rs_vs_ihsg['period_days']} hari terakhir)
{'='*40}

🇮🇩 *VS IHSG:*
├─ Return {ticker_name}: {rs_vs_ihsg['stock_return']:+.2f}%
├─ Return IHSG: {rs_vs_ihsg['benchmark_return']:+.2f}%
├─ Selisih (RS): {rs_vs_ihsg['rs_diff']:+.2f} poin
└─ Verdict: {rs_vs_ihsg['verdict']}
"""

    if sector_name and rs_vs_sector:
        msg += f"""
{'='*40}
🏢 *VS SEKTOR {sector_name}:*
├─ Return {ticker_name}: {rs_vs_sector['stock_return']:+.2f}%
├─ Return rata-rata sektor: {rs_vs_sector['benchmark_return']:+.2f}%
├─ Selisih (RS): {rs_vs_sector['rs_diff']:+.2f} poin
└─ Verdict: {rs_vs_sector['verdict']}
"""
    elif sector_name is None:
        msg += f"\n{'='*40}\nℹ️ {ticker_name} belum terdaftar di salah satu sektor yang dipantau, jadi perbandingan sektor dilewati (hanya vs IHSG).\n"

    msg += f"""
{'='*40}
💡 *INTERPRETASI:*
• OUTPERFORM = saham bergerak lebih kuat dari benchmark -- biasanya ada katalis spesifik di saham ini, bukan cuma ikut arus market.
• UNDERPERFORM = saham tertinggal dari benchmark -- waspadai kalau mau entry, momentum sektor/market tidak mendukung.
• NETRAL = saham ini bergerak ikut arus market/sektor, tidak ada sinyal spesifik dari pergerakan relatifnya.

⚠️ DYOR -- ini ukuran momentum relatif, bukan rekomendasi langsung.
"""
    return msg
