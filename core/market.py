# =========================
# MARKET REPORT & FILTER
# =========================
# Migrasi filter_cmd, daily_cmd, topgainer_cmd, topvolume_cmd dari
# main.py lama. Semuanya dulu loop SEQUENTIAL per-ticker dengan
# yf.download satu per satu -- sekarang pakai async_download_many()
# untuk paralelisasi.

import numpy as np

from core.async_yf import async_download_many
from core.stock_data import fix_yf_columns
from core.indicators import calculate_rsi

SECTOR_MAP = {
    "BANKING": ["BBCA.JK", "BBRI.JK", "BMRI.JK", "BBNI.JK"],
    "TECH": ["GOTO.JK", "BUKA.JK", "DCII.JK"],
    "ENERGY": ["ADRO.JK", "PTBA.JK", "MEDC.JK", "PGAS.JK"],
    "HEALTH": ["MIKA.JK", "SILO.JK", "HEAL.JK"],
    "CONSUMER": ["ICBP.JK", "INDF.JK", "MYOR.JK", "UNVR.JK"],
    "PROPERTY": ["BSDE.JK", "PWON.JK", "CTRA.JK"],
}

# FITUR BARU. 11 indeks sektoral resmi IDX-IC (IDX Industrial
# Classification, menggantikan sistem lama JASICA) -- dikonfirmasi via
# riset web (Wikipedia, situs resmi IDX, Yahoo Finance) bahwa ticker-
# ticker ini benar-benar diperdagangkan dan punya data historis.
#
# CATATAN JUJUR soal verifikasi: ticker-ticker ini TIDAK BISA dicoba
# eksekusi langsung di sandbox development (domain finance.yahoo.com
# tidak ada di allowlist jaringan sandbox -- bahkan ^JKSE yang sudah
# lama dipakai di seluruh bot ini ikut gagal kalau dicoba eksekusi
# langsung dari sandbox, BUKAN cuma ticker baru ini). Bukti yang
# dipakai adalah TIDAK LANGSUNG: snapshot harga real-time + halaman
# "Historical Data" terindeks terpisah untuk masing-masing ticker di
# Yahoo Finance (dikonfirmasi pada Juni 2026). Kalau ternyata salah
# satu ticker ini tidak bekerja saat dicoba di server produksi,
# kemungkinan besar cuma butuh penyesuaian kecil (mis. tanpa suffix
# .JK, atau ticker IDX-nya sedikit berbeda), bukan pendekatan yang
# salah total.
IDX_SECTORAL_INDICES = {
    "IDXENERGY.JK": "Energi",
    "IDXBASIC.JK": "Barang Baku",
    "IDXINDUST.JK": "Perindustrian",
    "IDXNONCYC.JK": "Konsumen Primer",
    "IDXCYCLIC.JK": "Konsumen Non-Primer",
    "IDXHEALTH.JK": "Kesehatan",
    "IDXFINANCE.JK": "Keuangan",
    "IDXPROPERT.JK": "Properti & Real Estat",
    "IDXTECHNO.JK": "Teknologi",
    "IDXINFRA.JK": "Infrastruktur",
    "IDXTRANS.JK": "Transportasi & Logistik",
}

# Pemetaan dari key SECTOR_MAP (nama ad-hoc yang SUDAH ditampilkan ke
# user di /rs, SENGAJA TIDAK diubah supaya tidak mengubah tampilan
# fitur yang sudah berjalan) ke ticker indeks sektoral resmi yang
# berkorespondensi. Hanya 6 dari 11 sektor resmi yang punya pemetaan
# di sini (sisanya -- Barang Baku, Perindustrian, Konsumen Non-Primer,
# Infrastruktur, Transportasi -- belum ada representasi saham di
# SECTOR_MAP sama sekali).
SECTOR_MAP_TO_INDEX = {
    "BANKING": "IDXFINANCE.JK",
    "TECH": "IDXTECHNO.JK",
    "ENERGY": "IDXENERGY.JK",
    "HEALTH": "IDXHEALTH.JK",
    "CONSUMER": "IDXNONCYC.JK",
    "PROPERTY": "IDXPROPERT.JK",
}


async def run_filter(tickers: list[str], mode: str) -> list[dict]:
    """Filter saham dengan 4 mode: bullish, breakout, volume, reversal.
    Logic kondisi DIPERTAHANKAN IDENTIK dengan main.py lama."""
    data_by_ticker = await async_download_many(tickers, period="3mo")
    results = []

    for ticker, df in data_by_ticker.items():
        try:
            df = fix_yf_columns(df).dropna()

            if len(df) < 50:
                continue

            close = float(df["Close"].iloc[-1])
            prev_close = float(df["Close"].iloc[-2])
            volume = float(df["Volume"].iloc[-1])

            if close < 200:
                continue
            if volume < 500000:
                continue

            avg_volume_20 = df["Volume"].rolling(20).mean().iloc[-1]
            avg_volume_50 = df["Volume"].rolling(50).mean().iloc[-1]
            ma5 = df["Close"].rolling(5).mean().iloc[-1]
            ma20 = df["Close"].rolling(20).mean().iloc[-1]
            ma50 = df["Close"].rolling(50).mean().iloc[-1]

            last_rsi = round(float(calculate_rsi(df["Close"]).iloc[-1]), 2)

            passed = False
            status = ""
            extra_info = ""

            if mode == "bullish":
                cond1 = ma5 > ma20 > ma50
                cond2 = close > ma50
                cond3 = close > ma20
                cond4 = last_rsi > 50
                cond5 = volume > avg_volume_20
                passed = cond1 and cond2 and cond3 and cond4 and cond5
                status = "BULLISH 🟢"
                extra_info = f"MA5>MA20>MA50 | RSI {last_rsi}"

            elif mode == "breakout":
                high20 = df["High"].rolling(20).max().iloc[-2]
                high50 = df["High"].rolling(50).max().iloc[-2]
                cond1 = close >= high20 * 0.995
                cond2 = close >= high50 * 0.99
                cond3 = volume > (1.5 * avg_volume_20)
                cond4 = volume > avg_volume_50
                passed = cond1 and cond2 and cond3 and cond4
                status = "BREAKOUT 🚀"
                extra_info = f"Res20: {int(high20)} | Vol: {volume/avg_volume_20:.1f}x"

            elif mode == "volume":
                vol_ratio_20 = volume / avg_volume_20 if avg_volume_20 > 0 else 1
                vol_ratio_50 = volume / avg_volume_50 if avg_volume_50 > 0 else 1
                cond1 = volume > (2.0 * avg_volume_20)
                cond2 = volume > (1.5 * avg_volume_50)
                cond3 = close > ma20
                passed = cond1 and cond2 and cond3
                status = "VOLUME SPIKE 🔥"
                extra_info = f"{vol_ratio_20:.1f}x avg20 | {vol_ratio_50:.1f}x avg50"

            elif mode == "reversal":
                cond1 = last_rsi < 35
                cond2 = close > df["Close"].rolling(5).mean().iloc[-2]
                cond3 = volume > avg_volume_20
                high20 = df["High"].rolling(20).max().iloc[-1]
                drop_pct = (high20 - close) / high20 * 100
                cond4 = drop_pct > 10
                passed = cond1 and cond2 and cond3 and cond4
                status = "REVERSAL 🔥"
                extra_info = f"RSI {last_rsi} | Turun {drop_pct:.1f}%"

            if passed:
                change = round(((close / prev_close) - 1) * 100, 2)
                results.append({
                    "ticker": ticker.replace(".JK", ""), "price": round(close, 2),
                    "change": change, "rsi": last_rsi, "status": status,
                    "volume": int(volume), "extra": extra_info,
                })

        except Exception as e:
            print(f"Error filter {ticker}: {e}")
            continue

    if mode == "bullish":
        results = sorted(results, key=lambda x: x["change"], reverse=True)
    elif mode in ("breakout", "volume"):
        results = sorted(results, key=lambda x: x["volume"], reverse=True)
    elif mode == "reversal":
        results = sorted(results, key=lambda x: x["rsi"])

    return results


def format_filter_results(results: list[dict], mode: str) -> str:
    """Format hasil run_filter() jadi pesan teks."""
    if not results:
        msg = f"❌ TIDAK ADA SAHAM UNTUK FILTER {mode.upper()}\n\n"
        msg += "Filter ketat yang berlaku:\n"
        msg += "• Harga minimal Rp500\n"
        msg += "• Volume minimal 500.000\n"
        if mode == "bullish":
            msg += "• MA5 > MA20 > MA50\n• Harga > MA50\n• RSI > 50\n"
        elif mode == "breakout":
            msg += "• Break resistance 20h & 50h\n• Volume > 1.5x rata-rata\n"
        elif mode == "volume":
            msg += "• Volume > 2x rata-rata 20h\n• Harga > MA20\n"
        elif mode == "reversal":
            msg += "• RSI < 35\n• Volume konfirmasi\n• Turun > 10%\n"
        return msg

    msg = f"📊 FILTER {mode.upper()} (STRICT MODE)\n{'='*40}\n\n"
    for i, r in enumerate(results[:15], 1):
        emoji = "🟢" if r["change"] >= 0 else "🔴"
        msg += f"{i}. {emoji} *{r['ticker']}*\n"
        msg += f"   Price: Rp{r['price']:,.0f} | {r['change']:+.2f}%\n"
        msg += f"   RSI: {r['rsi']} | Volume: {r['volume']:,}\n"
        msg += f"   📌 {r['status']}\n"
        if r.get('extra'):
            msg += f"   📊 {r['extra']}\n"
        msg += "\n"

    msg += f"{'='*40}\n"
    msg += f"📈 Total saham lolos: {len(results)}\n"
    msg += "⚠️ DYOR sebelum mengambil keputusan"
    return msg


async def get_sector_performance() -> list[dict]:
    """Hitung performa rata-rata tiap sektor (untuk daily report)."""
    all_tickers = [t for tickers in SECTOR_MAP.values() for t in tickers]
    data_by_ticker = await async_download_many(all_tickers, period="5d")

    sector_results = []
    for sector, tickers in SECTOR_MAP.items():
        changes = []
        for ticker in tickers:
            try:
                df = data_by_ticker.get(ticker)
                if df is None:
                    continue
                df = fix_yf_columns(df).dropna()
                if len(df) < 2:
                    continue
                last = float(df["Close"].iloc[-1])
                prev = float(df["Close"].iloc[-2])
                change = ((last / prev) - 1) * 100
                changes.append(change)
            except Exception:
                continue
        if changes:
            sector_results.append({"sector": sector, "change": round(np.mean(changes), 2)})

    return sorted(sector_results, key=lambda x: x["change"], reverse=True)


async def get_top_gainers(tickers: list[str]) -> list[dict]:
    """Ranking saham berdasarkan perubahan harga harian (top gainer)."""
    data_by_ticker = await async_download_many(tickers, period="5d")
    results = []

    for ticker, df in data_by_ticker.items():
        try:
            df = fix_yf_columns(df).dropna()
            if len(df) < 2:
                continue
            last = float(df["Close"].iloc[-1])
            prev = float(df["Close"].iloc[-2])
            change = ((last / prev) - 1) * 100
            results.append({"ticker": ticker.replace(".JK", ""), "change": round(change, 2)})
        except Exception:
            continue

    return sorted(results, key=lambda x: x["change"], reverse=True)


async def get_top_volume(tickers: list[str]) -> list[dict]:
    """Ranking saham berdasarkan volume transaksi (top volume)."""
    data_by_ticker = await async_download_many(tickers, period="5d")
    results = []

    for ticker, df in data_by_ticker.items():
        try:
            df = fix_yf_columns(df).dropna()
            if df.empty:
                continue
            volume = float(df["Volume"].iloc[-1])
            results.append({"ticker": ticker.replace(".JK", ""), "volume": volume})
        except Exception:
            continue

    return sorted(results, key=lambda x: x["volume"], reverse=True)


async def get_top_losers(tickers: list[str]) -> list[dict]:
    """Ranking saham berdasarkan perubahan harga harian (top loser).
    FITUR BARU. Logic identik dengan get_top_gainers, cuma terurut
    ASCENDING (paling negatif duluan) bukan descending -- SENGAJA TIDAK
    menduplikasi logic download/parsing, cuma beda arah sort di akhir."""
    data_by_ticker = await async_download_many(tickers, period="5d")
    results = []

    for ticker, df in data_by_ticker.items():
        try:
            df = fix_yf_columns(df).dropna()
            if len(df) < 2:
                continue
            last = float(df["Close"].iloc[-1])
            prev = float(df["Close"].iloc[-2])
            change = ((last / prev) - 1) * 100
            results.append({"ticker": ticker.replace(".JK", ""), "change": round(change, 2)})
        except Exception:
            continue

    return sorted(results, key=lambda x: x["change"])  # ascending: paling negatif duluan


async def get_top_value(tickers: list[str]) -> list[dict]:
    """Ranking saham berdasarkan NILAI transaksi (harga x volume), BUKAN
    frekuensi transaksi. FITUR BARU -- PENGGANTI NAMA untuk /TOPFREQ
    yang awalnya diminta (lihat keputusan: data frekuensi transaksi/
    jumlah order matched TIDAK ADA di yfinance, cuma OHLCV standar --
    dikonfirmasi via riset web, bukan diasumsikan. Nilai transaksi BISA
    dihitung dari data yang ada, jadi /TOPFREQ diganti nama jadi
    /TOPVALUE sepenuhnya, bukan dua command terpisah)."""
    data_by_ticker = await async_download_many(tickers, period="5d")
    results = []

    for ticker, df in data_by_ticker.items():
        try:
            df = fix_yf_columns(df).dropna()
            if df.empty:
                continue
            close = float(df["Close"].iloc[-1])
            volume = float(df["Volume"].iloc[-1])
            value = close * volume
            results.append({"ticker": ticker.replace(".JK", ""), "value": value, "close": close, "volume": volume})
        except Exception:
            continue

    return sorted(results, key=lambda x: x["value"], reverse=True)
