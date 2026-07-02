# =========================
# AI SCORE (RULE-BASED SCORING)
# =========================
# CATATAN PENTING UNTUK TRANSPARANSI: meskipun dinamai "AI Score" di
# command /ranah, /aiscore, /airank, ini BUKAN model machine learning.
# Ini adalah sistem skoring berbasis aturan (rule-based) yang mengukur
# kekuatan teknikal dari beberapa dimensi yang berbeda, setiap dimensi
# dengan bobot berbasis riset akademik.
#
# DASAR PEMILIHAN KRITERIA DAN BOBOT (dicatat untuk transparansi):
# Riset yang mendasari versi ini (upgrade dari versi lama yang hanya
# 4 kondisi + StochRSI):
# 1. QuantifiedStrategies.com (2026): backtest MACD+RSI 73% win rate
#    atas 235 trade → MACD dan RSI diberi bobot tertinggi (30 poin)
# 2. Journal of Autonomous Intelligence (2024): EMA+RSI combined
#    strategy 66.7% win rate → dikonfirmasi RSI adalah inti paling
#    andal
# 3. El-Mal journal Indonesia (2024, LQ45 BEI 2022-2023): RSI + MACD
#    paling akurat untuk pengambilan keputusan investasi saham IDX
# 4. Minervini Trend Template: MA alignment (50>150>200) terbukti
#    menyaring saham Stage 2 uptrend yang outperform pasar
# 5. Volume confirmation: volume spike + harga naik = konfirmasi
#    institusional (konsisten dari semua sumber di atas)
#
# DISTRIBUSI BOBOT (total 100 poin):
# - MACD + RSI kombinasi: 30 poin (paling kuat berdasarkan jurnal)
# - MA Trend (multi-timeframe, Minervini-inspired): 25 poin
# - Volume confirmation: 20 poin
# - Bollinger Band position: 10 poin
# - StochRSI (konfirmasi tambahan): 10 poin
# - Momentum harga 5 hari: 5 poin (bonus kecil)

from core.indicators import calculate_rsi, calculate_stochrsi, calculate_macd, calculate_bollinger_bands, calculate_atr
import math


def calculate_ai_score_from_df(df) -> dict | None:
    """Hitung AI Score (0-100) dari DataFrame OHLCV yang sudah didownload
    dan dibersihkan. Murni kalkulasi, tidak melakukan I/O apapun.

    Returns None kalau data tidak cukup (< 50 baris).

    Kriteria berbasis riset:
    - MACD+RSI kombinasi (30 poin) -- 73% win rate dari backtest jurnal
    - MA trend alignment (25 poin) -- Minervini Trend Template
    - Volume confirmation (20 poin) -- konfirmasi kelembagaan
    - Bollinger Band position (10 poin) -- volatilitas & posisi harga
    - StochRSI (10 poin) -- konfirmasi oversold/overbought
    - Momentum 5 hari (5 poin) -- bonus momentum jangka pendek
    """
    if len(df) < 50:
        return None

    current_price = float(df["Close"].iloc[-1])
    prev_price = float(df["Close"].iloc[-2]) if len(df) >= 2 else current_price
    volume = float(df["Volume"].iloc[-1])
    close = df["Close"]

    def safe_float(v, default=0.0):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return default
        try:
            return float(v)
        except Exception:
            return default

    # ===== 1. MACD + RSI KOMBINASI (30 poin) =====
    # Sumber: QuantifiedStrategies.com backtest 73% win rate
    # MACD 12,26,9 standar + RSI 14 standar
    macd_line, signal_line, histogram = calculate_macd(close)
    rsi_series = calculate_rsi(close)

    macd_now = safe_float(macd_line.iloc[-1])
    signal_now = safe_float(signal_line.iloc[-1])
    hist_now = safe_float(histogram.iloc[-1])
    hist_prev = safe_float(histogram.iloc[-2])
    rsi_now = safe_float(rsi_series.iloc[-1], 50.0)

    macd_score = 0
    macd_detail = ""
    if macd_now > signal_now and hist_now > 0 and hist_now > hist_prev:
        macd_score = 20  # MACD bullish DAN menguat = kondisi terbaik
        macd_detail = f"MACD bullish & menguat (hist {hist_now:+.2f})"
    elif macd_now > signal_now and hist_now > 0:
        macd_score = 13
        macd_detail = f"MACD bullish (hist {hist_now:+.2f})"
    elif macd_now > signal_now:
        macd_score = 8
        macd_detail = "MACD di atas signal (hist tipis)"
    else:
        macd_score = 0
        macd_detail = f"MACD bearish (hist {hist_now:+.2f})"

    rsi_score = 0
    rsi_detail = ""
    if 40 <= rsi_now <= 65:
        rsi_score = 10   # zona momentum sehat, bukan overbought
        rsi_detail = f"RSI {rsi_now:.1f} (zona optimal 40-65)"
    elif rsi_now < 30:
        rsi_score = 8    # oversold = potensi reversal naik
        rsi_detail = f"RSI {rsi_now:.1f} (oversold, potensi rebound)"
    elif 30 <= rsi_now < 40:
        rsi_score = 5
        rsi_detail = f"RSI {rsi_now:.1f} (borderline oversold)"
    elif 65 < rsi_now <= 75:
        rsi_score = 4
        rsi_detail = f"RSI {rsi_now:.1f} (momentum kuat tapi waspada)"
    else:
        rsi_score = 0
        rsi_detail = f"RSI {rsi_now:.1f} (overbought)"

    macd_rsi_total = macd_score + rsi_score  # max 30

    # ===== 2. MA TREND ALIGNMENT (25 poin) =====
    # Minervini Trend Template: harga > MA50, MA50 > MA20, MA200 naik
    ma5 = safe_float(close.rolling(5).mean().iloc[-1], current_price)
    ma20 = safe_float(close.rolling(20).mean().iloc[-1], current_price)
    ma50 = safe_float(close.rolling(50).mean().iloc[-1], current_price)
    ma200 = safe_float(close.rolling(200).mean().iloc[-1], current_price) if len(close) >= 200 else current_price
    ma200_1m = safe_float(close.rolling(200).mean().iloc[-22], ma200) if len(close) >= 222 else ma200

    ma_score = 0
    ma_detail = ""
    if current_price > ma50 > ma20 and ma200 > ma200_1m:
        ma_score = 25   # Stage 2 Minervini: semua MA aligned, MA200 rising
        ma_detail = "Stage 2 uptrend (MA alignment sempurna)"
    elif current_price > ma50 and ma50 > ma20:
        ma_score = 18
        ma_detail = "Uptrend kuat (harga > MA50 > MA20)"
    elif current_price > ma20 and ma20 > ma50 * 0.98:
        ma_score = 12
        ma_detail = f"Trend positif (harga > MA20={ma20:,.0f})"
    elif current_price > ma5 and ma5 > ma20:
        ma_score = 8
        ma_detail = "Momentum jangka pendek positif (MA5 > MA20)"
    elif current_price < ma50 < ma20:
        ma_score = 0
        ma_detail = "Downtrend (harga < MA50 < MA20)"
    else:
        ma_score = 4
        ma_detail = "Trend campuran/sideways"

    # ===== 3. VOLUME CONFIRMATION (20 poin) =====
    # Volume spike + harga naik = konfirmasi lebih kuat
    vol_ma20 = safe_float(df["Volume"].rolling(20).mean().iloc[-1], volume)
    vol_ratio = volume / vol_ma20 if vol_ma20 > 0 else 1.0
    change_1d = ((current_price / prev_price) - 1) * 100 if prev_price > 0 else 0

    vol_score = 0
    vol_detail = ""
    if vol_ratio >= 2.0 and change_1d > 0:
        vol_score = 20   # spike besar + harga naik = sinyal terkuat
        vol_detail = f"Volume {vol_ratio:.1f}x rata-rata + harga naik (konfirmasi kuat)"
    elif vol_ratio >= 1.5 and change_1d > 0:
        vol_score = 15
        vol_detail = f"Volume {vol_ratio:.1f}x rata-rata + harga naik"
    elif vol_ratio >= 1.5:
        vol_score = 10   # volume besar tapi arah belum jelas
        vol_detail = f"Volume {vol_ratio:.1f}x rata-rata (arah belum jelas)"
    elif vol_ratio >= 1.2:
        vol_score = 7
        vol_detail = f"Volume sedikit di atas rata-rata ({vol_ratio:.1f}x)"
    elif volume > 500_000:
        vol_score = 5    # minimal likuiditas terpenuhi
        vol_detail = f"Likuiditas memadai ({int(volume):,})"
    else:
        vol_score = 0
        vol_detail = f"Volume rendah ({int(volume):,}) -- kurang likuid"

    # ===== 4. BOLLINGER BAND POSITION (10 poin) =====
    # Posisi harga dalam BB dan kondisi squeeze
    bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(close)
    bb_up = safe_float(bb_upper.iloc[-1], current_price * 1.05)
    bb_lo = safe_float(bb_lower.iloc[-1], current_price * 0.95)
    bb_width = bb_up - bb_lo
    bb_position = (current_price - bb_lo) / bb_width * 100 if bb_width > 0 else 50

    bb_score = 0
    bb_detail = ""
    if current_price < bb_lo:
        bb_score = 8   # di bawah lower BB = oversold, potensi rebound
        bb_detail = "Di bawah BB lower (oversold, potensi rebound)"
    elif 20 <= bb_position <= 60:
        bb_score = 10  # zona mid-to-lower = entry zone terbaik
        bb_detail = f"Di zona tengah-bawah BB ({bb_position:.0f}%) -- zona entry"
    elif 60 < bb_position < 80:
        bb_score = 6
        bb_detail = f"Di atas tengah BB ({bb_position:.0f}%)"
    elif bb_position >= 100:
        bb_score = 3
        bb_detail = f"Breakout di atas BB upper ({bb_position:.0f}%) -- momentum kuat tapi rawan koreksi"
    elif bb_position >= 80:
        bb_score = 3   # mendekati upper = mulai overbought
        bb_detail = f"Mendekati BB upper ({bb_position:.0f}%) -- waspada"
    else:
        bb_score = 4
        bb_detail = f"Posisi BB {bb_position:.0f}%"

    # ===== 5. STOCHRSI (10 poin) =====
    stoch_k, stoch_d = calculate_stochrsi(close)
    current_k = safe_float(stoch_k.iloc[-1], 50.0)
    current_d = safe_float(stoch_d.iloc[-1], 50.0)
    prev_k = safe_float(stoch_k.iloc[-2] if len(stoch_k) > 1 else current_k, current_k)
    prev_d = safe_float(stoch_d.iloc[-2] if len(stoch_d) > 1 else current_d, current_d)

    golden_cross = (prev_k <= prev_d and current_k > current_d)
    is_oversold = current_k < 20 and current_d < 20
    is_overbought = current_k > 80 and current_d > 80

    stoch_score = 0
    stoch_detail = ""
    if is_oversold and golden_cross:
        stoch_score = 10  # oversold + golden cross = terkuat
        stoch_detail = f"StochRSI oversold + golden cross (K={current_k:.0f})"
    elif is_oversold:
        stoch_score = 8
        stoch_detail = f"StochRSI oversold (K={current_k:.0f}) -- potensi rebound"
    elif golden_cross:
        stoch_score = 7
        stoch_detail = f"StochRSI golden cross (K={current_k:.0f} > D={current_d:.0f})"
    elif 30 <= current_k <= 60:
        stoch_score = 5
        stoch_detail = f"StochRSI netral-bullish (K={current_k:.0f})"
    elif is_overbought:
        stoch_score = 1
        stoch_detail = f"StochRSI overbought (K={current_k:.0f}) -- hati-hati"
    else:
        stoch_score = 2
        stoch_detail = f"StochRSI {current_k:.0f}"

    # ===== 6. MOMENTUM 5 HARI (5 poin bonus) =====
    change_5d = 0.0
    if len(df) >= 6:
        prev_5d = safe_float(df["Close"].iloc[-6], current_price)
        change_5d = ((current_price / prev_5d) - 1) * 100 if prev_5d > 0 else 0

    momentum_score = 0
    if change_5d >= 3:
        momentum_score = 5
    elif change_5d >= 1:
        momentum_score = 3
    elif change_5d >= 0:
        momentum_score = 1

    # ===== TOTAL SCORE =====
    total = macd_rsi_total + ma_score + vol_score + bb_score + stoch_score + momentum_score
    score = min(int(total), 100)

    # ===== KONDISI LAMA (backward compat untuk handler yang sudah ada) =====
    vol_ma5 = safe_float(df["Volume"].rolling(5).mean().iloc[-1], volume)
    vol_ratio_ma = vol_ma5 / vol_ma20 if vol_ma20 > 0 else 1.0
    cond_ma = ma5 > ma20
    cond_volume_spike = vol_ratio_ma > 1.2
    cond_price = current_price > 200
    cond_volume_min = volume > 500_000
    signal_conditions_met = sum([cond_ma, cond_volume_spike, cond_price, cond_volume_min])

    # ===== ATR (volatilitas, untuk konteks /insight -- BARU) =====
    atr_value = calculate_atr(df)
    atr_pct = (atr_value / current_price * 100) if current_price > 0 else 0.0

    # ===== REASONS (ringkasan untuk display) + CONFLUENCE COUNT (BARU) =====
    # Hitung eksplisit berapa indikator bullish/bearish/netral -- dipakai
    # /insight untuk narasi "konfluensi sinyal" (mirip "5 Bearish / 1
    # Bullish / 2 Netral" di laporan analisis profesional), BUKAN dengan
    # parsing emoji string (rapuh), tapi tracking eksplisit per kondisi.
    bullish_count = 0
    bearish_count = 0
    netral_count = 0

    reasons = []
    if macd_now > signal_now:
        reasons.append(f"✅ MACD: {macd_detail}")
        bullish_count += 1
    else:
        reasons.append(f"❌ MACD: {macd_detail}")
        bearish_count += 1

    if rsi_score >= 8:
        reasons.append(f"✅ RSI: {rsi_detail}")
        bullish_count += 1
    elif rsi_score >= 4:
        reasons.append(f"⚠️ RSI: {rsi_detail}")
        netral_count += 1
    else:
        reasons.append(f"❌ RSI: {rsi_detail}")
        bearish_count += 1

    if ma_score >= 18:
        reasons.append(f"✅ MA Trend: {ma_detail}")
        bullish_count += 1
    elif ma_score >= 8:
        reasons.append(f"⚠️ MA Trend: {ma_detail}")
        netral_count += 1
    else:
        reasons.append(f"❌ MA Trend: {ma_detail}")
        bearish_count += 1

    if vol_score >= 15:
        reasons.append(f"✅ Volume: {vol_detail}")
        bullish_count += 1
    elif vol_score >= 5:
        reasons.append(f"⚠️ Volume: {vol_detail}")
        netral_count += 1
    else:
        reasons.append(f"❌ Volume: {vol_detail}")
        bearish_count += 1

    if bb_score >= 8:
        reasons.append(f"✅ Bollinger: {bb_detail}")
        bullish_count += 1
    else:
        reasons.append(f"⚠️ Bollinger: {bb_detail}")
        netral_count += 1

    if stoch_score >= 7:
        reasons.append(f"✅ StochRSI: {stoch_detail}")
        bullish_count += 1
    else:
        reasons.append(f"⚠️ StochRSI: {stoch_detail}")
        netral_count += 1

    # ===== RATING =====
    if score >= 75:
        rating, recommendation, color, signal_emoji = "SANGAT BAGUS", "STRONG BUY", "#00ff88", "🚀"
    elif score >= 60:
        rating, recommendation, color, signal_emoji = "BAGUS", "BUY", "#00d2ff", "📈"
    elif score >= 45:
        rating, recommendation, color, signal_emoji = "NETRAL", "HOLD", "#ffd700", "⏸️"
    elif score >= 30:
        rating, recommendation, color, signal_emoji = "CUKUP", "WATCH", "#ff8c00", "👀"
    else:
        rating, recommendation, color, signal_emoji = "BURUK", "AVOID", "#ff4444", "⚠️"

    vol_ratio = volume / vol_ma20 if vol_ma20 > 0 else 1.0  # untuk backward compat di handler

    return {
        "score": round(score, 1),
        "rating": rating,
        "recommendation": recommendation,
        "color": color,
        "signal": signal_emoji,
        "reasons": reasons,
        "price": current_price,
        "change_1d": round(change_1d, 2),
        "change_5d": round(change_5d, 2),
        "rsi": round(rsi_now, 1),
        "stoch_k": round(current_k, 1),
        "stoch_d": round(current_d, 1),
        "vol_ratio": round(vol_ratio, 1),
        "vol_ratio_ma": round(vol_ratio_ma, 1),
        "ma5_ma20": "MA5 > MA20" if cond_ma else "MA5 < MA20",
        "golden_cross": golden_cross,
        "is_oversold": is_oversold,
        "is_overbought": is_overbought,
        "cond_ma": cond_ma,
        "cond_volume_spike": cond_volume_spike,
        "cond_price": cond_price,
        "cond_volume_min": cond_volume_min,
        "signal_conditions_met": signal_conditions_met,
        # ===== FIELD BARU (untuk /insight yang lebih kaya) =====
        # Semua nilai ini SEBENARNYA SUDAH DIHITUNG secara internal di
        # atas untuk keperluan skoring -- cuma belum di-expose ke return
        # dict sebelumnya. Ini PURE ADDITION (tidak mengubah field lama
        # apapun), aman untuk semua caller existing (/aiscore, /compare,
        # compare_chart.py) yang sudah pakai fungsi ini.
        "macd_hist": round(hist_now, 2),
        "macd_bullish": macd_now > signal_now,
        "bb_position": round(bb_position, 1),
        "ma20": round(ma20, 0),
        "ma50": round(ma50, 0),
        "ma200": round(ma200, 0) if len(close) >= 200 else None,
        "atr_pct": round(atr_pct, 2),
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "netral_count": netral_count,
        # Detail string SATU SUMBER KEBENARAN -- dipakai /insight supaya
        # narasi prosa SELALU konsisten dengan klasifikasi yang dipakai
        # confluence count (BUKAN re-derive perbandingan baru yang bisa
        # diam-diam pakai kriteria berbeda dan kelihatan "kontradiksi"
        # secara teks meski masing-masing benar menurut definisinya
        # sendiri -- ditemukan & diperbaiki saat membangun /insight v2).
        "ma_detail": ma_detail,
        "macd_detail": macd_detail,
        "rsi_detail": rsi_detail,
        "vol_detail": vol_detail,
        "bb_detail": bb_detail,
        "stoch_detail": stoch_detail,
        # ===== KOMPONEN SKOR ASLI (BARU, untuk /ranah & /aiscore) =====
        # BUG NYATA DITEMUKAN & DIPERBAIKI (Juni 2026): handlers/
        # ai_score_handlers.py SEBELUMNYA menghitung breakdown skor
        # SENDIRI secara terpisah (ma_score = 25 if cond_ma else 10, dkk)
        # dengan bobot LAMA (MA 25/Volume 25/Harga 15/VolumeMin 15/
        # Stoch 20) yang SAMA SEKALI TIDAK SAMA dengan bobot yang
        # SUNGGUHAN dipakai untuk menghitung result['score'] di bawah
        # (MACD+RSI 30/MA 25/Volume 20/BB 10/Stoch 10/Momentum 5) --
        # breakdown yang ditampilkan ke user TIDAK PERNAH benar-benar
        # menjumlah ke score yang ditampilkan. Field di bawah ini
        # adalah skor komponen ASLI yang SUNGGUHAN dipakai (PURE
        # ADDITION, sudah dihitung secara internal di atas, cuma belum
        # di-expose) -- breakdown yang dibangun dari field ini DIJAMIN
        # menjumlah persis ke 'score' di atas, karena memang sumbernya
        # sama persis.
        "macd_rsi_score": macd_rsi_total,  # 0-30
        "ma_trend_score": ma_score,  # 0-25
        "volume_score": vol_score,  # 0-20
        "bollinger_score": bb_score,  # 0-10
        "stochrsi_score": stoch_score,  # 0-10
        "momentum_score": momentum_score,  # 0-5
    }
