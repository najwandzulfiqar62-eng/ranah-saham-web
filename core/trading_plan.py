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
    harga saat ini, ATR, dan level support/resistance."""
    entry_normal = current_price
    entry_pullback = sr["S1"] if sr["S1"] < current_price else current_price * 0.98
    entry_deep = sr["S2"] if sr["S2"] < current_price else current_price * 0.96
    breakout_level = sr["R1"] + (atr * 0.2)
    entry_breakout = breakout_level if breakout_level > current_price else current_price * 1.02

    return {
        "normal": entry_normal,
        "pullback": entry_pullback,
        "deep": entry_deep,
        "breakout": entry_breakout,
    }


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
        "pullback": {"name": "PULLBACK (S1)", "display_name": "📉 PULLBACK (S1)"},
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

    return {
        "created_date": created_date_str,
        "price_at_create": round(current_price, 0),
        "scenarios": scenarios,
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
