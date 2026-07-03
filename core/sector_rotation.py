# =========================
# SEKTOR & ROTASI
# =========================
# FITUR BARU. /rotasi, /sektor, /leader, /laggard, /beta. Memakai 11
# indeks sektoral resmi IDX-IC (IDX_SECTORAL_INDICES di core/market.py
# -- lihat catatan jujur di sana soal batasan verifikasi: ticker-ticker
# ini TIDAK BISA dicoba eksekusi langsung di sandbox development,
# bukti yang dipakai bersifat tidak langsung dari riset web).
#
# /leader dan /laggard (saham terkuat/terlemah DI DALAM satu sektor)
# tetap dibatasi oleh SECTOR_MAP yang cuma berisi 21 saham dari 793
# total -- TIDAK ADA cara menghindari batasan ini tanpa membangun
# mapping saham-ke-sektor yang lebih lengkap (yang butuh sumber data
# terpisah, belum diriset/diputuskan). Setiap pesan /leader & /laggard
# WAJIB menyebutkan batasan ini secara jujur ke user.

import asyncio
import pandas as pd

from core.market import IDX_SECTORAL_INDICES, SECTOR_MAP, SECTOR_MAP_TO_INDEX


async def _download_with_retry(ticker: str, period: str = "3mo", interval: str = "1d",
                                  max_retries: int = 3, base_delay: float = 1.5):
    """Download dengan retry + exponential backoff -- Yahoo Finance sering
    membalas error 'Expecting value: line 1 column 1' saat rate-limited
    (dikonfirmasi sebagai isu umum yfinance, bukan bug di kode kita: lihat
    GitHub ranaroussi/yfinance issue #2179, #2520, #2521). Retry dengan
    jeda singkat sering berhasil karena rate limit Yahoo biasanya per-
    detik, bukan blokir permanen.

    Returns DataFrame (bisa kosong kalau semua percobaan gagal) -- TIDAK
    raise exception, supaya caller bisa lanjut ke ticker berikutnya."""
    from core.async_yf import async_download

    for attempt in range(max_retries):
        try:
            raw = await async_download(ticker, period=period, interval=interval, progress=False)
            if raw is not None and not raw.empty:
                return raw
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"⚠️ {ticker} gagal setelah {max_retries}x percobaan: {type(e).__name__}: {e}")

        if attempt < max_retries - 1:
            await asyncio.sleep(base_delay * (attempt + 1))  # 1.5s, 3s, 4.5s

    return pd.DataFrame()  # kosong setelah semua percobaan gagal


def calculate_beta(stock_df: pd.DataFrame, market_df: pd.DataFrame) -> dict | None:
    """Hitung Beta coefficient: Cov(return_saham, return_market) /
    Var(return_market) -- formula standar (dikonfirmasi dari riset,
    konsisten di semua sumber: Wall Street Mojo, CFI, Wall Street
    Oasis, dll).

    Memakai daily returns (bukan return kumulatif periode), karena
    beta secara definisi mengukur sensitivitas pergerakan HARIAN saham
    relatif ke market, bukan return total satu periode.

    Returns None kalau data tidak cukup atau index tidak bisa
    disejajarkan (align) sama sekali."""
    if len(stock_df) < 30 or len(market_df) < 30:
        return None

    stock_returns = stock_df["Close"].pct_change().dropna()
    market_returns = market_df["Close"].pct_change().dropna()

    # Sejajarkan kedua return series berdasarkan index (tanggal) yang
    # SAMA -- penting karena downloadnya terpisah, index belum pasti
    # identik (misal salah satu ada hari libur yang berbeda)
    aligned = pd.concat([stock_returns, market_returns], axis=1, join="inner")
    aligned.columns = ["stock", "market"]

    if len(aligned) < 20:
        return None

    covariance = aligned["stock"].cov(aligned["market"])
    market_variance = aligned["market"].var()

    if market_variance == 0:
        return None

    beta = covariance / market_variance

    if beta > 1.5:
        interpretasi = "SANGAT AGRESIF -- bergerak jauh lebih liar dari IHSG"
    elif beta > 1.1:
        interpretasi = "AGRESIF -- bergerak lebih kuat dari IHSG"
    elif beta > 0.9:
        interpretasi = "SEJALAN IHSG -- volatilitas mirip pasar"
    elif beta > 0.5:
        interpretasi = "DEFENSIF -- bergerak lebih tenang dari IHSG"
    elif beta >= 0:
        interpretasi = "SANGAT DEFENSIF -- hampir tidak terpengaruh gerakan IHSG"
    else:
        interpretasi = "BERLAWANAN ARAH -- cenderung naik saat IHSG turun (jarang terjadi)"

    return {
        "beta": round(float(beta), 2),
        "n_observations": len(aligned),
        "interpretasi": interpretasi,
    }


async def get_sector_performance(period_days: int = 5) -> list[dict]:
    """Hitung return semua 11 indeks sektoral dalam period_days terakhir.

    Download individual per ticker dengan retry+delay untuk menghindari
    rate-limit Yahoo Finance (lihat catatan di _download_with_retry)."""
    from core.stock_data import fix_yf_columns

    tickers = list(IDX_SECTORAL_INDICES.keys())
    results = []

    for idx, ticker in enumerate(tickers):
        try:
            raw = await _download_with_retry(ticker, period="3mo", interval="1d")

            if raw is None or raw.empty:
                print(f"⚠️ get_sector_performance: {ticker} tetap kosong setelah retry")
                continue

            df = fix_yf_columns(raw).apply(pd.to_numeric, errors="coerce").dropna()

            if len(df) < period_days + 1:
                print(f"⚠️ get_sector_performance: {ticker} cuma {len(df)} baris valid (butuh {period_days+1})")
                continue

            start_price = float(df["Close"].iloc[-(period_days + 1)])
            end_price = float(df["Close"].iloc[-1])
            return_pct = ((end_price / start_price) - 1) * 100

            results.append({
                "ticker": ticker,
                "nama_sektor": IDX_SECTORAL_INDICES[ticker],
                "return_pct": round(return_pct, 2),
            })
        except Exception as e:
            print(f"⚠️ get_sector_performance: {ticker} GAGAL -- {type(e).__name__}: {e}")
            continue

        # Delay kecil antar ticker (bukan cuma antar retry) supaya tidak
        # membombardir Yahoo Finance dengan 11 request beruntun
        if idx < len(tickers) - 1:
            await asyncio.sleep(0.5)

    if not results:
        print(f"❌ get_sector_performance: SEMUA {len(tickers)} ticker sektoral gagal didownload.")

    results.sort(key=lambda x: x["return_pct"], reverse=True)
    return results


async def get_sector_rotation(short_period: int = 5, long_period: int = 20) -> list[dict]:
    """Bandingkan performa sektor di 2 periode berbeda.

    Download individual per ticker dengan retry+delay untuk menghindari
    rate-limit Yahoo Finance."""
    from core.stock_data import fix_yf_columns

    tickers = list(IDX_SECTORAL_INDICES.keys())
    results = []

    for idx, ticker in enumerate(tickers):
        try:
            raw = await _download_with_retry(ticker, period="3mo", interval="1d")

            if raw is None or raw.empty:
                continue

            df = fix_yf_columns(raw).apply(pd.to_numeric, errors="coerce").dropna()

            if len(df) < long_period + 1:
                continue

            def _return_over(n):
                start = float(df["Close"].iloc[-(n + 1)])
                end = float(df["Close"].iloc[-1])
                return ((end / start) - 1) * 100

            return_short = _return_over(short_period)
            return_long = _return_over(long_period)
            momentum_shift = return_short - (return_long / (long_period / short_period))

            if return_short > 0 and momentum_shift > 1:
                fase = "🚀 AKSELERASI (momentum baru menguat)"
            elif return_short > 0 and return_long > 0:
                fase = "✅ KONSISTEN KUAT (sudah lama menguat)"
            elif return_short < 0 and return_long > 0:
                fase = "⚠️ MULAI MELEMAH (masih positif jangka panjang)"
            else:
                fase = "🔴 LEMAH (negatif di kedua periode)"

            results.append({
                "ticker": ticker,
                "nama_sektor": IDX_SECTORAL_INDICES[ticker],
                "return_short": round(return_short, 2),
                "return_long": round(return_long, 2),
                "momentum_shift": round(momentum_shift, 2),
                "fase": fase,
            })
        except Exception as e:
            print(f"⚠️ get_sector_rotation: {ticker} GAGAL -- {type(e).__name__}: {e}")
            continue

        if idx < len(tickers) - 1:
            await asyncio.sleep(0.5)

    results.sort(key=lambda x: x["momentum_shift"], reverse=True)
    return results


async def get_leader_laggard(sector_key: str, top_n: int = 3) -> dict | None:
    """Saham terkuat (leader) & terlemah (laggard) di dalam satu sektor.
    Download individual per ticker dengan retry untuk rate-limit Yahoo Finance."""
    from core.stock_data import fix_yf_columns

    sector_key_upper = sector_key.upper()
    if sector_key_upper not in SECTOR_MAP:
        return None

    tickers = SECTOR_MAP[sector_key_upper]
    results = []

    for idx, ticker in enumerate(tickers):
        try:
            raw = await _download_with_retry(ticker, period="2mo", interval="1d")
            if raw is None or raw.empty:
                continue
            df = fix_yf_columns(raw).apply(pd.to_numeric, errors="coerce").dropna()
            if len(df) < 21:
                continue
            start_price = float(df["Close"].iloc[-21])
            end_price = float(df["Close"].iloc[-1])
            return_pct = ((end_price / start_price) - 1) * 100
            results.append({"ticker": ticker.replace(".JK", ""), "return_pct": round(return_pct, 2)})
        except Exception:
            continue

        if idx < len(tickers) - 1:
            await asyncio.sleep(0.5)

    if not results:
        return None

    results.sort(key=lambda x: x["return_pct"], reverse=True)

    # Konteks tambahan: return indeks sektoral resmi
    sector_index_ticker = SECTOR_MAP_TO_INDEX.get(sector_key_upper)
    sector_index_return = None
    if sector_index_ticker:
        try:
            raw_idx = await _download_with_retry(sector_index_ticker, period="2mo", interval="1d")
            index_df = fix_yf_columns(raw_idx).apply(pd.to_numeric, errors="coerce").dropna()
            if len(index_df) >= 21:
                idx_start = float(index_df["Close"].iloc[-21])
                idx_end = float(index_df["Close"].iloc[-1])
                sector_index_return = round(((idx_end / idx_start) - 1) * 100, 2)
        except Exception:
            sector_index_return = None

    leader = results[:top_n]
    # Laggard TIDAK BOLEH tumpang tindih dengan leader -- ditemukan nyata:
    # SECTOR_MAP saat ini cuma berisi 3-4 saham per sektor, jadi dengan
    # top_n=3 default, results[-top_n:] dan results[:top_n] overlap
    # SEBAGIAN (sektor 4 saham) atau TOTAL (sektor 3 saham) -- membuat
    # saham yang SAMA muncul sebagai "leader" sekaligus "laggard" di
    # sektor yang sama. Filter laggard supaya cuma berisi saham yang
    # BUKAN sudah masuk leader (kalau saham tersisa lebih sedikit dari
    # top_n, laggard cukup sependek itu -- lebih jujur daripada memaksa
    # duplikat).
    leader_tickers = {r["ticker"] for r in leader}
    laggard = [r for r in reversed(results) if r["ticker"] not in leader_tickers][:top_n]

    return {
        "sector_key": sector_key_upper,
        "total_saham_di_sektor_ini": len(results),
        "leader": leader,
        "laggard": laggard,
        "sector_index_ticker": sector_index_ticker,
        "sector_index_return": sector_index_return,
    }
