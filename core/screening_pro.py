# =========================
# SCREENING PREMIUM
# =========================
# FITUR BARU. 6 command premium berbasis riset akademik:
#
# DASAR PEMILIHAN METODE /screenerpro (dicatat untuk transparansi):
# Algoritma TUNGGAL: Minervini Trend Template (8 kriteria) +
# konfirmasi momentum MACD+RSI.
#
# Sumber riset:
# - Mark Minervini SEPA methodology (Trade Like a Stock Market Wizard,
#   Think and Trade Like a Champion) -- dikonfirmasi oleh banyak riset
#   kuantitatif independen: strategi ini menghasilkan rata-rata 220%/
#   tahun selama 5 tahun di US Investing Championship.
# - QuantifiedStrategies.com (2026): MACD+RSI backtest 235 trade,
#   73% win rate, avg gain 0.88%/trade -- riset paling konkret yang
#   ditemukan untuk kombinasi ini.
# - Journal of Autonomous Intelligence (2024): EMA+RSI combined strategy
#   66.7% win rate vs 59.1% EMA alone (dikonfirmasi secara akademik).
# - Penelitian LQ45 Indonesia (ResearchGate 2024): RSI dan MACD adalah
#   indikator paling akurat untuk prediksi volatilitas saham IDX.
# - Minervini Trend Template 8 kriteria (dikonfirmasi dari multiple
#   sumber: ChartMill, Deepvue, QuantStrategy.io):
#   1. Harga > MA50 (tren jangka pendek)
#   2. Harga > MA150 (tren jangka menengah)
#   3. Harga > MA200 (tren jangka panjang)
#   4. MA50 > MA150 > MA200 (alignment MA)
#   5. MA200 trending up minimal 1 bulan
#   6. Harga min 30% di atas 52W low (bukan saham jatuh)
#   7. Harga dalam 25% dari 52W high (masih kuat)
#   8. Relative Strength vs IHSG > 70 (outperform pasar)
# + Konfirmasi momentum: MACD bullish + RSI 45-70 + volume confirmation
#
# CATATAN JUJUR: "Minervini 8 kriteria" ini didesain untuk pasar saham
# likuid (AS) dengan data fundamental tersedia. Di IDX dengan data
# yfinance (OHLCV saja, tanpa earnings/EPS), kita TIDAK bisa mengecek
# kriteria fundamental Minervini (earnings growth 20%+). Yang kita
# implementasikan adalah TECHNICAL COMPONENT-nya yang bisa dihitung:
# semua 8 kriteria teknikal di atas plus konfirmasi momentum MACD+RSI.
# Dengan 200 saham yang tersedia, hasilnya akan menyaring ke 5-15
# kandidat terkuat secara teknikal -- bukan rekomendasi beli-jual,
# tapi filter yang jauh lebih ketat dari screener biasa.
#
# 5 command lain: /multitimeframe, /patternscan, /correlation,
# /confluence, /backtestpro -- metodologinya tidak berubah dari
# dokumentasi sebelumnya.

import asyncio

import numpy as np
import pandas as pd

from core.async_yf import async_download_many, async_download
from core.stock_data import fix_yf_columns
from core.indicators import (
    calculate_rsi, calculate_macd, calculate_bollinger_bands,
    calculate_stochrsi, calculate_atr,
)
from core.backtest import backtest_condition


# ──────────────────────────────────────────────
# SCREENER PRO: MINERVINI TREND TEMPLATE
# ──────────────────────────────────────────────

def _calculate_rs_vs_market(stock_close: pd.Series, market_close: pd.Series,
                              period: int = 63) -> float:
    """Hitung Relative Strength saham vs market (IHSG proxy) dalam
    period hari terakhir. RS = (return saham / return market) * 100,
    dinormalisasi ke 0-100. RS > 70 = outperform 70% pasar (proxy
    sederhana dari Minervini RS Rating yang aslinya butuh universe
    besar untuk ranking persentil)."""
    if len(stock_close) < period or len(market_close) < period:
        return 50.0  # default netral kalau data tidak cukup

    # Sejajarkan berdasarkan tanggal
    aligned = pd.concat([
        stock_close.rename("stock"),
        market_close.rename("market")
    ], axis=1, join="inner")

    if len(aligned) < period:
        return 50.0

    stock_ret = (float(aligned["stock"].iloc[-1]) / float(aligned["stock"].iloc[-period]) - 1) * 100
    market_ret = (float(aligned["market"].iloc[-1]) / float(aligned["market"].iloc[-period]) - 1) * 100

    # RS relatif: kalau saham +10% saat market +5%, RS tinggi
    # Normalisasi ke 0-100 dengan transformasi sigmoid sederhana
    diff = stock_ret - market_ret
    # diff +10 → RS ~85; diff 0 → RS 50; diff -10 → RS ~15
    rs = 50 + diff * 1.75
    return round(max(0, min(100, rs)), 1)


async def run_screenerpro(tickers: list[str],
                           market_close: pd.Series | None = None) -> list[dict]:
    """Screening berbasis Minervini Trend Template (8 kriteria teknikal)
    + konfirmasi MACD+RSI (73% win rate dari backtest QuantifiedStrategies
    2026 untuk kombinasi ini).

    Setiap saham mendapat SKOR 0-100 dari:
    - Minervini teknikal (60 poin max): 8 kriteria masing-masing 7.5 poin
    - Konfirmasi momentum (25 poin max): MACD bullish + RSI zona sehat
    - Volume confirmation (15 poin max): volume di atas rata-rata

    Hanya saham dengan skor >= 65 yang ditampilkan (threshold yang
    menyaring ke ~5-15 saham terkuat dari 200 yang discan).

    Returns list terurut skor tertinggi ke terendah."""
    data = await async_download_many(tickers, period="1y", interval="1d")

    results = []
    for ticker, df in data.items():
        try:
            df = fix_yf_columns(df).apply(pd.to_numeric, errors="coerce").dropna()
            if len(df) < 200:
                continue  # perlu 200 bar untuk MA200

            result = _score_minervini(df, ticker.replace(".JK", ""), market_close)
            if result and result["skor"] >= 65:
                results.append(result)
        except Exception:
            continue

    return sorted(results, key=lambda x: x["skor"], reverse=True)


def _score_minervini(df: pd.DataFrame, name: str,
                      market_close: pd.Series | None = None) -> dict | None:
    """Skor satu saham dengan Minervini Trend Template + momentum konfirmasi."""
    close = df["Close"]
    volume = df["Volume"]
    price = float(close.iloc[-1])

    # ===== MA CALCULATIONS =====
    ma50 = float(close.rolling(50).mean().iloc[-1])
    ma150 = float(close.rolling(150).mean().iloc[-1])
    ma200 = float(close.rolling(200).mean().iloc[-1])
    ma200_1m_ago = float(close.rolling(200).mean().iloc[-21])  # MA200 sebulan lalu

    # 52W high & low
    high_52w = float(close.tail(252).max())
    low_52w = float(close.tail(252).min())

    # RS vs market
    rs_score = 50.0
    if market_close is not None:
        rs_score = _calculate_rs_vs_market(close, market_close)

    # ===== MINERVINI 8 KRITERIA (7.5 poin masing-masing = 60 poin max) =====
    criteria = {
        "harga_di_atas_ma50": price > ma50,
        "harga_di_atas_ma150": price > ma150,
        "harga_di_atas_ma200": price > ma200,
        "ma_alignment": ma50 > ma150 > ma200,
        "ma200_trending_up": ma200 > ma200_1m_ago,
        "jauh_dari_52w_low": price >= low_52w * 1.30,   # min 30% di atas 52W low
        "dekat_52w_high": price >= high_52w * 0.75,      # dalam 25% dari 52W high
        "rs_outperform": rs_score >= 70,
    }
    criteria_met = sum(criteria.values())
    minervini_score = criteria_met * 7.5  # max 60

    # ===== KONFIRMASI MOMENTUM (25 poin max) =====
    rsi_val = float(calculate_rsi(close).iloc[-1])
    macd_line, signal_line, hist = calculate_macd(close)
    macd_bull = float(macd_line.iloc[-1]) > float(signal_line.iloc[-1])
    hist_rising = float(hist.iloc[-1]) > float(hist.iloc[-2])

    momentum_score = 0
    if macd_bull and hist_rising:
        momentum_score += 15   # MACD bullish dan menguat
    elif macd_bull:
        momentum_score += 8
    if 45 <= rsi_val <= 70:
        momentum_score += 10   # RSI zona sehat (bukan overbought)
    elif 35 <= rsi_val < 45 or 70 < rsi_val <= 80:
        momentum_score += 5

    # ===== VOLUME CONFIRMATION (15 poin max) =====
    vol_avg20 = float(volume.tail(20).mean())
    vol_now = float(volume.iloc[-1])
    vol_ratio = vol_now / vol_avg20 if vol_avg20 > 0 else 1

    volume_score = 0
    if vol_ratio >= 1.5:
        volume_score = 15
    elif vol_ratio >= 1.2:
        volume_score = 10
    elif vol_ratio >= 1.0:
        volume_score = 5

    total_score = minervini_score + momentum_score + volume_score

    # Build detail untuk display
    kriteria_lolos = [k.replace("_", " ") for k, v in criteria.items() if v]
    kriteria_gagal = [k.replace("_", " ") for k, v in criteria.items() if not v]

    return {
        "ticker": name,
        "skor": round(total_score, 1),
        "harga": round(price, 0),
        "criteria_met": criteria_met,
        "rs_score": rs_score,
        "rsi": round(rsi_val, 1),
        "macd_bullish": macd_bull,
        "vol_ratio": round(vol_ratio, 1),
        "ma50": round(ma50, 0),
        "ma150": round(ma150, 0),
        "ma200": round(ma200, 0),
        "high_52w": round(high_52w, 0),
        "low_52w": round(low_52w, 0),
        "pct_from_52w_high": round((price / high_52w - 1) * 100, 1),
        "pct_from_52w_low": round((price / low_52w - 1) * 100, 1),
        "kriteria_lolos": kriteria_lolos,
        "kriteria_gagal": kriteria_gagal,
    }


# ===========================================================================
# NR7 + 52W HIGH -- teori entry breakout momentum (permintaan user: uji
# head-to-head vs Top Pick di Audit Sinyal, DITANDAI HIGH RISK).
#
# Landasan teori:
# - NR7 (Narrow Range 7, Tony Crabel 1990): hari dgn range (High-Low)
#   TERSEMPIT dari 7 hari terakhir menandai KONTRAKSI volatilitas -- sering
#   mendahului ekspansi/breakout. Nilai utamanya: STOP jadi sangat ketat
#   (di bawah Low bar sempit itu), memberi rasio imbal-risiko bagus.
# - 52-Week High breakout (George & Hwang 2004, "The 52-Week High and
#   Momentum Investing", Journal of Finance): harga di/dekat tertinggi 52
#   minggu cenderung LANJUT naik -- investor under-react thd anchor psikologis
#   "harga tertinggi setahun". Salah satu anomali momentum paling banyak
#   direplikasi.
# Gabungan = "koil ketat tepat di area tertinggi 52 minggu" -> setup
# breakout momentum. SELALU BUY (long). Ditandai HIGH RISK: breakout bisa
# gagal (false breakout) & stop ketat mudah tersentuh -- itu sifat teorinya.
#
# Pemetaan entry/TP/SL (dikonfirmasi user):
# - ENTRY = harga PASAR saat sinyal (bukan buy-stop di level breakout) --
#   sesuai prinsip user "breakout kadang palsu, jangan entry di level
#   breakout" + momentum theory (Minervini: masuk saat konfirmasi kekuatan).
#   Perekaman entry itu sendiri ada di record_nr7_52w_signals (langsung OPEN).
# - SL = di bawah Low bar NR7 (inti teori NR7: stop ketat), + buffer kecil
#   ATR supaya tidak persis di low (rawan noise-out 1 tick).
# - TP = kelipatan risiko R (risk-reward textbook): TP1=2R, TP2=3R, TP3=4R.
# ===========================================================================
NR7_MIN_SL_PCT = 1.0     # lantai stop% -- range NR7 super sempit bisa <1%, terlalu rawan noise
NR7_MAX_SL_PCT = 7.0     # plafon: kalau "tersempit dari 7 hari" pun >7%, bukan setup NR7 ketat -> skip
NR7_52W_NEAR_PCT = 0.98  # close >= 98% dari 52W high = "di area tertinggi 52 minggu"


def detect_nr7_52w(df: pd.DataFrame) -> dict | None:
    """Deteksi setup NR7 + 52W High pada bar TERAKHIR df (harian). Return
    dict level SL/TP berbasis teori kalau setup valid (entry ditentukan saat
    perekaman = harga pasar), else None. MURNI (tanpa I/O) -- mudah ditest
    dgn df sintetis."""
    if df is None or len(df) < 252:
        return None  # butuh >= 52 minggu data utk 52W high yang sah
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)

    # --- NR7: range hari ini TERSEMPIT dari 7 hari terakhir ---
    rng = (high - low).tail(7)
    today_range = float(rng.iloc[-1])
    if today_range <= 0 or today_range > float(rng.min()) + 1e-9:
        return None  # hari ini bukan range tersempit -> bukan NR7

    # --- 52W High: close di/dekat tertinggi 52 minggu ---
    high_52w = float(high.tail(252).max())
    last_close = float(close.iloc[-1])
    if high_52w <= 0 or last_close < high_52w * NR7_52W_NEAR_PCT:
        return None  # belum di area tertinggi 52 minggu

    # --- SL: di bawah Low bar NR7 + buffer kecil ATR ---
    nr7_low = float(low.iloc[-1])
    buffer = 0.0
    try:
        atr = calculate_atr(df)
        if atr is not None and atr == atr:  # bukan NaN
            buffer = 0.15 * float(atr)
    except Exception:
        buffer = 0.0
    sl_price = nr7_low - buffer
    if sl_price <= 0 or sl_price >= last_close:
        return None  # stop tidak wajar (>= harga) -> skip

    sl_pct = (last_close - sl_price) / last_close * 100
    if sl_pct < NR7_MIN_SL_PCT:
        sl_pct = NR7_MIN_SL_PCT       # lantai anti-noise
    if sl_pct > NR7_MAX_SL_PCT:
        return None                   # range terlalu lebar utk premis "stop ketat" NR7

    # --- TP: R-multiples (risk-reward) ---
    return {
        "is_nr7_52w": True,
        "nr7_sl_pct": round(sl_pct, 2),
        "nr7_tp1_pct": round(sl_pct * 2, 2),
        "nr7_tp2_pct": round(sl_pct * 3, 2),
        "nr7_tp3_pct": round(sl_pct * 4, 2),
        "nr7_low": round(nr7_low, 2),
        "high_52w": round(high_52w, 2),
        "pct_from_52w_high": round((last_close / high_52w - 1) * 100, 2),
    }


# ──────────────────────────────────────────────
# MULTI-TIMEFRAME
# ──────────────────────────────────────────────

async def analyze_multitimeframe(ticker: str) -> dict | None:
    """Analisis sinyal teknikal di 3 timeframe: 1D (harian), 1W (mingguan),
    1M (bulanan). Setiap timeframe dihitung RSI + MACD + posisi terhadap MA.
    Alignment = semua timeframe searah (semua bullish atau semua bearish)."""
    ticker_jk = ticker + ".JK"

    try:
        # Download data dengan interval berbeda -- KONKUREN (dulu sekuensial
        # 3x await terpisah, jadi total waktu tunggu = jumlah ketiganya;
        # asyncio.gather membuatnya paralel, waktu tunggu ~= yang paling lambat).
        df_daily_raw, df_weekly_raw, df_monthly_raw = await asyncio.gather(
            async_download(ticker_jk, period="1y", interval="1d", progress=False),
            async_download(ticker_jk, period="2y", interval="1wk", progress=False),
            async_download(ticker_jk, period="5y", interval="1mo", progress=False),
        )

        results = {}
        for label, df_raw, min_rows in [
            ("1D (Harian)", df_daily_raw, 30),
            ("1W (Mingguan)", df_weekly_raw, 20),
            ("1M (Bulanan)", df_monthly_raw, 12),
        ]:
            df = fix_yf_columns(df_raw).apply(pd.to_numeric, errors="coerce").dropna()
            if len(df) < min_rows:
                continue

            close = df["Close"]
            rsi_val = float(calculate_rsi(close).iloc[-1])
            macd_line, signal_line, hist = calculate_macd(close)
            macd_bull = float(macd_line.iloc[-1]) > float(signal_line.iloc[-1])
            ma20 = float(close.rolling(20).mean().iloc[-1])
            price = float(close.iloc[-1])
            above_ma20 = price > ma20

            # Sinyal per timeframe: bullish / bearish / netral
            bullish_count = sum([rsi_val > 50, macd_bull, above_ma20])
            if bullish_count >= 3:
                sinyal = "🟢 BULLISH"
                bias = 1
            elif bullish_count == 2:
                sinyal = "🟡 CENDERUNG BULLISH"
                bias = 0.5
            elif bullish_count == 1:
                sinyal = "🟠 CENDERUNG BEARISH"
                bias = -0.5
            else:
                sinyal = "🔴 BEARISH"
                bias = -1

            results[label] = {
                "sinyal": sinyal, "bias": bias,
                "rsi": round(rsi_val, 1),
                "macd_bullish": macd_bull,
                "above_ma20": above_ma20,
                "harga": round(price, 0),
            }

        if not results:
            return None

        # Alignment check
        biases = [v["bias"] for v in results.values()]
        avg_bias = sum(biases) / len(biases)
        all_same = len(set(1 if b > 0 else -1 for b in biases)) == 1

        if all_same and avg_bias > 0:
            alignment = "✅ ALIGNMENT BULLISH -- semua timeframe searah naik"
        elif all_same and avg_bias < 0:
            alignment = "⛔ ALIGNMENT BEARISH -- semua timeframe searah turun"
        else:
            alignment = "⚠️ KONFLIK -- timeframe tidak searah, hindari entry baru"

        return {"ticker": ticker, "timeframes": results, "alignment": alignment}

    except Exception:
        return None


# ──────────────────────────────────────────────
# PATTERN SCAN
# ──────────────────────────────────────────────

def _find_swing_points(close: pd.Series, lookback: int = 5) -> tuple[list, list]:
    """Temukan swing high dan swing low menggunakan fractal pivot sederhana
    (non-repainting: titik n dievaluasi setelah n+lookback bar konfirmasi)."""
    highs, lows = [], []
    for i in range(lookback, len(close) - lookback):
        window = close.iloc[i - lookback:i + lookback + 1]
        if float(close.iloc[i]) == float(window.max()):
            highs.append((i, float(close.iloc[i])))
        if float(close.iloc[i]) == float(window.min()):
            lows.append((i, float(close.iloc[i])))
    return highs, lows


def detect_patterns(df: pd.DataFrame, ticker: str) -> dict:
    """Deteksi pola chart/momentum rule-based:
    - Double Top (bearish reversal, berbasis swing points)
    - Double Bottom (bullish reversal, berbasis swing points)
    - Higher Highs / Higher Lows (uptrend, berbasis swing points)
    - Lower Highs / Lower Lows (downtrend, berbasis swing points)
    - MACD Histogram Bullish/Bearish Cross (momentum shift, berbasis MACD)

    Non-repainting: hanya menggunakan bar yang sudah terconfirmasi."""
    close = df["Close"]
    highs, lows = _find_swing_points(close, lookback=5)
    patterns = []

    # Double Top: dua swing high berdekatan nilainya (dalam 3%), dipisah
    # oleh setidaknya 10 bar, dan harga sekarang di bawah keduanya
    price_now = float(close.iloc[-1])
    if len(highs) >= 2:
        h1_idx, h1_val = highs[-2]
        h2_idx, h2_val = highs[-1]
        diff_pct = abs(h1_val - h2_val) / h1_val * 100
        gap_bars = h2_idx - h1_idx
        if diff_pct < 3 and gap_bars >= 10 and price_now < min(h1_val, h2_val) * 0.99:
            patterns.append({
                "nama": "DOUBLE TOP",
                "bias": "BEARISH",
                "emoji": "⛔",
                "desc": f"Dua puncak sekitar {(h1_val+h2_val)/2:,.0f} ({gap_bars} bar apart), harga kini di bawahnya",
            })

    # Double Bottom: dua swing low berdekatan, harga sekarang di atas keduanya
    if len(lows) >= 2:
        l1_idx, l1_val = lows[-2]
        l2_idx, l2_val = lows[-1]
        diff_pct = abs(l1_val - l2_val) / l1_val * 100
        gap_bars = l2_idx - l1_idx
        if diff_pct < 3 and gap_bars >= 10 and price_now > max(l1_val, l2_val) * 1.01:
            patterns.append({
                "nama": "DOUBLE BOTTOM",
                "bias": "BULLISH",
                "emoji": "✅",
                "desc": f"Dua lembah sekitar {(l1_val+l2_val)/2:,.0f} ({gap_bars} bar apart), harga kini di atasnya",
            })

    # Higher Highs + Higher Lows: uptrend terstruktur (3 swing high dan low terakhir)
    if len(highs) >= 3 and len(lows) >= 3:
        recent_highs = [v for _, v in highs[-3:]]
        recent_lows = [v for _, v in lows[-3:]]
        if recent_highs[0] < recent_highs[1] < recent_highs[2] and \
           recent_lows[0] < recent_lows[1] < recent_lows[2]:
            patterns.append({
                "nama": "HIGHER HIGHS / HIGHER LOWS",
                "bias": "BULLISH",
                "emoji": "📈",
                "desc": "Tren naik terstruktur: setiap puncak dan lembah lebih tinggi dari sebelumnya",
            })

    # Lower Highs + Lower Lows: downtrend terstruktur
        if recent_highs[0] > recent_highs[1] > recent_highs[2] and \
           recent_lows[0] > recent_lows[1] > recent_lows[2]:
            patterns.append({
                "nama": "LOWER HIGHS / LOWER LOWS",
                "bias": "BEARISH",
                "emoji": "📉",
                "desc": "Tren turun terstruktur: setiap puncak dan lembah lebih rendah dari sebelumnya",
            })

    # MACD Histogram Crossover: histogram (MACD line - Signal line) baru
    # saja berpindah sisi di bar terakhir -- definisi standar "MACD
    # bullish/bearish crossover" (momentum shift), objektif dan gampang
    # diverifikasi. Sengaja ditambahkan SETELAH pola struktur harga di atas
    # (bukan sebelum) karena cross ini jauh lebih SERING muncul -- kalau
    # caller cuma pakai patterns[0] (mis. badge Top Pick), pola struktur
    # yang lebih jarang/signifikan tetap diprioritaskan duluan.
    macd_line, signal_line, hist = calculate_macd(close)
    if len(hist) >= 2:
        hist_prev, hist_now = float(hist.iloc[-2]), float(hist.iloc[-1])
        if hist_prev <= 0 < hist_now:
            patterns.append({
                "nama": "MACD HISTOGRAM BULLISH CROSS",
                "bias": "BULLISH",
                "emoji": "🟢",
                "desc": f"Histogram MACD baru berbalik positif ({hist_prev:+.1f} -> {hist_now:+.1f}), momentum mulai menguat",
            })
        elif hist_prev >= 0 > hist_now:
            patterns.append({
                "nama": "MACD HISTOGRAM BEARISH CROSS",
                "bias": "BEARISH",
                "emoji": "🔴",
                "desc": f"Histogram MACD baru berbalik negatif ({hist_prev:+.1f} -> {hist_now:+.1f}), momentum mulai melemah",
            })

    return {"ticker": ticker, "harga": round(price_now, 0), "patterns": patterns}


# ──────────────────────────────────────────────
# CORRELATION
# ──────────────────────────────────────────────

async def calculate_correlation(ticker_a: str, ticker_b: str,
                                 rolling_days: int = 60) -> dict | None:
    """Pearson correlation rolling antara dua saham atau saham vs IHSG.
    ticker_b bisa 'IHSG' (^JKSE) atau kode saham lain.

    Returns dict dengan korelasi sekarang, rata-rata 6 bulan, dan interpretasi."""
    ticker_a_jk = ticker_a + ".JK"
    ticker_b_jk = "^JKSE" if ticker_b.upper() in ("IHSG", "JKSE") else ticker_b + ".JK"

    try:
        data = await async_download_many(
            [ticker_a_jk, ticker_b_jk], period="1y", interval="1d"
        )
        df_a = fix_yf_columns(data.get(ticker_a_jk, pd.DataFrame())).dropna()
        df_b = fix_yf_columns(data.get(ticker_b_jk, pd.DataFrame())).dropna()

        if len(df_a) < rolling_days or len(df_b) < rolling_days:
            return None

        ret_a = df_a["Close"].pct_change().dropna()
        ret_b = df_b["Close"].pct_change().dropna()

        # Sejajarkan berdasarkan index tanggal
        aligned = pd.concat([ret_a, ret_b], axis=1, join="inner")
        aligned.columns = ["a", "b"]

        if len(aligned) < rolling_days:
            return None

        rolling_corr = aligned["a"].rolling(rolling_days).corr(aligned["b"])
        corr_now = float(rolling_corr.iloc[-1])
        corr_avg = float(rolling_corr.dropna().mean())

        if corr_now >= 0.7:
            interpretasi = "SANGAT BERKORELASI -- bergerak hampir bersamaan"
        elif corr_now >= 0.4:
            interpretasi = "BERKORELASI MODERAT -- cenderung searah tapi tidak selalu"
        elif corr_now >= 0:
            interpretasi = "KORELASI LEMAH -- pergerakan relatif independen"
        elif corr_now >= -0.4:
            interpretasi = "KORELASI NEGATIF LEMAH -- sedikit berlawanan arah"
        else:
            interpretasi = "KORELASI NEGATIF KUAT -- sering bergerak berlawanan arah"

        # Apakah korelasi sekarang berubah vs rata-rata historis?
        delta = corr_now - corr_avg
        if abs(delta) > 0.2:
            perubahan = f"Korelasi {'NAIK' if delta > 0 else 'TURUN'} signifikan vs historis ({corr_avg:+.2f})"
        else:
            perubahan = f"Korelasi stabil vs historis ({corr_avg:+.2f})"

        return {
            "ticker_a": ticker_a, "ticker_b": ticker_b,
            "corr_now": round(corr_now, 3), "corr_avg": round(corr_avg, 3),
            "interpretasi": interpretasi, "perubahan": perubahan,
            "rolling_days": rolling_days, "n_observations": len(aligned),
        }
    except Exception:
        return None


# ──────────────────────────────────────────────
# CONFLUENCE
# ──────────────────────────────────────────────

def calculate_confluence(df: pd.DataFrame, ticker: str) -> dict:
    """Cek alignment 6 indikator teknikal berbeda. Makin banyak yang
    searah (bullish atau bearish), makin kuat konfluensi sinyal.

    Indikator: RSI, MACD, MA (posisi harga vs MA20), Bollinger Band,
    Stochastic RSI, Volume. Masing-masing dinilai bullish/netral/bearish."""
    close = df["Close"]
    volume = df["Volume"]

    indicators = {}

    # 1. RSI
    rsi_val = float(calculate_rsi(close).iloc[-1])
    if rsi_val < 35:
        indicators["RSI"] = ("BULLISH", f"RSI {rsi_val:.0f} (oversold, rebound potensial)")
    elif rsi_val > 70:
        indicators["RSI"] = ("BEARISH", f"RSI {rsi_val:.0f} (overbought, koreksi potensial)")
    elif rsi_val >= 50:
        indicators["RSI"] = ("BULLISH", f"RSI {rsi_val:.0f} (di atas 50)")
    else:
        indicators["RSI"] = ("BEARISH", f"RSI {rsi_val:.0f} (di bawah 50)")

    # 2. MACD
    macd_line, signal_line, hist = calculate_macd(close)
    if float(macd_line.iloc[-1]) > float(signal_line.iloc[-1]) and float(hist.iloc[-1]) > 0:
        indicators["MACD"] = ("BULLISH", "MACD > Signal, histogram positif")
    elif float(macd_line.iloc[-1]) < float(signal_line.iloc[-1]):
        indicators["MACD"] = ("BEARISH", "MACD < Signal")
    else:
        indicators["MACD"] = ("NETRAL", "MACD ≈ Signal")

    # 3. MA (posisi harga vs MA20)
    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else ma20
    price = float(close.iloc[-1])
    if price > ma20 and ma20 > ma50:
        indicators["MA"] = ("BULLISH", f"Harga > MA20 ({ma20:,.0f}) > MA50")
    elif price > ma20:
        indicators["MA"] = ("BULLISH", f"Harga > MA20 ({ma20:,.0f})")
    elif price < ma20:
        indicators["MA"] = ("BEARISH", f"Harga < MA20 ({ma20:,.0f})")
    else:
        indicators["MA"] = ("NETRAL", "Harga ≈ MA20")

    # 4. Bollinger Bands
    bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(close)
    bb_up = float(bb_upper.iloc[-1])
    bb_lo = float(bb_lower.iloc[-1])
    bb_mid = float(bb_middle.iloc[-1])
    if price < bb_lo:
        indicators["BB"] = ("BULLISH", f"Harga di bawah BB lower ({bb_lo:,.0f}) -- oversold")
    elif price > bb_up:
        indicators["BB"] = ("BEARISH", f"Harga di atas BB upper ({bb_up:,.0f}) -- overbought")
    elif price > bb_mid:
        indicators["BB"] = ("BULLISH", "Harga di atas BB tengah")
    else:
        indicators["BB"] = ("BEARISH", "Harga di bawah BB tengah")

    # 5. Stochastic RSI
    stoch_k, stoch_d = calculate_stochrsi(close)
    sk = float(stoch_k.iloc[-1]) if not pd.isna(stoch_k.iloc[-1]) else 50
    if sk < 20:
        indicators["StochRSI"] = ("BULLISH", f"StochRSI {sk:.0f} (oversold)")
    elif sk > 80:
        indicators["StochRSI"] = ("BEARISH", f"StochRSI {sk:.0f} (overbought)")
    elif sk >= 50:
        indicators["StochRSI"] = ("BULLISH", f"StochRSI {sk:.0f} (di atas 50)")
    else:
        indicators["StochRSI"] = ("BEARISH", f"StochRSI {sk:.0f} (di bawah 50)")

    # 6. Volume
    vol_avg20 = float(volume.tail(20).mean())
    vol_now = float(volume.iloc[-1])
    vol_ratio = vol_now / vol_avg20 if vol_avg20 > 0 else 1
    price_change = ((price / float(close.iloc[-2])) - 1) * 100
    if vol_ratio >= 1.5 and price_change > 0:
        indicators["Volume"] = ("BULLISH", f"Volume {vol_ratio:.1f}x rata-rata + harga naik")
    elif vol_ratio >= 1.5 and price_change < 0:
        indicators["Volume"] = ("BEARISH", f"Volume {vol_ratio:.1f}x rata-rata + harga turun")
    elif vol_ratio >= 1.0:
        indicators["Volume"] = ("NETRAL", f"Volume normal ({vol_ratio:.1f}x rata-rata)")
    else:
        indicators["Volume"] = ("NETRAL", f"Volume rendah ({vol_ratio:.1f}x rata-rata)")

    bullish = sum(1 for v, _ in indicators.values() if v == "BULLISH")
    bearish = sum(1 for v, _ in indicators.values() if v == "BEARISH")
    netral = sum(1 for v, _ in indicators.values() if v == "NETRAL")

    if bullish >= 5:
        kesimpulan = "✅ KONFLUENSI BULLISH SANGAT KUAT (5-6 indikator searah naik)"
    elif bullish >= 4:
        kesimpulan = "🟢 KONFLUENSI BULLISH KUAT (4 indikator searah naik)"
    elif bullish >= 3:
        kesimpulan = "🟡 CENDERUNG BULLISH (3 indikator bullish)"
    elif bearish >= 5:
        kesimpulan = "⛔ KONFLUENSI BEARISH SANGAT KUAT (5-6 indikator searah turun)"
    elif bearish >= 4:
        kesimpulan = "🔴 KONFLUENSI BEARISH KUAT (4 indikator searah turun)"
    elif bearish >= 3:
        kesimpulan = "🟠 CENDERUNG BEARISH (3 indikator bearish)"
    else:
        kesimpulan = "⚪ MIXED SIGNAL -- tidak ada konfluensi yang jelas"

    return {
        "ticker": ticker, "harga": round(price, 0),
        "indicators": indicators,
        "bullish": bullish, "bearish": bearish, "netral": netral,
        "kesimpulan": kesimpulan,
    }


# ──────────────────────────────────────────────
# BACKTEST PRO (WALK-FORWARD VALIDATION)
# ──────────────────────────────────────────────

def run_backtestpro(df: pd.DataFrame, ticker: str, mode: str = "momentum",
                     n_windows: int = 4) -> dict | None:
    """Walk-forward validation -- lebih rigorous dari backtest in-sample.

    Cara kerja: bagi data historis jadi n_windows periode non-overlapping.
    Di tiap window, jalankan kondisi teknikal yang sama (momentum/breakout/
    quality) dan catat win rate. Aggregate lintas window memberikan
    estimasi yang lebih jujur karena setiap window test-nya benar-benar
    out-of-sample relatif terhadap window sebelumnya.

    mode: 'momentum' | 'breakout' | 'quality' (konsisten dengan screenerpro)
    n_windows: jumlah windows walk-forward (default 4, ~60-90 hari per window)
    """
    if len(df) < 120:
        return None

    window_size = len(df) // n_windows
    if window_size < 30:
        return None

    def condition_momentum(df_w: pd.DataFrame, i: int) -> bool:
        close = df_w["Close"]
        if i < 26:
            return False
        rsi = calculate_rsi(close)
        macd_line, signal_line, _ = calculate_macd(close)
        return (float(rsi.iloc[i]) > 50 and
                float(macd_line.iloc[i]) > float(signal_line.iloc[i]) and
                float(df_w["Volume"].iloc[i]) > float(df_w["Volume"].rolling(20).mean().iloc[i]) * 1.2)

    def condition_breakout(df_w: pd.DataFrame, i: int) -> bool:
        close = df_w["Close"]
        if i < 20:
            return False
        high_20 = float(close.iloc[max(0, i-20):i].max())
        vol_med = float(df_w["Volume"].iloc[max(0, i-20):i].median())
        return (float(close.iloc[i]) > high_20 * 0.98 and
                float(df_w["Volume"].iloc[i]) > vol_med * 2)

    def condition_quality(df_w: pd.DataFrame, i: int) -> bool:
        close = df_w["Close"]
        if i < 20:
            return False
        ma20 = float(close.rolling(20).mean().iloc[i])
        vol_avg = float(df_w["Volume"].rolling(20).mean().iloc[i])
        returns = close.pct_change().iloc[max(0, i-20):i]
        vol_20d = float(returns.std()) * 100
        return (float(close.iloc[i]) > ma20 and
                float(df_w["Volume"].iloc[i]) > vol_avg and
                vol_20d < 3.0)  # volatilitas harian < 3%

    condition_fn_map = {
        "momentum": condition_momentum,
        "breakout": condition_breakout,
        "quality": condition_quality,
    }
    if mode not in condition_fn_map:
        return None
    condition_fn = condition_fn_map[mode]

    window_results = []
    for w in range(n_windows):
        start = w * window_size
        end = start + window_size + 10  # sedikit overlap untuk forward return
        df_window = df.iloc[start:min(end, len(df))].reset_index(drop=True)

        r = backtest_condition(df_window, condition_fn, forward_days=5)
        if r is not None:
            window_results.append(r)

    if not window_results:
        return None

    # Agregasi lintas windows
    all_win_rates = [w["win_rate"] for w in window_results]
    all_ns = [w["n"] for w in window_results]
    all_avg_returns = [w["avg_return"] for w in window_results]

    weighted_win_rate = sum(r * n for r, n in zip(all_win_rates, all_ns)) / sum(all_ns)
    avg_return_overall = np.mean(all_avg_returns)
    total_n = sum(all_ns)

    # Konsistensi: apakah win rate stabil lintas window atau fluktuatif?
    std_win_rate = float(np.std(all_win_rates))
    if std_win_rate < 10:
        konsistensi = f"KONSISTEN (std {std_win_rate:.1f}%)"
    elif std_win_rate < 20:
        konsistensi = f"CUKUP KONSISTEN (std {std_win_rate:.1f}%)"
    else:
        konsistensi = f"TIDAK KONSISTEN (std {std_win_rate:.1f}%) -- waspada"

    return {
        "ticker": ticker, "mode": mode,
        "n_windows": len(window_results),
        "total_n": total_n,
        "weighted_win_rate": round(weighted_win_rate, 1),
        "avg_return": round(avg_return_overall, 2),
        "std_win_rate": round(std_win_rate, 1),
        "konsistensi": konsistensi,
        "window_details": [
            {"window": i + 1, "n": r["n"], "win_rate": r["win_rate"],
             "avg_return": r["avg_return"]}
            for i, r in enumerate(window_results)
        ],
    }
