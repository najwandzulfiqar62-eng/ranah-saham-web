# =========================
# ANALISIS IHSG MULTI-TIMEFRAME
# =========================
# Migrasi analyze_ihsg_advanced dari main.py lama. Modul ini menggabungkan
# 10 teknik analisis: multi-timeframe trend, Fibonacci retracement,
# clustering S/R dari swing pivots, volume profile (POC), RSI divergence,
# MACD, Bollinger squeeze, candlestick pattern scoring, faktor musiman,
# dan scoring engine bullish/bearish gabungan.
#
# PERBAIKAN PENTING dari kode lama: field "target_move" (target persentase
# pergerakan harga yang ditampilkan ke user) di kode lama dihasilkan dari
# random.uniform(), BUKAN dari kalkulasi apapun -- artinya angka itu
# tampil seolah hasil prediksi tapi sebenarnya acak. Ini masalah serius
# untuk kredibilitas produk yang memberi rekomendasi finansial ke
# komunitas. Diganti dengan kalkulasi berbasis ATR (Average True Range)
# IHSG, diskalakan menurut tingkat confidence -- confidence TINGGI memberi
# target lebih besar (mengikuti semangat asli: rentang berbeda untuk
# TINGGI vs SEDANG), tapi sekarang besarnya target benar-benar mengikuti
# volatilitas riil index, bukan angka acak.
#
# Semua scoring bullish/bearish lainnya (RSI, MACD, Fibonacci, dst)
# DIPERTAHANKAN IDENTIK dengan kode lama -- itu sudah valid karena
# dihitung dari indikator riil, bukan random.

from datetime import datetime

import numpy as np
import pandas as pd

from core.indicators import calculate_atr, calculate_rsi


def _cluster_levels(levels: list, tolerance: float = 0.005) -> list:
    """Cluster level harga berdekatan (toleransi 0.5%) jadi satu rata-rata."""
    if not levels:
        return []
    levels = sorted(levels)
    clusters = []
    current_cluster = [levels[0]]

    for l in levels[1:]:
        if (l - current_cluster[-1]) / current_cluster[-1] < tolerance:
            current_cluster.append(l)
        else:
            clusters.append(round(np.mean(current_cluster), 0))
            current_cluster = [l]
    clusters.append(round(np.mean(current_cluster), 0))
    return clusters


def _pad_and_order_levels(levels: list, current_price: float, step: float, reverse: bool) -> list:
    """Lengkapi `levels` (kandidat resistance/support VALID, hasil cluster
    asli) jadi minimal 2 elemen dengan fallback proporsional, LALU urutkan
    ulang gabungan asli+fallback bareng, baru ambil 2 teratas.

    BUG NYATA yang jadi alasan fungsi ini dipisah: sebelumnya level_1/
    level_2 diisi terpisah (level_1 dari cluster asli KALAU ADA, level_2
    dari fallback KALAU cluster kedua tidak ada) TANPA re-order gabungan
    keduanya. Kalau cuma 1 cluster asli ketemu dan kebetulan jauh dari
    harga (mis. resistance asli +8.5%), sedangkan fallback level_2 pakai
    step lebih KECIL (mis. +3.5%), hasilnya level_1 (8.5%) > level_2
    (3.5%) -- TERBALIK, padahal level_1 harus SELALU lebih dekat ke harga
    daripada level_2. Menggabung dulu baru urutkan menjamin urutan benar
    apapun kombinasi asli vs fallback yang akhirnya dipakai.

    reverse=False utk resistance (ascending, makin dekat harga = makin
    kecil), reverse=True utk support (descending, makin dekat harga =
    makin besar)."""
    result = list(levels)
    while len(result) < 2:
        base = result[-1] if result else current_price
        result.append(round(base * step, 0))
    result = sorted(result, reverse=reverse)[:2]
    return result


def _calculate_target_move(atr: float, current_price: float, confidence: str, is_bullish: bool) -> str:
    """Hitung target pergerakan harga berbasis ATR (volatilitas riil),
    diskalakan menurut confidence level.

    GANTI dari random.uniform() di kode lama. ATR sebagai persentase dari
    harga memberi ukuran volatilitas yang proporsional terhadap index;
    confidence TINGGI menggunakan multiplier ATR lebih besar (2.0x-3.5x)
    daripada SEDANG (1.0x-1.8x), mempertahankan semangat asli rentang
    target yang berbeda per confidence level, tapi sekarang berbasis data.
    """
    atr_pct = (atr / current_price) * 100

    if confidence == "TINGGI (70%+)":
        target_pct = min(atr_pct * 2.5, 2.0)  # cap di 2% supaya tidak ekstrem untuk index
        target_pct = max(target_pct, 0.8)  # floor 0.8% biar tidak terlalu kecil saat ATR rendah
    else:  # SEDANG (60-70%)
        target_pct = min(atr_pct * 1.4, 1.0)
        target_pct = max(target_pct, 0.3)

    sign = "+" if is_bullish else "-"
    return f"{sign}{target_pct:.1f}%"


def analyze_ihsg_advanced(df_daily: pd.DataFrame, df_weekly: pd.DataFrame) -> dict | None:
    """Analisis IHSG multi-teknik. df_daily dan df_weekly harus sudah
    didownload & dibersihkan oleh caller (period 3mo/1d dan 1y/1wk).

    Returns None kalau data daily tidak cukup (< 50 baris).
    """
    if len(df_daily) < 50:
        return None

    current_price = float(df_daily["Close"].iloc[-1])
    prev_close = float(df_daily["Close"].iloc[-2])
    daily_change = ((current_price / prev_close) - 1) * 100

    # ===== 1. MULTIPLE TIMEFRAME TREND =====
    ma20_d = df_daily["Close"].rolling(20).mean().iloc[-1]
    ma50_d = df_daily["Close"].rolling(50).mean().iloc[-1]

    if len(df_weekly) >= 20:
        ma5_w = df_weekly["Close"].rolling(5).mean().iloc[-1]
        ma10_w = df_weekly["Close"].rolling(10).mean().iloc[-1]
        weekly_trend_bullish = current_price > ma5_w and ma5_w > ma10_w
    else:
        weekly_trend_bullish = None

    # ===== 2. FIBONACCI =====
    high_50 = df_daily["High"].tail(50).max() if len(df_daily) >= 50 else df_daily["High"].tail(20).max()
    low_50 = df_daily["Low"].tail(50).min() if len(df_daily) >= 50 else df_daily["Low"].tail(20).min()

    fib_range = high_50 - low_50
    fib_382 = low_50 + fib_range * 0.382
    fib_500 = low_50 + fib_range * 0.5
    fib_618 = low_50 + fib_range * 0.618

    # CATATAN: nilai fib_position pakai "-" sbg pemisah (mis. "BELOW-382"),
    # bukan underscore -- konvensi ini dipertahankan dari versi bot
    # Telegram lama (underscore ganjil bikin parse_mode='Markdown' gagal
    # total), tidak ada alasan diubah krn format ini tetap valid & sudah
    # dipakai konsisten oleh frontend web saat ini.
    if current_price > fib_618:
        fib_position = "ABOVE-618"
    elif current_price > fib_500:
        fib_position = "BETWEEN-500-618"
    elif current_price > fib_382:
        fib_position = "BETWEEN-382-500"
    else:
        fib_position = "BELOW-382"

    # ===== 3. SUPPORT RESISTANCE CLUSTER =====
    pivots_high = []
    pivots_low = []
    for i in range(10, len(df_daily) - 10):
        if df_daily['High'].iloc[i] == df_daily['High'].iloc[i - 10:i + 11].max():
            pivots_high.append(float(df_daily['High'].iloc[i]))
        if df_daily['Low'].iloc[i] == df_daily['Low'].iloc[i - 10:i + 11].min():
            pivots_low.append(float(df_daily['Low'].iloc[i]))

    # BUG NYATA ditemukan & diperbaiki (2 bagian):
    # 1. Pivot swing LAMA bisa berada di SISI YANG SALAH dari harga sekarang
    #    kalau IHSG sudah bergerak jauh sejak titik itu terjadi (mis. swing
    #    low lama dari saat indeks masih tinggi kini malah di ATAS harga
    #    sekarang setelah indeks turun -- itu bukan support lagi). Baris
    #    341/347 di bawah SUDAH menyadari & memfilter ini untuk scoring
    #    internal ("nearest_support"/"nearest_resistance"), TAPI field
    #    support_1/resistance_1/entry_zone yang ditampilkan ke USER
    #    sebelumnya TIDAK ikut difilter -- diperbaiki di sini, di akar
    #    masalahnya, supaya SEMUA pemakai konsisten benar.
    # 2. _cluster_levels() return ascending (kecil->besar). Resistance ada
    #    DI ATAS harga -> 3 TERKECIL (paling dekat harga) yang relevan,
    #    seharusnya [:3], TAPI kode lama pakai [-3:] (3 terbesar/terjauh).
    #    Support ada DI BAWAH harga -> 3 TERBESAR (paling dekat harga) yang
    #    relevan, seharusnya [-3:], TAPI kode lama pakai [:3] (3 terkecil/
    #    terjauh). Kedua arah TERBALIK -- pola bug yang sama persis dengan
    #    yang ditemukan & diperbaiki di core/charts/snr_chart.py.
    pivots_high_valid = [p for p in pivots_high if p >= current_price]
    pivots_low_valid = [p for p in pivots_low if p <= current_price]

    resistance_levels = _cluster_levels(pivots_high_valid[-20:])[:3]
    support_levels = _cluster_levels(pivots_low_valid[-20:])[-3:][::-1]

    # ===== 4. VOLUME PROFILE (POC) =====
    volumes = df_daily['Volume'].values
    prices = df_daily['Close'].values
    price_bins = 20
    price_min = prices.min()
    price_max = prices.max()
    bin_width = (price_max - price_min) / price_bins

    volume_profile = []
    for i in range(price_bins):
        bin_low = price_min + i * bin_width
        bin_high = bin_low + bin_width
        mask = (prices >= bin_low) & (prices < bin_high)
        vol_sum = volumes[mask].sum()
        volume_profile.append((bin_low + bin_width / 2, vol_sum))

    poc = max(volume_profile, key=lambda x: x[1])[0]

    # Yahoo Finance kadang balikin bar hari "sekarang" dengan Volume=0
    # sebelum sesi bursa IHSG benar-benar tertutup (ditemukan nyata: cek
    # live ^JKSE, volume hari berjalan 0 padahal 4 hari sebelumnya normal
    # ratusan juta). Kalau bar ini dipakai mentah di rata-rata 5 hari,
    # bobotnya 1/5 -- cukup besar untuk menyeret recent_volume turun ~20%+
    # dan bisa salah membaca volume_trend jadi "DECREASING" padahal bukan.
    # Buang KHUSUS untuk kalkulasi volume kalau bar terakhir volume-nya
    # persis 0 (bar riil yang sudah closed nyaris tidak pernah benar 0).
    vol_series = df_daily['Volume']
    if len(vol_series) > 1 and vol_series.iloc[-1] == 0:
        vol_series = vol_series.iloc[:-1]

    recent_volume = vol_series.tail(5).mean()
    avg_volume_50 = vol_series.tail(50).mean()
    volume_trend = ("INCREASING" if recent_volume > avg_volume_50 * 1.2
                     else "DECREASING" if recent_volume < avg_volume_50 * 0.8 else "STABLE")

    # ===== 5. RSI & DIVERGENCE =====
    rsi = calculate_rsi(df_daily["Close"])
    current_rsi = float(rsi.iloc[-1])

    price_lower_low = df_daily['Close'].iloc[-5] < df_daily['Close'].iloc[-10]
    rsi_higher_low = rsi.iloc[-5] > rsi.iloc[-10]
    bullish_divergence = price_lower_low and rsi_higher_low

    price_higher_high = df_daily['Close'].iloc[-5] > df_daily['Close'].iloc[-10]
    rsi_lower_high = rsi.iloc[-5] < rsi.iloc[-10]
    bearish_divergence = price_higher_high and rsi_lower_high

    # ===== 6. MACD =====
    ema12 = df_daily["Close"].ewm(span=12, adjust=False).mean()
    ema26 = df_daily["Close"].ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line

    macd_bullish = macd_line.iloc[-1] > signal_line.iloc[-1]
    macd_histogram_rising = histogram.iloc[-1] > histogram.iloc[-2] if len(histogram) > 1 else False

    # ===== 7. BOLLINGER BANDS & SQUEEZE =====
    sma20 = df_daily["Close"].rolling(20).mean()
    std20 = df_daily["Close"].rolling(20).std()
    upper_bb = sma20 + (std20 * 2)
    lower_bb = sma20 - (std20 * 2)
    bb_width = (upper_bb - lower_bb) / sma20 * 100

    bb_width_20 = df_daily['Close'].rolling(20).std() / sma20 * 100
    is_bb_squeeze = bb_width.iloc[-1] < bb_width_20.mean() * 0.5 if len(bb_width) > 20 else False
    bb_squeeze_forming = bb_width.iloc[-1] < bb_width.iloc[-5] if len(bb_width) > 5 else False

    # ===== 8. CANDLESTICK PATTERNS =====
    candle_patterns = []
    open_c = float(df_daily["Open"].iloc[-1])
    close_c = current_price
    high_c = float(df_daily["High"].iloc[-1])
    low_c = float(df_daily["Low"].iloc[-1])

    body = abs(close_c - open_c)
    upper_shadow = high_c - max(open_c, close_c)
    lower_shadow = min(open_c, close_c) - low_c
    candle_range = high_c - low_c

    is_bullish_candle = close_c > open_c
    is_bearish_candle = close_c < open_c

    # CATATAN: nama pattern pakai SPASI bukan underscore, konsisten dgn
    # alasan yang sama di fib_position di atas (warisan dari versi bot
    # Telegram lama, tetap dipertahankan krn masih valid utk web).
    if (lower_shadow > body * 2) and (upper_shadow < body * 0.5) and is_bearish_candle:
        candle_patterns.append(("HAMMER", 15))
    if (upper_shadow > body * 2) and (lower_shadow < body * 0.5) and is_bullish_candle:
        candle_patterns.append(("SHOOTING STAR", -15))

    prev_open = float(df_daily["Open"].iloc[-2])
    prev_close_c = float(df_daily["Close"].iloc[-2])
    prev_body = abs(prev_close_c - prev_open)
    if (prev_close_c < prev_open) and is_bullish_candle and body > prev_body:
        candle_patterns.append(("BULLISH ENGULFING", 20))
    elif (prev_close_c > prev_open) and is_bearish_candle and body > prev_body:
        candle_patterns.append(("BEARISH ENGULFING", -20))

    if body < candle_range * 0.1:
        candle_patterns.append(("DOJI", 0))

    if upper_shadow < body * 0.1 and lower_shadow < body * 0.1:
        if is_bullish_candle:
            candle_patterns.append(("BULLISH MARUBOZU", 10))
        else:
            candle_patterns.append(("BEARISH MARUBOZU", -10))

    # ===== 9. SEASONALITY =====
    now = datetime.now()
    day_of_week = now.weekday()
    day_of_month = now.day

    dow_performance = {
        0: "MONDAY_EFFECT", 1: "TUESDAY_EFFECT", 2: "WEDNESDAY_EFFECT",
        3: "THURSDAY_EFFECT", 4: "FRIDAY_EFFECT",
    }
    is_month_end = day_of_month > 25
    is_month_start = day_of_month < 5

    # ===== 10. SCORING ENGINE =====
    bullish_score = 0
    bearish_score = 0

    if current_price > ma20_d and ma20_d > ma50_d:
        bullish_score += 20
    elif current_price < ma20_d and ma20_d < ma50_d:
        bearish_score += 20
    elif current_price > ma20_d:
        bullish_score += 12
    elif current_price < ma20_d:
        bearish_score += 12

    if weekly_trend_bullish is True:
        bullish_score += 10
    elif weekly_trend_bullish is False:
        bearish_score += 10

    if fib_position == "BELOW-382":
        bullish_score += 10
    elif fib_position == "BETWEEN-382-500":
        bullish_score += 5
    elif fib_position == "BETWEEN-500-618":
        bearish_score += 5
    elif fib_position == "ABOVE-618":
        bearish_score += 10

    if current_rsi < 30:
        bullish_score += 15
    elif current_rsi > 70:
        bearish_score += 15
    elif current_rsi < 40 and current_rsi > rsi.iloc[-2]:
        bullish_score += 8
    elif current_rsi > 60 and current_rsi < rsi.iloc[-2]:
        bearish_score += 8

    if bullish_divergence:
        bullish_score += 15
    elif bearish_divergence:
        bearish_score += 15

    if macd_bullish:
        bullish_score += 7
        if macd_histogram_rising:
            bullish_score += 3
    else:
        bearish_score += 7
        if not macd_histogram_rising:
            bearish_score += 3

    bb_position = ((current_price - lower_bb.iloc[-1]) / (upper_bb.iloc[-1] - lower_bb.iloc[-1]) * 100
                   if (upper_bb.iloc[-1] - lower_bb.iloc[-1]) > 0 else 50)
    if bb_position < 5:
        bullish_score += 10
    elif bb_position > 95:
        bearish_score += 10
    elif bb_position < 20:
        bullish_score += 6
    elif bb_position > 80:
        bearish_score += 6

    if is_bb_squeeze:
        bullish_score += 5
    elif bb_squeeze_forming:
        bullish_score += 3

    if volume_trend == "INCREASING" and daily_change > 0:
        bullish_score += 10
    elif volume_trend == "INCREASING" and daily_change < 0:
        bearish_score += 10
    elif volume_trend == "DECREASING" and daily_change > 0:
        bearish_score += 5

    if current_price < poc:
        bullish_score += 5
    elif current_price > poc * 1.05:
        bearish_score += 5

    pattern_score = sum(score for _, score in candle_patterns)
    if pattern_score > 0:
        bullish_score += pattern_score
    elif pattern_score < 0:
        bearish_score += abs(pattern_score)

    if support_levels:
        nearest_support = max([s for s in support_levels if s < current_price] + [current_price * 0.95])
        dist_to_support = ((current_price - nearest_support) / current_price) * 100
        if dist_to_support < 1:
            bullish_score += 5

    if resistance_levels:
        nearest_resistance = min([r for r in resistance_levels if r > current_price] + [current_price * 1.05])
        dist_to_resistance = ((nearest_resistance - current_price) / current_price) * 100
        if dist_to_resistance < 1:
            bearish_score += 5

    # ===== FINAL PREDICTION =====
    total_score = bullish_score + bearish_score
    if total_score > 0:
        bullish_percent = (bullish_score / total_score) * 100
        bearish_percent = (bearish_score / total_score) * 100
    else:
        bullish_percent = bearish_percent = 50

    # ATR untuk target_move berbasis volatilitas riil (GANTI random)
    atr = calculate_atr(df_daily)

    if bullish_percent >= 70:
        prediction = "BULLISH"
        confidence = "TINGGI (70%+)"
        action = "AKUMULASI - Harga diperkirakan naik"
        target_move = _calculate_target_move(atr, current_price, confidence, is_bullish=True)
    elif bullish_percent >= 60:
        prediction = "CENDERUNG BULLISH"
        confidence = "SEDANG (60-70%)"
        action = "WAIT & SEE - Cenderung naik, tunggu konfirmasi"
        target_move = _calculate_target_move(atr, current_price, confidence, is_bullish=True)
    elif bearish_percent >= 70:
        prediction = "BEARISH"
        confidence = "TINGGI (70%+)"
        action = "HINDARI BELI - Harga diperkirakan turun"
        target_move = _calculate_target_move(atr, current_price, confidence, is_bullish=False)
    elif bearish_percent >= 60:
        prediction = "CENDERUNG BEARISH"
        confidence = "SEDANG (60-70%)"
        action = "HOLD - Cenderung turun, jangan entry baru"
        target_move = _calculate_target_move(atr, current_price, confidence, is_bullish=False)
    elif abs(bullish_percent - bearish_percent) < 15:
        prediction = "SIDEWAYS"
        confidence = "RENDAH (50-60%)"
        action = "RANGE TRADING - Jual di resistance, beli di support"
        target_move = "0.0% (sideways)"
    else:
        prediction = "MIXED"
        confidence = "RENDAH (<50%)"
        action = "MONITOR - Tunggu sinyal lebih jelas"
        target_move = "Tidak jelas"

    # ===== AKURASI: TIDAK DIHITUNG DI SINI =====
    # GANTI dari kode lama: dulu "predicted_accuracy" dihitung dari rumus
    # arbitrer (50 + signal_confluence*5, dibatasi maks 85) -- angka ini
    # TAMPAK seperti hasil pengukuran tapi sebenarnya formula buatan,
    # sama bermasalahnya dengan target_move yang dulu random.uniform()
    # (lihat catatan lengkap di bagian atas file ini dan di
    # core/backtest.py: condition_ihsg_bullish_strong/bearish_strong).
    #
    # Fungsi ini TIDAK menghitung akurasi -- itu sengaja dipindah ke
    # analyze_ihsg_with_backtest() (fungsi wrapper di bawah), yang
    # memanggil backtest_condition() pada histori IHSG untuk mengukur
    # win-rate SUNGGUHAN dari kondisi serupa di masa lalu. Dipisah dari
    # fungsi ini supaya analyze_ihsg_advanced() tetap pure & mudah
    # ditest (tidak butuh data tambahan di luar df_daily/df_weekly).

    # Sanitasi nilai NaN/Inf yang bisa muncul dari data anomali (harga konstan,
    # data sangat pendek, dll). Field string dan bool tidak perlu sanitasi.
    import math
    def _safe_float(v, default=0.0):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return default
        return v

    resistance_display = _pad_and_order_levels(resistance_levels, current_price, 1.02, reverse=False)
    support_display = _pad_and_order_levels(support_levels, current_price, 0.98, reverse=True)

    return {
        "current_price": current_price,
        "daily_change": _safe_float(daily_change),
        "prediction": prediction,
        "confidence": confidence,
        "target_move": target_move,
        "action": action,
        "bullish_score": round(bullish_percent),
        "bearish_score": round(bearish_percent),
        "bullish_score_raw": bullish_score,
        "bearish_score_raw": bearish_score,
        "rsi": round(_safe_float(current_rsi, 50.0), 1),  # default 50 (netral) kalau NaN
        "rsi_divergence": "BULLISH" if bullish_divergence else "BEARISH" if bearish_divergence else "NONE",
        "macd_signal": "BULLISH" if macd_bullish else "BEARISH",
        "bb_position": round(_safe_float(bb_position, 50.0), 1),
        "bb_squeeze": is_bb_squeeze,
        "fib_position": fib_position,
        "fib_382": round(fib_382, 0),
        "fib_500": round(fib_500, 0),
        "fib_618": round(fib_618, 0),
        "poc": round(poc, 0),
        "support_1": support_display[0],
        "support_2": support_display[1],
        "resistance_1": resistance_display[0],
        "resistance_2": resistance_display[1],
        "ma20": round(_safe_float(ma20_d, current_price), 0),
        "ma50": round(_safe_float(ma50_d, current_price), 0),
        "ma_trend": "BULLISH" if current_price > ma20_d > ma50_d else "BEARISH" if current_price < ma20_d < ma50_d else "MIXED",
        "volume_trend": volume_trend,
        "volume_ratio": round(_safe_float(recent_volume / avg_volume_50 if avg_volume_50 > 0 else 1.0), 1),
        "candle_patterns": candle_patterns,
        "day_of_week": dow_performance.get(day_of_week, "UNKNOWN"),
        "is_month_end": is_month_end,
        "is_month_start": is_month_start,
        "entry_zone": f"Rp{support_display[0]:,.0f} - Rp{resistance_display[0]:,.0f}",
        "stop_loss": round(current_price * 0.97, 0),
        "take_profit": round(current_price * 1.02, 0),
        "risk_reward": "1:1.5",
    }


def analyze_ihsg_with_backtest(df_daily: pd.DataFrame, df_weekly: pd.DataFrame,
                                  df_longer_history: pd.DataFrame) -> dict | None:
    """Wrapper di atas analyze_ihsg_advanced() yang menambahkan akurasi
    SUNGGUHAN (bukan rumus arbitrer) lewat backtest historis.

    GANTI dari "accuracy_estimate" lama yang formula buatan (lihat
    catatan di analyze_ihsg_advanced). Sekarang, tergantung prediction
    yang dihasilkan ('BULLISH'/'CENDERUNG BULLISH' vs 'BEARISH'/
    'CENDERUNG BEARISH'), dijalankan backtest_condition() dengan kondisi
    condition_ihsg_bullish_strong / condition_ihsg_bearish_strong pada
    df_longer_history (perlu histori lebih panjang dari df_daily yang
    cuma 3 bulan -- supaya sample backtest cukup besar untuk bermakna).

    df_longer_history: histori IHSG yang LEBIH PANJANG dari df_daily,
    disarankan minimal 1-2 tahun (period='1y' atau '2y'), khusus untuk
    keperluan backtest -- BUKAN dipakai untuk analisis teknikal utama
    (yang tetap pakai df_daily seperti sebelumnya).

    Returns dict yang SAMA dengan analyze_ihsg_advanced() PLUS field
    'backtest_result' (dict dari backtest_condition(), atau None kalau
    sample historis terlalu kecil -- lihat core/backtest.py).
    Returns None kalau analyze_ihsg_advanced() sendiri gagal (data
    daily tidak cukup).
    """
    from core.backtest import (
        backtest_condition, condition_ihsg_bullish_strong, condition_ihsg_bearish_strong,
    )

    analysis = analyze_ihsg_advanced(df_daily, df_weekly)
    if analysis is None:
        return None

    prediction = analysis["prediction"]
    is_bullish_prediction = "BULLISH" in prediction and "BEARISH" not in prediction
    is_bearish_prediction = "BEARISH" in prediction

    backtest_result = None
    if is_bullish_prediction:
        backtest_result = backtest_condition(df_longer_history, condition_ihsg_bullish_strong, forward_days=5)
    elif is_bearish_prediction:
        backtest_result = backtest_condition(df_longer_history, condition_ihsg_bearish_strong, forward_days=5)
    # Kalau prediction SIDEWAYS/MIXED, backtest_result tetap None --
    # tidak ada kondisi bullish/bearish strong yang relevan untuk dicek

    analysis["backtest_result"] = backtest_result
    return analysis
