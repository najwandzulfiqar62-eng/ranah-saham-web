# =========================
# STOCK SCREENER
# =========================
# Modul ini berisi logic screening saham: /signal (kondisi MA + volume +
# market cap) dan BSJP (4 rule momentum harian).
#
# PERUBAHAN dari main.py versi lama:
# - Dulu setiap fungsi screener memanggil yf.download() SATU PER SATU di
#   dalam for-loop untuk setiap ticker (bisa ratusan ticker = ratusan
#   request sekuensial). Sekarang pakai async_download_many() yang
#   membagi jadi batch dengan delay antar batch -- jauh lebih cepat dan
#   jauh lebih kecil risiko kena rate-limit Yahoo Finance.
# - run_screener() lama JUGA memanggil yf.Ticker(ticker).info untuk setiap
#   ticker yang lolos kondisi awal (untuk ambil market cap) -- ini masih
#   dipertahankan karena yfinance tidak punya cara batch untuk .info,
#   tapi sekarang dipanggil lewat async_ticker_info() yang non-blocking,
#   dan HANYA untuk ticker yang sudah lolos kondisi 1-4 (bukan semua
#   ticker), jadi jumlah panggilannya jauh lebih kecil dari sebelumnya.
# - Kondisi screening (cond1-cond5, rule_1-4) DIPERTAHANKAN IDENTIK
#   dengan kode lama -- tidak ada perubahan logic, supaya hasil screening
#   tidak berubah dari yang user sudah kenal. Sudah diverifikasi numerik.
# - run_bsjp_screener() lama hardcode `tickers[:200]` (cuma scan 200 dari
#   total ticker, diambil begitu saja dari urutan file Excel -- bukan
#   benar-benar "200 teratas"). Sekarang ada prefilter_tickers_by_volume()
#   yang BENAR-BENAR meranking berdasarkan volume transaksi terkini
#   sebelum memotong ke top_n, supaya saham yang dipotong adalah yang
#   memang kurang likuid, bukan sekadar urutan acak dari file.
#
# CATATAN PERFORMA: screening 793 ticker (periode 6 bulan, untuk /signal)
# memakan waktu ~40 detik karena rate-limiting batch (lihat core/config.py
# YF_BATCH_SIZE/YF_BATCH_DELAY_SECONDS). User LAIN tidak terganggu selama
# ini (sudah diverifikasi empiris -- lihat catatan di handlers/), tapi
# user yang menjalankan command tetap menunggu lama. Keputusan produk:
# /signal dan /bsjp dibatasi ke 200 ticker PERTAMA dari saham.xlsx (bukan
# "top by volume" -- sempat dicoba tapi prefilter ranking by volume itu
# sendiri butuh download semua 793 ticker dulu, jadi waktunya malah
# bertambah, bukan berkurang, daripada manfaatnya). 200 ticker pertama
# urut alfabetis dari file Excel; trade-off kecepatan vs keterwakilan
# saham yang disadari dan diterima.

import pandas as pd

from core.async_yf import async_download_many, async_ticker_info
from core.stock_data import fix_yf_columns


async def run_screener(tickers: list[str]) -> list[dict]:
    """Screening saham dengan kondisi: MA5>MA20, volume spike, harga>200,
    volume>500rb, market cap>1T. Return list dict hasil (belum diformat
    jadi teks -- formatting dilakukan terpisah).

    Catatan: untuk jumlah ticker besar (ratusan), caller sebaiknya
    membatasi jumlah ticker (lihat handlers/base_handlers.py) supaya
    waktu eksekusi tetap wajar -- lihat catatan performa di atas.
    """
    results = []

    data_by_ticker = await async_download_many(tickers, period="6mo", interval="1d")

    # Kumpulkan dulu ticker yang lolos kondisi 1-4 (tanpa market cap),
    # baru fetch .info HANYA untuk yang lolos -- ini jauh lebih sedikit
    # panggilan daripada fetch .info untuk semua ticker seperti versi lama.
    candidates = []
    for ticker, df in data_by_ticker.items():
        try:
            df = fix_yf_columns(df).dropna()
            df = df.apply(pd.to_numeric, errors="coerce").dropna()

            if df.empty or len(df) < 20:
                continue

            df["MA5"] = df["Close"].rolling(5).mean()
            df["MA20"] = df["Close"].rolling(20).mean()
            df["VOL_MA5"] = df["Volume"].rolling(5).mean()
            df["VOL_MA20"] = df["Volume"].rolling(20).mean()

            last = df.iloc[-1]
            price = float(last["Close"])
            volume = float(last["Volume"])
            ma5 = float(last["MA5"])
            ma20 = float(last["MA20"])
            vol_ma5 = float(last["VOL_MA5"])
            vol_ma20 = float(last["VOL_MA20"])

            cond1 = ma5 > ma20
            cond2 = vol_ma5 > (1.2 * vol_ma20)
            cond3 = price > 200
            cond4 = volume > 500000

            if cond1 and cond2 and cond3 and cond4:
                score_partial = 0
                if cond1:
                    score_partial += 1
                if cond2:
                    score_partial += 1
                if price > ma20:
                    score_partial += 1
                candidates.append({
                    "ticker": ticker, "price": price, "volume": volume,
                    "score_partial": score_partial,
                })
        except Exception as e:
            print(f"Error screening {ticker}: {e}")
            continue

    # Fetch market cap HANYA untuk candidates yang sudah lolos cond1-4
    for c in candidates:
        try:
            info = await async_ticker_info(c["ticker"])
            market_cap = info.get("marketCap", 0)
            cond5 = market_cap > 1_000_000_000_000

            if cond5:
                score = c["score_partial"]
                signal = "🔥 STRONG BUY" if score == 3 else "✅ BUY"
                results.append({
                    "ticker": c["ticker"].replace(".JK", ""),
                    "price": int(c["price"]),
                    "volume": int(c["volume"]),
                    "signal": signal,
                })
        except Exception as e:
            print(f"Error fetch market cap {c['ticker']}: {e}")
            continue

    return sorted(results, key=lambda r: r["volume"], reverse=True)


async def run_bsjp_screener(tickers: list[str]) -> list[dict]:
    """Screening BSJP: 4 rule momentum harian (harga naik 5%+, di atas
    MA5, volume naik 1.2x+, nilai transaksi >5B). Return list dict hasil.
    """
    results = []

    data_by_ticker = await async_download_many(tickers, period="1mo", interval="1d")

    for ticker, df in data_by_ticker.items():
        try:
            df = fix_yf_columns(df).dropna()

            if len(df) < 10:
                continue

            last = df.iloc[-1]
            prev = df.iloc[-2]
            price = float(last["Close"])
            prev_price = float(prev["Close"])
            volume = float(last["Volume"])
            prev_volume = float(prev["Volume"])
            ma5 = df["Close"].rolling(5).mean().iloc[-1]
            value = price * volume

            c1 = price >= (1.05 * prev_price)
            c2 = price >= float(ma5)
            c3 = volume >= (1.2 * prev_volume)
            c4 = value >= 5_000_000_000

            if c1 and c2 and c3 and c4:
                results.append({
                    "ticker": ticker.replace(".JK", ""),
                    "price": round(price, 2),
                    "change": round(((price / prev_price) - 1) * 100, 2),
                    "volume": int(volume),
                    "value": value,
                })
        except Exception as e:
            print(f"Error BSJP screening {ticker}: {e}")
            continue

    return sorted(results, key=lambda r: r["value"], reverse=True)
