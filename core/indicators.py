# =========================
# TECHNICAL INDICATORS
# =========================
# Modul ini menyatukan semua kalkulasi indikator teknikal yang sebelumnya
# TERSEBAR dan DIDUPLIKASI di banyak tempat di main.py lama.
#
# TEMUAN PENTING dari refactor ini:
# Rumus RSI manual (delta -> gain/loss -> rs -> 100-(100/(1+rs))) ditulis
# ULANG SECARA MANUAL sebanyak 13 KALI di file lama, di lokasi berbeda-beda.
# Ini bahaya karena kalau suatu saat rumusnya mau diperbaiki/diganti (misal
# ke Wilder's smoothing yang lebih standar daripada simple moving average
# yang dipakai sekarang), gampang lupa update di salah satu lokasi -- hasil
# RSI bisa beda-beda antar command untuk saham yang sama.
#
# Semua fungsi di sini dipertahankan PERSIS hasil kalkulasinya sama dengan
# kode lama (sudah dites dengan data yang sama, lihat test_indicators.py),
# cuma sekarang jadi satu sumber kebenaran. Rumus RSI tetap pakai simple
# moving average (bukan Wilder's) supaya hasil tidak berubah dari versi
# sebelumnya -- kalau mau upgrade ke Wilder's, itu keputusan terpisah yang
# sebaiknya didiskusikan dulu karena akan mengubah angka yang user lihat.

import numpy as np
import pandas as pd


def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index. Return Series RSI sepanjang data (bukan cuma
    angka terakhir), supaya bisa dipakai untuk chart maupun nilai tunggal.

    Dipertahankan pakai simple moving average untuk gain/loss (bukan
    Wilder's smoothing) -- ini rumus yang dipakai konsisten di seluruh
    kode lama, jadi dipertahankan agar angka tidak berubah.
    """
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def get_rsi_value(ticker: str, df: pd.DataFrame | None = None) -> str:
    """Format RSI jadi string dengan label Overbought/Oversold/Normal.

    Bisa dipanggil dengan df yang sudah ada (hindari download ulang), atau
    tanpa df untuk kompatibilitas dengan kode lama yang download sendiri --
    namun pemanggil disarankan selalu kirim df yang sudah ada supaya tidak
    download data yang sama berkali-kali.
    """
    try:
        if df is None or len(df) < 30:
            return "N/A"

        rsi = calculate_rsi(df["Close"])
        last_rsi = float(rsi.iloc[-1])

        if last_rsi > 70:
            return f"{last_rsi:.1f} (Overbought)"
        elif last_rsi < 30:
            return f"{last_rsi:.1f} (Oversold)"
        else:
            return f"{last_rsi:.1f} (Normal)"
    except Exception:
        return "N/A"


def calculate_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Moving Average Convergence Divergence.
    Returns: (macd_line, signal_line, histogram)
    """
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calculate_bollinger_bands(close: pd.Series, period: int = 20, num_std: float = 2.0):
    """Bollinger Bands. Returns: (middle_band/MA, upper_band, lower_band)"""
    middle = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = middle + (std * num_std)
    lower = middle - (std * num_std)
    return middle, upper, lower


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Average True Range -- ukuran volatilitas, dipakai untuk menentukan
    jarak stop-loss yang proporsional terhadap volatilitas saham."""
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    return atr.iloc[-1]


def calculate_stochrsi(series: pd.Series, period: int = 14, smooth_k: int = 3, smooth_d: int = 3):
    """Stochastic RSI. Returns: (%K, %D)"""
    rsi = calculate_rsi(series, period)

    min_rsi = rsi.rolling(window=period).min()
    max_rsi = rsi.rolling(window=period).max()

    stochrsi_k = (rsi - min_rsi) / (max_rsi - min_rsi) * 100
    stochrsi_d = stochrsi_k.rolling(window=smooth_d).mean()

    return stochrsi_k, stochrsi_d


def calculate_stochastic(df: pd.DataFrame, period: int = 14, smooth_k: int = 3, smooth_d: int = 3):
    """Stochastic Oscillator KLASIK (BUKAN StochRSI di atas) -- dihitung
    LANGSUNG dari harga High/Low/Close, bukan dari RSI. Ini indikator
    yang BERBEDA secara definisi meski sama-sama menghasilkan %K/%D
    skala 0-100 -- StochRSI mengukur "RSI relatif terhadap range RSI-nya
    sendiri", Stochastic klasik mengukur "Close relatif terhadap range
    High-Low-nya sendiri". Dipakai untuk /ta (core/charts/ta_chart.py),
    DIPISAH dari calculate_stochrsi yang sudah dipakai command lain
    (/signal dkk) supaya TIDAK mengubah perilaku command yang sudah ada.

    Formula baku: %K = (Close - Lowest Low) / (Highest High - Lowest Low) * 100,
    di-smooth dengan SMA(smooth_k) untuk %K final, %D = SMA(%K, smooth_d).
    Returns: (%K, %D)"""
    low_min = df["Low"].rolling(window=period).min()
    high_max = df["High"].rolling(window=period).max()

    range_hl = (high_max - low_min).replace(0, pd.NA)  # hindari div-by-zero (limit/suspend)
    raw_k = (df["Close"] - low_min) / range_hl * 100

    stoch_k = raw_k.rolling(window=smooth_k).mean()
    stoch_d = stoch_k.rolling(window=smooth_d).mean()

    return stoch_k, stoch_d


def calculate_adx(df: pd.DataFrame, period: int = 14):
    """Average Directional Index (ADX) + DI -- formula baku Wilder
    (dikonfirmasi dari riset: StockCharts ChartSchool, Wikipedia,
    TradingView, konsisten di semua sumber). Mengukur KEKUATAN tren
    (bukan arahnya) -- ADX < 20 = tren lemah/sideways, ADX > 25 =
    tren kuat, ADX > 40 = tren sangat kuat.

    Returns: (adx, plus_di, minus_di) -- tiga pd.Series."""
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(0.0, index=df.index)
    minus_dm = pd.Series(0.0, index=df.index)
    plus_dm[(up_move > down_move) & (up_move > 0)] = up_move[(up_move > down_move) & (up_move > 0)]
    minus_dm[(down_move > up_move) & (down_move > 0)] = down_move[(down_move > up_move) & (down_move > 0)]

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Wilder's smoothing (setara EMA dengan alpha=1/period, BUKAN SMA biasa
    # -- ini yang membedakan dari moving average umum, sesuai metode asli
    # Wilder yang dikonfirmasi semua sumber riset)
    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_dm_smooth = plus_dm.ewm(alpha=1/period, adjust=False).mean()
    minus_dm_smooth = minus_dm.ewm(alpha=1/period, adjust=False).mean()

    plus_di = 100 * (plus_dm_smooth / atr.replace(0, np.nan))
    minus_di = 100 * (minus_dm_smooth / atr.replace(0, np.nan))

    di_sum = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    adx = dx.ewm(alpha=1/period, adjust=False).mean()

    return adx, plus_di, minus_di


def calculate_fibonacci_levels(df: pd.DataFrame, lookback: int = 90) -> dict:
    """Level Fibonacci retracement dari swing high/low dalam lookback
    hari terakhir. Formula baku: level = low + (high - low) * ratio,
    untuk ratio 0.382 dan 0.618 (dua level paling umum dipakai trader,
    konsisten dengan yang sudah dipakai di /ihsg core/ihsg/ihsg_analysis.py)."""
    window = df.tail(lookback)
    swing_high = float(window["High"].max())
    swing_low = float(window["Low"].min())
    diff = swing_high - swing_low

    return {
        "swing_high": swing_high,
        "swing_low": swing_low,
        "fib_382": round(swing_low + diff * 0.382, 0),
        "fib_618": round(swing_low + diff * 0.618, 0),
    }


def calculate_support_resistance_deep(df: pd.DataFrame) -> dict:
    """Pivot point berbasis Fibonacci untuk level support & resistance."""
    high = df["High"].values
    low = df["Low"].values
    close = df["Close"].values

    pivot = (high[-1] + low[-1] + close[-1]) / 3
    range_hl = high[-1] - low[-1]

    r1 = pivot + range_hl * 0.382
    r2 = pivot + range_hl * 0.618
    r3 = pivot + range_hl * 1.000
    r4 = pivot + range_hl * 1.382
    r5 = pivot + range_hl * 1.618

    s1 = pivot - range_hl * 0.382
    s2 = pivot - range_hl * 0.618
    s3 = pivot - range_hl * 1.000
    s4 = pivot - range_hl * 1.382

    high_20 = max(high[-20:])
    high_50 = max(high[-50:]) if len(high) >= 50 else high_20

    return {
        "R1": round(r1, 2), "R2": round(r2, 2), "R3": round(r3, 2),
        "R4": round(r4, 2), "R5": round(r5, 2),
        "S1": round(s1, 2), "S2": round(s2, 2), "S3": round(s3, 2),
        "S4": round(s4, 2),
        "Pivot": round(pivot, 2),
        "High20": round(high_20, 2),
        "High50": round(high_50, 2),
    }


def calculate_confidence(df: pd.DataFrame, current_price: float, sr: dict,
                          volume_confirmation) -> int:
    """Confidence score (0-100) gabungan dari trend MA, posisi RSI, rasio
    volume, dan posisi harga relatif ke support."""
    confidence = 50

    ma5 = df["Close"].rolling(5).mean().iloc[-1]
    ma20 = df["Close"].rolling(20).mean().iloc[-1]
    ma50 = df["Close"].rolling(50).mean().iloc[-1]

    if ma5 > ma20 > ma50:
        confidence += 20
    elif ma5 > ma20:
        confidence += 10

    rsi = calculate_rsi(df["Close"])
    last_rsi = float(rsi.iloc[-1])

    if 40 <= last_rsi <= 60:
        confidence += 15
    elif 30 <= last_rsi <= 70:
        confidence += 5

    volume = float(df["Volume"].iloc[-1])
    avg_volume = df["Volume"].rolling(20).mean().iloc[-1]
    vol_ratio = volume / avg_volume if avg_volume > 0 else 1

    if vol_ratio > 1.5:
        confidence += 15
    elif vol_ratio > 1.2:
        confidence += 10

    if current_price <= sr["S1"] * 1.02:
        confidence += 10

    return min(confidence, 100)
