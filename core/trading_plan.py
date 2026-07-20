# =========================
# TRADING PLAN CALCULATOR
# =========================
# Modul ini berisi LOGIC KALKULASI MURNI untuk trading plan (4 skenario
# entry: normal/pullback/deep/breakout, masing-masing dengan SL & 3 level
# TP). Dipisah dari I/O (download data, format pesan, generate chart)
# supaya kalkulasinya bisa ditest dengan data dummy tanpa perlu network
# ataupun matplotlib -- ini krusial karena ini bagian yang menentukan
# angka entry/SL/TP yang akan dilihat dan dipakai user untuk trading
# sungguhan.
#
# Semua rumus di sini dipertahankan IDENTIK dengan main.py versi lama
# (sudah diverifikasi numerik, lihat hasil test di akhir percakapan).
# Yang berubah hanya STRUKTUR kode: pemisahan lapisan kalkulasi vs I/O
# vs formatting, supaya lebih mudah ditest dan dirawat.

from core.indicators import calculate_atr, calculate_support_resistance_deep, calculate_confidence, calculate_rsi


# Floor minimum jarak SL ke entry -- permintaan eksplisit user: SL yang
# cuma mengikuti support TERDEKAT (S1) apa adanya kadang jatuh SANGAT DEKAT
# dari entry (pernah kelihatan senyata -0.4% di JPFA/UNTR) kalau kebetulan
# harga sedang duduk persis di atas S1 -- itu nyaris pasti kena cuma dari
# noise harian biasa (bid-ask, candle intraday), BUKAN risiko sungguhan
# yang berarti tren teknikalnya sudah rusak. Padahal kalau tren teknikal
# masih bagus, posisi semestinya masih layak di-hold. Floor ini memberi SL
# jarak minimum yang wajar, SAMA dgn floor TP1 (max(3.0, risk_pct)) yang
# sudah ada -- konsisten, bukan angka baru yang asal pilih.
MIN_SL_PCT = 3.0

# Diskon entry PULLBACK dari harga saat ini (persen). REVISI KETIGA sehari
# (S1 pivot -> MA20 -> 1x ATR -> INI, permintaan user langsung sambil
# lihat data nyata: "nih kaya gini kejauhan keburu org pada tp saya
# mintanya entry pada hari itu bukan nunggu lama kaya gitu" -- BRMS
# tercatat Rp478 tapi harga sudah lari ke Rp505 (+5,65%) SEBELUM entry
# sempat kena, padahal TP1-nya cuma Rp500 -- pasar sudah "lewat" area TP
# sebelum PENDING_ENTRY sempat jadi OPEN. ATR (~1x, sering 3-6% dari
# harga) & MA20 (bisa >5-10% saat tren kuat) SAMA-SAMA masih terlalu
# dalam. Angka ini SENGAJA kecil (sisi bawah rentang 0,5-1% yang dipilih
# user) supaya PENDING_ENTRY realistis kena LEWAT FLUKTUASI HARIAN WAJAR
# (hari yang sama/besoknya), bukan menunggu pullback besar yang saham
# keburu jalan duluan sebelum sempat terjadi.
PULLBACK_DISCOUNT_PCT = 0.5


def _calc_entry_levels(entry: float, atr: float, sr: dict) -> dict:
    """Hitung SL dan 3 level TP untuk satu titik entry. Dipakai bersama
    oleh calculate_fixed_entry_levels (4 skenario watchlist).

    SL dipilih dari level SUPPORT SUNGGUHAN (S1..S4, pivot Fibonacci --
    lihat calculate_support_resistance_deep -- S1 PALING DEKAT dari entry,
    S4 PALING JAUH), bukan cuma S1 apa adanya: kalau S1 (atau S2, S3)
    ternyata terlalu dekat (jaraknya di bawah floor MIN_SL_PCT), turun ke
    level BERIKUTNYA yang lebih dalam (S2/S3/S4) -- diambil yang PERTAMA
    kali cukup jauh, bukan langsung lompat ke floor persentase generik yg
    tidak berdasar level harga sungguhan apa pun. Permintaan user
    eksplisit: "sl nya kedeketan, kalo bisa sl nya di support" -- SL harus
    tetap berarti sebagai level teknikal (support asli), bukan angka %
    yang dikarang begitu S1 kebetulan dekat. Floor persentase (entry x
    (1 - MIN_SL_PCT%)) HANYA dipakai sbg jaring pengaman terakhir kalau
    SEMUA level S1..S4 di bawah entry sudah dicoba dan tetap tidak ada
    yang cukup jauh (atau tidak ada support yang berada di bawah entry
    sama sekali)."""
    # S1..S4 sudah terurut dari calculate_support_resistance_deep sbg
    # terdekat->terjauh (S1 > S2 > S3 > S4 dari sisi harga) -- urutan itu
    # dipertahankan di sini (bukan di-sort ulang) supaya "coba S1 dulu,
    # baru S2, dst" sesuai definisi levelnya sendiri.
    support_levels = [sr["S1"], sr["S2"], sr["S3"], sr["S4"]]
    supports_below = [s for s in support_levels if s < entry]

    stop_loss = None
    for support in supports_below:
        candidate_sl = support - (atr * 0.2)
        candidate_risk_pct = ((entry - candidate_sl) / entry) * 100 if entry > 0 else 0
        if candidate_risk_pct >= MIN_SL_PCT:
            stop_loss = candidate_sl
            break

    if stop_loss is None:
        # Tidak ada level S1..S4 (di bawah entry) yang cukup jauh, atau
        # tidak ada support di bawah entry sama sekali -- fallback floor
        # persentase generik (jaring pengaman lama).
        stop_loss = entry * (1 - MIN_SL_PCT / 100)

    risk_abs = entry - stop_loss
    risk_pct = (risk_abs / entry) * 100 if entry > 0 else 5
    if risk_pct < MIN_SL_PCT:
        # Jaring pengaman terakhir (harusnya jarang/tidak pernah kena
        # kalau loop di atas benar) -- hitung ULANG stop_loss dari floor
        # supaya risk_pct dan sl (Rp) tetap konsisten satu sama lain.
        risk_pct = MIN_SL_PCT
        stop_loss = entry * (1 - MIN_SL_PCT / 100)
    tp1_pct = max(3.0, risk_pct)
    tp2_pct = tp1_pct * 2
    tp3_pct = tp1_pct * 3

    return {
        "entry": round(entry, 0),
        "sl": round(stop_loss, 0),
        "risk_pct": round(risk_pct, 1),
        "tp1_pct": round(tp1_pct, 1),
        "tp2_pct": round(tp2_pct, 1),
        "tp3_pct": round(tp3_pct, 1),
        "tp1": round(entry * (1 + tp1_pct / 100), 0),
        "tp2": round(entry * (1 + tp2_pct / 100), 0),
        "tp3": round(entry * (1 + tp3_pct / 100), 0),
    }


def _determine_entry_points(current_price: float, atr: float, sr: dict) -> dict:
    """Tentukan 4 titik entry (normal/pullback/deep/breakout) berdasarkan
    harga saat ini, ATR, dan level support/resistance.

    PULLBACK -- REVISI KETIGA sehari (S1 pivot -> MA20 -> 1x ATR -> INI).
    Kedua percobaan sebelumnya (MA20, lalu 1x ATR ~3-6% dari harga) SAMA-
    SAMA masih dikoreksi user setelah lihat data nyata: BRMS tercatat
    entry Rp478, tapi harga SUDAH lari ke Rp505 (+5,65%) SEBELUM entry
    sempat kena -- padahal TP1-nya cuma Rp500, jadi pasar sudah "lewat"
    area TP sebelum PENDING_ENTRY sempat jadi OPEN sama sekali ("kejauhan
    keburu org pada tp ... saya mintanya entry pada hari itu bukan nunggu
    lama"). SEKARANG cuma diskon KECIL (lihat PULLBACK_DISCOUNT_PCT, 0,5%)
    dari harga saat sinyal dicatat -- SENGAJA supaya PENDING_ENTRY
    realistis kena lewat fluktuasi harian wajar (hari yang sama/besoknya),
    BUKAN nunggu pullback besar yang keburu dilewati tren duluan. Ini
    mengorbankan sebagian "tunggu harga lebih baik" demi jauh lebih
    realistis kena -- trade-off yang sengaja dipilih user."""
    entry_normal = current_price
    entry_pullback = current_price * (1 - PULLBACK_DISCOUNT_PCT / 100)
    entry_deep = sr["S2"] if sr["S2"] < current_price else current_price * 0.96
    breakout_level = sr["R1"] + (atr * 0.2)
    entry_breakout = breakout_level if breakout_level > current_price else current_price * 1.02

    return {
        "normal": entry_normal,
        "pullback": entry_pullback,
        "deep": entry_deep,
        "breakout": entry_breakout,
    }


def classify_entry_mode(
    df,
    *,
    is_breakout: bool = False,
    volume_confirmation: bool = False,
) -> str:
    """Klasifikasi momentum entry: AGRESIF vs AREA_AMAN.

    Permintaan user langsung: "nentuin entry audit sinyalnya lebih akurat
    lagi jadi kamu tuh tau nih momentum saham yg masuk sinyal harus masuk
    agresif atau masuk area aman dlu gitu".

    AGRESIF (dua jalur -- menunggu pullback berisiko KETINGGALAN karena
    harga cenderung terus naik, jadi entry LANGSUNG di market):
    - Jalur breakout: breakout R1 + volume >2x (walk-forward validated) --
      StochRSI overbought TIDAK jadi syarat di sini (saat breakout momentum,
      StochRSI wajar mentok tinggi; itu ciri momentum, bukan reversal).
    - Jalur momentum konfluent (tanpa breakout resmi): MACD bullish menguat
      + RSI zona optimal + harga > MA20 + StochRSI belum overbought -- tetap
      ketat karena tanpa breakout, overbought benar menaikkan risiko reversal.

    Entry AGRESIF dicatat di harga MARKET (skenario 'normal'), BUKAN level
    breakout R1+ATR -- permintaan user: breakout kadang FAKE (lihat
    web/app.py::confidence & record_top_picks).

    AREA_AMAN = momentum belum cukup konfluent, entry skenario pullback
    (tunggu harga turun ke support) lebih aman -- salah satu atau lebih
    kondisi "agresif" tidak terpenuhi (volume lemah, MACD bearish, RSI
    terlalu rendah/tinggi, harga < MA20, StochRSI overbought).

    INDIKATOR YANG DIPAKAI -- semuanya SUDAH ADA & teruji di codebase:
    - is_breakout + volume_confirmation: dari calculate_fixed_entry_levels_
      from_df() / condition_breakout() di screening_pro.py (walk-forward
      validated)
    - MACD histogram: dari core/indicators.py::calculate_macd()
    - RSI(14): dari core/indicators.py::calculate_rsi()
    - MA20: rolling 20 standar
    - StochRSI: dari core/indicators.py::calculate_stochrsi()

    Fungsi ini MURNI kalkulasi (tidak melakukan I/O), aman ditest dengan
    data dummy."""
    import math
    from core.indicators import calculate_macd, calculate_rsi, calculate_stochrsi

    if df is None or len(df) < 50:
        return "AREA_AMAN"

    close = df["Close"]
    current_price = float(close.iloc[-1])

    def safe(v, default=0.0):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return default
        try:
            return float(v)
        except Exception:
            return default

    # 1. MACD bullish & menguat (histogram > 0 DAN naik vs kemarin)
    _, _, histogram = calculate_macd(close)
    hist_now = safe(histogram.iloc[-1])
    hist_prev = safe(histogram.iloc[-2])
    macd_bullish_strong = hist_now > 0 and hist_now > hist_prev

    # 2. RSI di zona optimal (40-70, bukan overbought bukan oversold)
    rsi = calculate_rsi(close)
    rsi_now = safe(rsi.iloc[-1], 50)
    rsi_optimal = 40 <= rsi_now <= 70

    # 3. Harga > MA20 (tren pendek positif)
    ma20 = safe(close.rolling(20).mean().iloc[-1], current_price)
    above_ma20 = current_price > ma20

    # 4. StochRSI BUKAN overbought (K < 80)
    stoch_k, _ = calculate_stochrsi(close)
    k_now = safe(stoch_k.iloc[-1], 50)
    not_overbought = k_now < 80

    # 5. Volume dipakai dari is_breakout + volume_confirmation yang sudah
    #    dihitung caller (walk-forward validated, bukan ambang baru)

    # ----- Keputusan -----
    # Jalur 1 (PALING kuat): breakout + volume confirmed -- sudah terbukti
    # walk-forward, jadi langsung AGRESIF. StochRSI overbought SENGAJA TIDAK
    # dijadikan syarat di jalur ini (keputusan user): saat breakout momentum
    # sungguhan, StochRSI justru WAJAR mentok ~100 -- itu CIRI momentum kuat,
    # bukan sinyal reversal. Menjadikannya gate malah memblokir entry agresif
    # TEPAT ketika momentumnya paling kuat (temuan nyata: dari 25 saham cuma
    # SSIA yang breakout + volume >2x, dan itu pun ter-AREA_AMAN semata-mata
    # gara2 StochRSI 100 -- jalur AGRESIF jadi praktis mati).
    if is_breakout and volume_confirmation:
        return "AGRESIF"

    # Jalur 2: BUKAN breakout resmi, tapi momentum teknikal SANGAT konfluent
    # (MACD + RSI + MA20 + StochRSI semua selaras) -- SENGAJA tetap ketat,
    # termasuk not_overbought (keputusan user: jalur non-breakout tetap
    # ketat). Tanpa struktur breakout yang mengonfirmasi, StochRSI overbought
    # di sini memang menaikkan risiko reversal, jadi gate-nya dipertahankan.
    if macd_bullish_strong and rsi_optimal and above_ma20 and not_overbought:
        return "AGRESIF"

    return "AREA_AMAN"


def calculate_fixed_entry_levels_from_df(df, created_date_str: str) -> dict | None:
    """Hitung 4 skenario fixed entry levels (dipakai saat add ke watchlist).
    Murni kalkulasi -- caller bertanggung jawab menyediakan df yang sudah
    didownload dan dibersihkan, serta timestamp untuk created_date.

    Returns None kalau data tidak cukup (< 50 baris).
    """
    if df.empty or len(df) < 50:
        return None

    current_price = float(df["Close"].iloc[-1])
    atr = calculate_atr(df)
    sr = calculate_support_resistance_deep(df)

    entries = _determine_entry_points(current_price, atr, sr)

    scenario_meta = {
        "normal": {"name": "NORMAL", "display_name": "📊 NORMAL"},
        "pullback": {"name": "PULLBACK (-0.5%)", "display_name": "📉 PULLBACK (-0.5%)"},
        "deep": {"name": "DEEP (S2)", "display_name": "🔻 DEEP (S2)"},
        "breakout": {"name": "BREAKOUT", "display_name": "🚀 BREAKOUT"},
    }

    scenarios = {}
    for key, entry_price in entries.items():
        scenarios[key] = {
            **scenario_meta[key],
            "key": key,
            "entry": entry_price,
            **_calc_entry_levels(entry_price, atr, sr),
        }

    # recommended_scenario (permintaan user langsung: "skenario nya antara
    # pullback atau breakout aja tapi valid soalnya kalo pullback kadang ga
    # kena yg ada malah kena tp") -- SEBELUM ini Top Pick SELALU pakai
    # 'pullback' apa adanya, padahal kalau saham SEDANG breakout momentum
    # harga jarang mundur ke S1 lagi -- nunggu pullback yang tidak pernah
    # datang membuat sinyal berakhir EXPIRED_NO_ENTRY padahal harga sudah
    # lanjut jalan (bahkan sempat menyentuh level yang SEHARUSNYA jadi TP
    # kalau entry-nya breakout, bukan pullback).
    #
    # PENTING -- SENGAJA TIDAK reuse is_breakout=(current_price > sr["R1"])
    # dari calculate_advanced_plan_from_df: R1 di situ dihitung dari H/L/C
    # HARI YANG SAMA (baris terakhir df itu sendiri), dan secara matematis
    # pivot+range*0.382 SELALU >= Close hari itu (dibuktikan lewat aljabar
    # + sanity check langsung -- bahkan candle yang closing PERSIS di High
    # tetap menghasilkan R1 > Close). Itu artinya is_breakout di fungsi itu
    # PADA DASARNYA TIDAK PERNAH true -- bug laten terpisah, di luar scope
    # perubahan ini, TIDAK disentuh di sini supaya tidak memperbesar blast
    # radius (fitur "Rencana Trading" lain yang memakainya).
    #
    # Definisi breakout yang dipakai DI SINI reuse PERSIS formula
    # condition_breakout() di core/screening_pro.py::walk_forward_validate
    # (mode 'breakout', SUDAH divalidasi walk-forward, bukan ambang baru
    # yang dikarang): close hari ini > 98% dari HIGH 20 HARI SEBELUMNYA
    # (index i-20:i, TIDAK termasuk hari ini -- bukan self-referential),
    # DAN volume hari ini > 2x median volume 20 hari sebelumnya.
    if len(df) >= 21:
        prior_high_20 = float(df["Close"].iloc[-21:-1].max())
        prior_vol_median = float(df["Volume"].iloc[-21:-1].median())
        is_breakout = current_price > prior_high_20 * 0.98
        volume_confirmation = bool(prior_vol_median > 0 and float(df["Volume"].iloc[-1]) > prior_vol_median * 2)
    else:
        is_breakout = False
        volume_confirmation = False
    recommended_scenario = "breakout" if (is_breakout and volume_confirmation) else "pullback"

    entry_mode = classify_entry_mode(
        df, is_breakout=is_breakout, volume_confirmation=volume_confirmation,
    )

    return {
        "created_date": created_date_str,
        "price_at_create": round(current_price, 0),
        "scenarios": scenarios,
        "is_breakout": is_breakout,
        "volume_confirmation": volume_confirmation,
        "recommended_scenario": recommended_scenario,
        "entry_mode": entry_mode,
    }


def get_hit_scenarios(scenarios: dict, low_today: float, high_today: float) -> list:
    """Tentukan skenario mana yang BENAR-BENAR kena hari ini, berdasarkan
    posisi Low/High harga hari ini relatif ke level entry tiap skenario.

    Urutan prioritas: deep > pullback > breakout > normal (kalau low hari
    ini sudah menembus level deep, itu yang paling relevan dilaporkan,
    bukan normal yang levelnya lebih tinggi).
    """
    result = []

    entry_breakout = scenarios.get("breakout", {}).get("entry", float("inf"))
    entry_normal = scenarios.get("normal", {}).get("entry", float("inf"))
    entry_pullback = scenarios.get("pullback", {}).get("entry", float("inf"))
    entry_deep = scenarios.get("deep", {}).get("entry", float("inf"))

    breakout_kena = high_today >= entry_breakout
    deep_kena = low_today <= entry_deep
    pullback_kena = low_today <= entry_pullback
    normal_kena = (low_today <= entry_normal <= high_today) and not pullback_kena and not deep_kena

    if deep_kena:
        result.append({"key": "deep", "scenario": scenarios["deep"], "entry_price": entry_deep})
    if pullback_kena and not deep_kena:
        result.append({"key": "pullback", "scenario": scenarios["pullback"], "entry_price": entry_pullback})
    if breakout_kena:
        result.append({"key": "breakout", "scenario": scenarios["breakout"], "entry_price": entry_breakout})
    if normal_kena:
        result.append({"key": "normal", "scenario": scenarios["normal"], "entry_price": entry_normal})

    return result


def calculate_advanced_plan_from_df(df, ticker_symbol: str) -> dict | None:
    """Hitung advanced trading plan lengkap: 4 skenario entry dengan SL,
    3-level TP, R:R ratio, dan position sizing (modal Rp100jt, risk 3%).

    Murni kalkulasi, return dict berisi semua angka mentah -- formatting
    jadi pesan teks dilakukan terpisah oleh format_advanced_plan_message()
    di modul messages.py supaya logic angka dan logic tampilan tidak
    tercampur.

    Returns None kalau data tidak cukup (< 50 baris).
    """
    if df.empty or len(df) < 50:
        return None

    current_price = float(df["Close"].iloc[-1])
    prev_close = float(df["Close"].iloc[-2])

    atr = calculate_atr(df)
    sr = calculate_support_resistance_deep(df)

    is_breakout = current_price > sr["R1"]
    is_strong_breakout = current_price > sr["R2"]
    volume = float(df["Volume"].iloc[-1])
    avg_volume_20 = df["Volume"].rolling(20).mean().iloc[-1]
    volume_confirmation = volume > (1.3 * avg_volume_20)

    confidence = calculate_confidence(df, current_price, sr, volume_confirmation)

    entries = _determine_entry_points(current_price, atr, sr)
    support_levels = [sr["S1"], sr["S2"], sr["S3"], sr["S4"]]

    def get_stop_loss(entry_price):
        supports_below = [s for s in support_levels if s < entry_price]
        nearest_support = max(supports_below) if supports_below else entry_price * 0.97
        stop_loss = nearest_support - (atr * 0.2)
        return stop_loss, entry_price - stop_loss

    account_size = 100_000_000
    target_risk_pct = 3.0
    max_risk_amount = account_size * (target_risk_pct / 100)

    def calc_pos(risk_abs):
        if risk_abs <= 0:
            return 0
        return max(int(max_risk_amount / risk_abs), 100)

    def calc_tps(entry_price, risk_pct):
        risk_amount = entry_price * (risk_pct / 100)
        min_tp1_pct = max(3.0, risk_pct)
        tp1_amount = entry_price * (min_tp1_pct / 100)
        tp1 = entry_price + tp1_amount
        tp2 = entry_price + (tp1_amount * 2)
        tp3 = entry_price + (tp1_amount * 3)
        rr1 = tp1_amount / risk_amount if risk_amount > 0 else 0
        rr2 = (tp1_amount * 2) / risk_amount if risk_amount > 0 else 0
        rr3 = (tp1_amount * 3) / risk_amount if risk_amount > 0 else 0
        return {
            "tp1": round(tp1, 2), "tp2": round(tp2, 2), "tp3": round(tp3, 2),
            "tp1_pct": round(min_tp1_pct, 1), "tp2_pct": round(min_tp1_pct * 2, 1),
            "tp3_pct": round(min_tp1_pct * 3, 1),
            "rr1": round(rr1, 1), "rr2": round(rr2, 1), "rr3": round(rr3, 1),
            "risk_amount": round(risk_amount, 2), "risk_pct": risk_pct,
        }

    scenarios = {}
    for key, entry_price in entries.items():
        sl, risk_abs = get_stop_loss(entry_price)
        risk_pct = (risk_abs / entry_price) * 100
        pos = calc_pos(risk_abs)
        scenarios[key] = {
            "entry": entry_price,
            "sl": sl,
            "risk_abs": risk_abs,
            "risk_pct": risk_pct,
            "position_size": pos,
            "position_value": pos * entry_price,
            "tp": calc_tps(entry_price, risk_pct),
        }

    ma5 = df["Close"].rolling(5).mean().iloc[-1]
    ma20 = df["Close"].rolling(20).mean().iloc[-1]
    ma50 = df["Close"].rolling(50).mean().iloc[-1]

    if ma5 > ma20 > ma50:
        trend = "BULLISH 🟢 (Strong)"
    elif ma5 > ma20:
        trend = "BULLISH 🟢 (Moderate)"
    elif ma5 < ma20 < ma50:
        trend = "BEARISH 🔴"
    else:
        trend = "NEUTRAL ⚪"

    last_rsi = round(float(calculate_rsi(df["Close"]).iloc[-1]), 2)
    if last_rsi > 70:
        rsi_status = "OVERBOUGHT ⚠️ (Hati-hati beli)"
    elif last_rsi < 30:
        rsi_status = "OVERSOLD 🔥 (Potensi rebound)"
    else:
        rsi_status = "NORMAL ✅"

    vol_ratio = volume / avg_volume_20 if avg_volume_20 > 0 else 1
    if vol_ratio > 1.5:
        vol_status = "🔥 HIGH (Volume besar)"
    elif vol_ratio > 1.2:
        vol_status = "✅ GOOD (Volume di atas rata-rata)"
    elif vol_ratio > 0.8:
        vol_status = "📊 NORMAL"
    else:
        vol_status = "⚠️ LOW (Volume rendah)"

    if is_breakout:
        if is_strong_breakout and volume_confirmation:
            breakout_status = "✅ AKTIF - Strong Breakout dengan volume!"
        else:
            breakout_status = "⚠️ Breakout terdeteksi, tunggu konfirmasi volume"
    else:
        breakout_status = "❌ Belum breakout"

    return {
        "ticker_symbol": ticker_symbol,
        "current_price": current_price,
        "prev_close": prev_close,
        "daily_change_pct": ((current_price / prev_close) - 1) * 100,
        "atr": atr,
        "sr": sr,
        "rsi": last_rsi,
        "rsi_status": rsi_status,
        "trend": trend,
        "volume": volume,
        "vol_ratio": vol_ratio,
        "vol_status": vol_status,
        "breakout_status": breakout_status,
        "confidence": confidence,
        "scenarios": scenarios,
        "account_size": account_size,
        "target_risk_pct": target_risk_pct,
        "max_risk_amount": max_risk_amount,
    }


def calculate_bsjp_plan_from_df(df, ticker_symbol: str) -> dict | None:
    """Hitung BSJP (Buy Saham Jangka Pendek) trading plan: 4 rule screening,
    entry/SL/TP dengan metode khusus BSJP (stop loss lebih lebar karena
    volatilitas BSJP biasanya lebih tinggi).

    Returns None kalau data tidak cukup (< 20 baris).
    """
    if df.empty or len(df) < 20:
        return None

    current_price = float(df["Close"].iloc[-1])
    prev_price = float(df["Close"].iloc[-2])
    current_volume = float(df["Volume"].iloc[-1])
    prev_volume = float(df["Volume"].iloc[-2])
    current_value = current_price * current_volume
    atr = calculate_atr(df, period=10)

    rule_1 = current_price >= (1.05 * prev_price)
    rule_2 = current_price >= df["Close"].rolling(5).mean().iloc[-1]
    rule_3 = current_volume >= (1.2 * prev_volume)
    rule_4 = current_value >= 5_000_000_000

    rules_passed = sum([rule_1, rule_2, rule_3, rule_4])
    daily_change = ((current_price / prev_price) - 1) * 100

    high = df["High"].values
    low = df["Low"].values
    close = df["Close"].values

    pivot = (high[-1] + low[-1] + close[-1]) / 3
    r1 = pivot + (high[-1] - low[-1]) * 0.382
    r2 = pivot + (high[-1] - low[-1]) * 0.618
    s1 = pivot - (high[-1] - low[-1]) * 0.382
    s2 = pivot - (high[-1] - low[-1]) * 0.618

    atr_stop = current_price - (2.5 * atr)
    support_stop = s2 if s2 > 0 else current_price * 0.9
    pct_stop = current_price * 0.9

    stop_loss = max(atr_stop, support_stop, pct_stop)
    max_stop = current_price * 0.85
    if stop_loss < max_stop:
        stop_loss = max_stop

    risk_per_share = current_price - stop_loss
    risk_pct = (risk_per_share / current_price) * 100

    tp1 = current_price + (risk_per_share * 1.2)
    tp2 = current_price + (risk_per_share * 2.0)
    tp3 = current_price + (risk_per_share * 3.0)

    if tp1 > r1 and r1 > current_price:
        tp1 = r1
    if tp2 > r2 and r2 > tp1:
        tp2 = r2

    account_size = 100_000_000
    risk_per_trade_pct = 3.0
    max_risk_amount = account_size * (risk_per_trade_pct / 100)

    avg_value = (close[-20:] * df["Volume"].values[-20:]).mean()
    liquidity_adj = 1.0 if avg_value >= 10_000_000_000 else 0.6

    adjusted_risk = max_risk_amount * liquidity_adj
    position_size = int(adjusted_risk / risk_per_share) if risk_per_share > 0 else 0
    position_value = position_size * current_price
    entry_limit = s1 if s1 < current_price else current_price * 0.97

    confidence = rules_passed * 20
    vol_ma5 = df["Volume"].rolling(5).mean().iloc[-1]
    vol_spike = current_volume / vol_ma5 if vol_ma5 > 0 else 1
    if vol_spike > 1.5:
        confidence += 20
    elif vol_spike > 1.2:
        confidence += 10

    return {
        "ticker_symbol": ticker_symbol,
        "current_price": current_price,
        "daily_change_pct": daily_change,
        "current_volume": current_volume,
        "prev_volume": prev_volume,
        "current_value": current_value,
        "rules": {"rule_1": rule_1, "rule_2": rule_2, "rule_3": rule_3, "rule_4": rule_4},
        "rules_passed": rules_passed,
        "entry_aggressive": current_price,
        "entry_conservative": entry_limit,
        "r1": r1, "r2": r2,
        "stop_loss": stop_loss,
        "risk_per_share": risk_per_share,
        "risk_pct": risk_pct,
        "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "risk_per_trade_pct": risk_per_trade_pct,
        "adjusted_risk": adjusted_risk,
        "position_size": position_size,
        "position_value": position_value,
        "confidence": min(confidence, 100),
    }
