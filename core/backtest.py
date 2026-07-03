# =========================
# BACKTESTING SINYAL (VALIDASI STATISTIK HISTORIS)
# =========================
# FITUR BARU. Tujuan: ketika /signal atau /bsjp mengeluarkan sinyal untuk
# suatu saham, user bisa tahu "dalam histori saham ini, kondisi serupa
# muncul berapa kali, dan berapa persen yang akhirnya naik dalam N hari
# ke depan". Ini mengubah AI score dari rule-based scoring murni jadi
# punya bukti statistik konkret di belakangnya.
#
# PENTING -- KETERBATASAN YANG HARUS DISADARI (supaya tidak menyesatkan
# user dengan overclaim statistik):
# - Sample historis dari satu saham individual biasanya KECIL (puluhan
#   kejadian dalam 1-2 tahun data), jadi "win rate 70%" dari 10 kejadian
#   beda jauh kredibilitasnya dari yang sama dari 100 kejadian. Hasil
#   SELALU menyertakan jumlah sample (n) dan TIDAK PERNAH ditampilkan
#   tanpa itu.
# - Backtest "kondisi sama pernah muncul, harga naik X%" adalah pengujian
#   pada DATA YANG SAMA dengan yang dipakai screener (in-sample), bukan
#   out-of-sample validation yang sesungguhnya. Ini bentuk paling
#   sederhana dari validasi historis, bukan bukti bahwa strategi akan
#   profitable di masa depan. Disclaimer ini WAJIB ada di setiap output.
# - "Naik dalam N hari" tidak memperhitungkan kapan harus exit / stop
#   loss di tengah jalan -- ini ukuran arah pergerakan, bukan simulasi
#   trading plan lengkap.

import numpy as np
import pandas as pd

from core.indicators import calculate_rsi


# =========================
# UNIVERSE BACKTESTER (untuk web)
# =========================
# Berbeda dari backtest_condition() di bawah (yang untuk single-stock/bot),
# fungsi ini menerima dict conditions, scan semua saham dalam universe,
# dan kembalikan statistik agregat + daftar trade.

def _compute_indicators_bt(df: pd.DataFrame) -> dict:
    close = df["Close"]
    rsi = calculate_rsi(close, 14)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - signal_line
    return {
        "rsi": rsi,
        "macd_hist": macd_hist,
        "ma5": close.rolling(5).mean(),
        "ma20": close.rolling(20).mean(),
        "ma50": close.rolling(50).mean(),
        "ma200": close.rolling(200).mean(),
        "vol_ma20": df["Volume"].rolling(20).mean(),
    }


def _find_signals_for_stock(kode: str, df: pd.DataFrame, conditions: dict, holding_days: int) -> list:
    """Scan histori satu saham, kembalikan list trade dict."""
    if df is None or len(df) < 210 + holding_days:
        return []
    ind = _compute_indicators_bt(df)
    close = df["Close"]
    vol = df["Volume"]
    dates = df.index
    trades = []

    for i in range(200, len(df) - holding_days):
        ok = True
        rsi_v = ind["rsi"].iloc[i]
        if pd.isna(rsi_v):
            continue

        rsi_max = conditions.get("rsi_max")
        if rsi_max is not None and rsi_v > rsi_max:
            ok = False

        rsi_min = conditions.get("rsi_min")
        if ok and rsi_min is not None and rsi_v < rsi_min:
            ok = False

        if ok and conditions.get("macd_cross"):
            h_prev = ind["macd_hist"].iloc[i - 1]
            h_now = ind["macd_hist"].iloc[i]
            if pd.isna(h_prev) or pd.isna(h_now) or not (h_prev < 0 and h_now >= 0):
                ok = False

        if ok and conditions.get("price_above_ma20"):
            ma = ind["ma20"].iloc[i]
            if pd.isna(ma) or close.iloc[i] <= ma:
                ok = False

        if ok and conditions.get("price_above_ma50"):
            ma = ind["ma50"].iloc[i]
            if pd.isna(ma) or close.iloc[i] <= ma:
                ok = False

        if ok and conditions.get("price_above_ma200"):
            ma = ind["ma200"].iloc[i]
            if pd.isna(ma) or close.iloc[i] <= ma:
                ok = False

        spike = conditions.get("volume_spike")
        if ok and spike:
            vm = ind["vol_ma20"].iloc[i]
            if pd.isna(vm) or vm <= 0 or vol.iloc[i] < spike * vm:
                ok = False

        if ok and conditions.get("golden_cross"):
            ma5_prev = ind["ma5"].iloc[i - 1]
            ma20_prev = ind["ma20"].iloc[i - 1]
            ma5_now = ind["ma5"].iloc[i]
            ma20_now = ind["ma20"].iloc[i]
            if any(pd.isna(x) for x in [ma5_prev, ma20_prev, ma5_now, ma20_now]):
                ok = False
            elif not (ma5_prev <= ma20_prev and ma5_now > ma20_now):
                ok = False

        if not ok:
            continue

        entry = float(close.iloc[i])
        exit_price = float(close.iloc[i + holding_days])
        if entry <= 0:
            continue

        trades.append({
            "kode": kode,
            "date": str(dates[i].date()),
            "exit_date": str(dates[i + holding_days].date()),
            "entry": round(entry),
            "exit": round(exit_price),
            "return_pct": round((exit_price / entry - 1) * 100, 2),
            "rsi_at_signal": round(float(rsi_v), 1),
        })

    return trades


def aggregate_backtest(all_trades: list, universe_size: int, holding_days: int) -> dict:
    """Agregasi list trade jadi statistik ringkas."""
    if not all_trades:
        return {
            "total_signals": 0,
            "stocks_with_signals": 0,
            "universe_size": universe_size,
            "holding_days": holding_days,
            "win_rate": None,
            "avg_return": None,
            "trades": [],
            "by_stock": [],
            "equity_curve": [],
        }

    sorted_trades = sorted(all_trades, key=lambda t: t["date"])
    rets = np.array([t["return_pct"] for t in sorted_trades])
    wins = int((rets > 0).sum())
    losses = len(rets) - wins

    gain_sum = float(rets[rets > 0].sum()) if wins else 0.0
    loss_sum = float(abs(rets[rets <= 0].sum())) if losses else 0.0
    profit_factor = round(gain_sum / loss_sum, 2) if loss_sum > 0 else None

    # Equity curve: running cumulative return (equal-weight per trade)
    equity = []
    running = 0.0
    for idx, t in enumerate(sorted_trades):
        running += t["return_pct"]
        equity.append({
            "date": t["date"],
            "cumulative": round(running / (idx + 1), 2),
            "total": round(running, 1),
        })

    # Per-stock stats
    by_stock: dict = {}
    for t in all_trades:
        by_stock.setdefault(t["kode"], []).append(t["return_pct"])

    by_stock_list = []
    for kode, rs in sorted(by_stock.items()):
        arr = np.array(rs)
        by_stock_list.append({
            "kode": kode,
            "n": len(arr),
            "win_rate": round(float((arr > 0).mean() * 100), 1),
            "avg_return": round(float(arr.mean()), 2),
        })
    by_stock_list.sort(key=lambda x: x["avg_return"], reverse=True)

    best = max(sorted_trades, key=lambda t: t["return_pct"])
    worst = min(sorted_trades, key=lambda t: t["return_pct"])

    return {
        "total_signals": len(sorted_trades),
        "stocks_with_signals": len(by_stock),
        "universe_size": universe_size,
        "holding_days": holding_days,
        "win_rate": round(float(wins / len(rets) * 100), 1),
        "avg_return": round(float(rets.mean()), 2),
        "median_return": round(float(np.median(rets)), 2),
        "best_return": round(float(rets.max()), 2),
        "worst_return": round(float(rets.min()), 2),
        "std_return": round(float(rets.std()), 2),
        "profit_factor": profit_factor,
        "best_trade": best,
        "worst_trade": worst,
        "trades": sorted_trades,
        "by_stock": by_stock_list,
        "equity_curve": equity,
    }

MIN_SAMPLE_SIZE = 5  # di bawah ini, hasil backtest dianggap tidak cukup andal untuk ditampilkan


def _detect_signal_occurrences(df: pd.DataFrame, condition_fn) -> list[int]:
    """Scan seluruh df, kembalikan list index (posisi baris) di mana
    condition_fn(df, i) bernilai True. condition_fn menerima df dan
    index baris, return bool."""
    occurrences = []
    for i in range(20, len(df) - 1):  # mulai dari 20 supaya MA20 dkk sudah valid
        try:
            if condition_fn(df, i):
                occurrences.append(i)
        except Exception:
            continue
    return occurrences


def _forward_return(df: pd.DataFrame, idx: int, forward_days: int) -> float | None:
    """Hitung return harga dari index idx ke idx+forward_days. Return
    None kalau idx+forward_days di luar range data (sinyal terlalu baru
    untuk dihitung forward return-nya)."""
    target_idx = idx + forward_days
    if target_idx >= len(df):
        return None
    entry_price = float(df["Close"].iloc[idx])
    future_price = float(df["Close"].iloc[target_idx])
    return ((future_price / entry_price) - 1) * 100


def _base_rate(df: pd.DataFrame, forward_days: int) -> float | None:
    """Win rate TANPA SYARAT (base rate): dari SEMUA hari di histori,
    berapa persen yang harganya naik dalam forward_days ke depan.

    KENAPA PENTING (inti perbaikan berbasis riset): "win rate sinyal 58%"
    tidak berarti apa-apa kalau pasar memang naik 56% di hari acak mana
    pun (IHSG cenderung drift naik jangka panjang). Yang bermakna adalah
    EDGE = win_rate sinyal − base_rate. Literatur technical trading rules
    menekankan perbandingan terhadap null model / baseline ini (mis. Chen,
    Huang & Lai 2009 soal data-snooping di pasar Asia; Brock, Lakonishok &
    LeBaron 1992). Tanpa baseline, win rate gampang menyesatkan."""
    rets = []
    for i in range(20, len(df) - forward_days):
        r = _forward_return(df, i, forward_days)
        if r is not None:
            rets.append(r)
    if not rets:
        return None
    arr = np.array(rets)
    return round(float((arr > 0).mean() * 100), 1)


def backtest_condition(df: pd.DataFrame, condition_fn, forward_days: int = 5) -> dict | None:
    """Backtest satu kondisi sinyal terhadap histori harga.

    condition_fn: function(df, i) -> bool, kondisi yang dicek di tiap baris i.
    forward_days: berapa hari ke depan untuk mengukur hasil (default 5,
    konsisten dengan horizon swing-trading jangka pendek).

    Returns dict berisi statistik, atau None kalau sample terlalu kecil
    (< MIN_SAMPLE_SIZE) untuk dianggap bermakna.
    """
    occurrences = _detect_signal_occurrences(df, condition_fn)

    returns = []
    for idx in occurrences:
        r = _forward_return(df, idx, forward_days)
        if r is not None:
            returns.append(r)

    n = len(returns)
    if n < MIN_SAMPLE_SIZE:
        return None

    returns_arr = np.array(returns)
    win_count = int((returns_arr > 0).sum())
    win_rate = (win_count / n) * 100

    base_rate = _base_rate(df, forward_days)
    edge = round(win_rate - base_rate, 1) if base_rate is not None else None

    return {
        "n": n,
        "forward_days": forward_days,
        "win_rate": round(win_rate, 1),
        "base_rate": base_rate,          # win rate tanpa syarat (baseline)
        "edge": edge,                    # win_rate − base_rate; >0 = ada keunggulan
        "win_count": win_count,
        "loss_count": n - win_count,
        "avg_return": round(float(returns_arr.mean()), 2),
        "median_return": round(float(np.median(returns_arr)), 2),
        "best_return": round(float(returns_arr.max()), 2),
        "worst_return": round(float(returns_arr.min()), 2),
        "std_return": round(float(returns_arr.std()), 2),
    }


# ===== KONDISI SIAP-PAKAI (konsisten dengan kondisi /signal & /bsjp) =====

def condition_ma_cross_volume_spike(df: pd.DataFrame, i: int) -> bool:
    """Kondisi /signal: MA5>MA20 + volume spike + harga>200 + volume>500rb.
    Identik dengan kondisi cond1-cond4 di core/screener.py run_screener(),
    supaya backtest benar-benar mengukur kondisi yang sama dengan yang
    dipakai screener live."""
    ma5 = df["Close"].rolling(5).mean().iloc[i]
    ma20 = df["Close"].rolling(20).mean().iloc[i]
    vol_ma5 = df["Volume"].rolling(5).mean().iloc[i]
    vol_ma20 = df["Volume"].rolling(20).mean().iloc[i]
    close = df["Close"].iloc[i]
    volume = df["Volume"].iloc[i]

    cond1 = ma5 > ma20
    cond2 = (vol_ma5 / vol_ma20 if vol_ma20 > 0 else 1) > 1.2
    cond3 = close > 200
    cond4 = volume > 500000
    return cond1 and cond2 and cond3 and cond4


def condition_rsi_oversold(df: pd.DataFrame, i: int, threshold: float = 30) -> bool:
    """Kondisi RSI oversold (dipakai di banyak tempat: ai_score, advanced_chart)."""
    rsi = calculate_rsi(df["Close"])
    return rsi.iloc[i] < threshold


def condition_golden_cross_ma(df: pd.DataFrame, i: int) -> bool:
    """Golden cross: MA5 baru saja naik melewati MA20 (crossover persis
    di baris ini, bukan sudah berlangsung lama)."""
    ma5 = df["Close"].rolling(5).mean()
    ma20 = df["Close"].rolling(20).mean()
    if i < 1:
        return False
    return ma5.iloc[i - 1] <= ma20.iloc[i - 1] and ma5.iloc[i] > ma20.iloc[i]


def _ihsg_condition_indicators(df: pd.DataFrame) -> dict:
    """Cache RSI/MACD/MA20/MA50 di df.attrs, dipakai bersama oleh
    condition_ihsg_bullish_strong & condition_ihsg_bearish_strong.

    DITEMUKAN NYATA: kedua fungsi kondisi itu dulu menghitung ulang RSI
    dan MACD dari NOL di setiap panggilan -- dan _detect_signal_occurrences
    memanggil condition_fn(df, i) untuk SETIAP baris saat scan ratusan
    hari histori, jadi total kerjanya O(n) per baris x n baris = O(n^2)
    padahal nilainya identik untuk df yang sama. df.attrs aman dipakai
    sebagai cache karena scoped ke instance DataFrame itu sendiri (bukan
    cache global/modul yang bisa nyasar ke df lain)."""
    cache_key = "_ihsg_cond_cache"
    cached = df.attrs.get(cache_key)
    if cached is not None:
        return cached

    close = df["Close"]
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()

    result = {
        "ma20": close.rolling(20).mean(),
        "ma50": close.rolling(50).mean(),
        "rsi": calculate_rsi(close),
        "macd_hist": macd_line - signal_line,
    }
    df.attrs[cache_key] = result
    return result


def condition_ihsg_bullish_strong(df: pd.DataFrame, i: int) -> bool:
    """Versi ringkas dari 'skor bullish TINGGI' di analyze_ihsg_advanced
    (core/ihsg/ihsg_analysis.py): trend MA daily kuat (close > MA20 >
    MA50) + RSI belum overbought + MACD histogram positif. Sengaja tidak
    menyertakan komponen yang butuh data weekly atau pivot clustering
    (lebih mahal dihitung berulang untuk setiap baris saat backtest scan
    ratusan hari) -- ini APROKSIMASI dari kondisi penuh, dipakai khusus
    untuk mengukur win-rate historis yang menggantikan accuracy_estimate
    yang dulu rumus arbitrer (lihat catatan di ihsg_analysis.py)."""
    ind = _ihsg_condition_indicators(df)
    ma20 = ind["ma20"].iloc[i]
    ma50 = ind["ma50"].iloc[i]
    close = df["Close"].iloc[i]
    current_rsi = ind["rsi"].iloc[i]
    macd_hist = ind["macd_hist"].iloc[i]

    trend_strong = close > ma20 and ma20 > ma50
    rsi_ok = 40 < current_rsi < 70  # bullish tapi belum overbought
    macd_bullish = macd_hist > 0

    return trend_strong and rsi_ok and macd_bullish


def condition_ihsg_bearish_strong(df: pd.DataFrame, i: int) -> bool:
    """Kebalikan dari condition_ihsg_bullish_strong -- versi ringkas
    'skor bearish TINGGI'. Lihat catatan di condition_ihsg_bullish_strong."""
    ind = _ihsg_condition_indicators(df)
    ma20 = ind["ma20"].iloc[i]
    ma50 = ind["ma50"].iloc[i]
    close = df["Close"].iloc[i]
    current_rsi = ind["rsi"].iloc[i]
    macd_hist = ind["macd_hist"].iloc[i]

    trend_weak = close < ma20 and ma20 < ma50
    rsi_ok = 30 < current_rsi < 60  # bearish tapi belum oversold
    macd_bearish = macd_hist < 0

    return trend_weak and rsi_ok and macd_bearish


CONDITION_REGISTRY = {
    "ma_cross_volume": ("MA5>MA20 + Volume Spike (kondisi /signal)", condition_ma_cross_volume_spike),
    "rsi_oversold": ("RSI Oversold (<30)", condition_rsi_oversold),
    "golden_cross": ("Golden Cross MA5/MA20", condition_golden_cross_ma),
    "ihsg_bullish_strong": ("Trend Bullish Kuat (MA+RSI+MACD)", condition_ihsg_bullish_strong),
    "ihsg_bearish_strong": ("Trend Bearish Kuat (MA+RSI+MACD)", condition_ihsg_bearish_strong),
}


def format_backtest_result(ticker_name: str, condition_label: str, result: dict | None) -> str:
    """Format hasil backtest_condition() jadi pesan teks untuk user."""
    if result is None:
        return (
            f"📊 *BACKTEST: {condition_label}*\n"
            f"Saham: {ticker_name}\n\n"
            f"⚠️ Kondisi ini terlalu jarang muncul di histori {ticker_name} "
            f"(kurang dari {MIN_SAMPLE_SIZE} kejadian dalam data yang tersedia) "
            f"untuk dihitung statistiknya secara bermakna."
        )

    win_emoji = "🟢" if result["win_rate"] >= 60 else "🟡" if result["win_rate"] >= 45 else "🔴"

    return f"""
📊 *BACKTEST: {condition_label}*
Saham: {ticker_name}
{'='*40}

Kondisi ini muncul *{result['n']}x* di histori data yang tersedia.

{win_emoji} *Win Rate ({result['forward_days']} hari ke depan): {result['win_rate']}%*
├─ Naik: {result['win_count']}x
└─ Turun/Stagnan: {result['loss_count']}x

📈 *Return rata-rata: {result['avg_return']:+.2f}%*
├─ Median: {result['median_return']:+.2f}%
├─ Terbaik: {result['best_return']:+.2f}%
├─ Terburuk: {result['worst_return']:+.2f}%
└─ Std Dev: {result['std_return']:.2f}%

{'='*40}
⚠️ *PENTING:*
• Sample {result['n']}x {"tergolong kecil -- " if result['n'] < 15 else ""}hasil ini gambaran historis, BUKAN garansi hasil masa depan.
• Ini pengujian pada data yang sama dipakai screener (bukan validasi out-of-sample murni).
• Tidak memperhitungkan stop loss/exit di tengah jalan, cuma ukur arah harga.
• DYOR & gunakan sebagai SATU dari banyak pertimbangan, bukan satu-satunya.
"""
