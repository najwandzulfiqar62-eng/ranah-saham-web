# =========================
# VOLUME PATTERNS
# =========================
# FITUR BARU. /volumespike, /adline -- PENGGANTI NAMA untuk command-
# command yang awalnya diminta dengan nama institusional (BANDARMOLOGI,
# SMARTMONEY, BIGMONEY, UNUSUAL, HOTMONEY, ACCUMULATION, DISTRIBUTION).
#
# KEPUTUSAN PENAMAAN ULANG (dicatat untuk konteks, bukan keputusan
# diam-diam): nama-nama institusional itu menyiratkan deteksi data
# transaksi bandar/institusi SUNGGUHAN, padahal yang BENAR-BENAR bisa
# dibangun dari data candle+volume publik cuma PROXY price-action --
# sama seperti disclaimer di core/smc.py soal SMC. Setelah dibedah,
# 6 dari 7 command itu cuma 2 konsep teknis BERBEDA (bukan 6):
# 1. BANDARMOLOGI/BIGMONEY/UNUSUAL/HOTMONEY -- semuanya soal "volume
#    jauh lebih tinggi dari rata-rata historisnya", beda cuma di
#    threshold sensitivitas -> digabung jadi /volumespike (satu fungsi,
#    threshold disesuaikan ke yang paling umum dipakai di riset: >2
#    standar deviasi atau >1.5-2x rata-rata 20 hari).
# 2. ACCUMULATION/DISTRIBUTION -- bukan dua hal terpisah, tapi DUA UJUNG
#    dari SATU SPEKTRUM yang sudah punya nama resmi & formula baku
#    sejak lama: Chaikin Accumulation/Distribution Line (CLV x Volume,
#    dikumulatifkan) -> /adline.
# SMARTMONEY (candle besar/displacement) DI-SKIP TOTAL karena konsepnya
# pada dasarnya sama dengan Order Block yang SUDAH ADA di core/smc.py
# (/orderblock) -- membangunnya lagi sebagai command terpisah cuma
# menduplikasi fitur yang sudah ada dengan nama berbeda, bukan
# menambah nilai baru.
# FOREIGN sudah diputuskan SKIP TOTAL sejak awal project (data asing
# tidak ada sumber gratis resmi dari IDX).

import pandas as pd


def detect_volume_spikes(df: pd.DataFrame, lookback_days: int = 10, threshold_multiplier: float = 2.0) -> dict:
    """Deteksi candle dengan volume jauh di atas rata-rata 20 hari,
    dalam lookback_days terakhir.

    Threshold 2.0x dipilih sebagai titik tengah dari rentang yang umum
    dipakai di riset (1.5x untuk breakout valid, hingga RelVol>=3 untuk
    'unusual volume' yang lebih ekstrem) -- bukan threshold yang sudah
    dipakai di tempat lain di codebase ini (yang bervariasi 1.2x-2.0x
    tergantung konteks masing-masing fitur), karena fungsi ini punya
    tujuan berbeda: melaporkan HISTORI spike, bukan kondisi screening
    pass/fail untuk satu candle terakhir saja.

    Returns dict: {'spikes': list of dict (tanggal, volume, vol_ratio,
    price_change_pct -- arah harga saat spike terjadi), 'avg_volume_20'}
    """
    if len(df) < 20:
        return {"spikes": [], "avg_volume_20": None}

    avg_volume_20 = df["Volume"].rolling(20).mean()
    vol_ratio = df["Volume"] / avg_volume_20.replace(0, pd.NA)

    recent = df.iloc[-lookback_days:]
    recent_ratio = vol_ratio.iloc[-lookback_days:]

    spikes = []
    for i in range(len(recent)):
        ratio = recent_ratio.iloc[i]
        if pd.isna(ratio) or ratio < threshold_multiplier:
            continue

        idx = recent.index[i]
        close = float(recent["Close"].iloc[i])
        open_ = float(recent["Open"].iloc[i])
        price_change_pct = ((close / open_) - 1) * 100 if open_ > 0 else 0

        spikes.append({
            "date": idx,
            "volume": float(recent["Volume"].iloc[i]),
            "vol_ratio": round(float(ratio), 2),
            "price_change_pct": round(price_change_pct, 2),
            "arah": "🟢 Volume naik + harga naik (minat beli)" if price_change_pct > 0
                    else "🔴 Volume naik + harga turun (minat jual)" if price_change_pct < 0
                    else "⚪ Volume naik, harga flat",
        })

    # Urut dari paling baru
    spikes.sort(key=lambda x: x["date"], reverse=True)

    return {
        "spikes": spikes,
        "avg_volume_20": round(float(avg_volume_20.iloc[-1]), 0) if not pd.isna(avg_volume_20.iloc[-1]) else None,
    }


def calculate_ad_line(df: pd.DataFrame, lookback_days: int = 20) -> dict | None:
    """Chaikin Accumulation/Distribution Line. Formula baku (dikonfirmasi
    dari riset, konsisten di semua sumber -- MarketVolume, LiteFinance,
    investment dictionary, dll):

    CLV (Close Location Value) = [(Close-Low) - (High-Close)] / (High-Low)
    Range CLV: -1 (close di low candle, tekanan jual) hingga +1 (close
    di high candle, tekanan beli).
    A/D = A/D_prev + (Volume x CLV), dikumulatifkan dari awal data.

    Returns None kalau data tidak cukup. Returns dict berisi nilai A/D
    line saat ini, trend (naik/turun dalam lookback_days terakhir), dan
    apakah ada DIVERGENSI dengan harga (harga naik tapi A/D turun =
    sinyal distribusi tersembunyi, atau sebaliknya -- ini penggunaan
    KLASIK indikator ini, bukan interpretasi baru)."""
    if len(df) < lookback_days + 5:
        return None

    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    volume = df["Volume"]

    range_hl = (high - low).replace(0, pd.NA)  # hindari div-by-zero kalau high==low (limit/suspend)
    clv = ((close - low) - (high - close)) / range_hl
    clv = clv.fillna(0)  # candle dengan high==low: CLV dianggap netral (0), bukan crash

    money_flow_volume = volume * clv
    ad_line = money_flow_volume.cumsum()

    current_ad = float(ad_line.iloc[-1])
    ad_n_periods_ago = float(ad_line.iloc[-(lookback_days + 1)])
    ad_trend_pct = ((current_ad / ad_n_periods_ago) - 1) * 100 if ad_n_periods_ago != 0 else 0

    price_now = float(close.iloc[-1])
    price_n_periods_ago = float(close.iloc[-(lookback_days + 1)])
    price_trend_pct = ((price_now / price_n_periods_ago) - 1) * 100

    ad_naik = current_ad > ad_n_periods_ago
    price_naik = price_now > price_n_periods_ago

    if price_naik and ad_naik:
        sinyal = "✅ KONFIRMASI BULLISH (harga naik + A/D naik, sejalan)"
        label = "Akumulasi"
    elif not price_naik and not ad_naik:
        sinyal = "✅ KONFIRMASI BEARISH (harga turun + A/D turun, sejalan)"
        label = "Distribusi"
    elif price_naik and not ad_naik:
        sinyal = "⚠️ DIVERGENSI BEARISH (harga naik tapi A/D turun -- waspada distribusi tersembunyi)"
        label = "Distribusi Tersembunyi"
    else:
        sinyal = "⚠️ DIVERGENSI BULLISH (harga turun tapi A/D naik -- mungkin ada akumulasi tersembunyi)"
        label = "Akumulasi Tersembunyi"

    last_clv = float(clv.iloc[-1])
    if last_clv > 0.5:
        clv_label = "tekanan beli kuat (close dekat high)"
    elif last_clv > 0:
        clv_label = "tekanan beli ringan"
    elif last_clv == 0:
        clv_label = "netral (close di tengah range, atau candle limit/suspend)"
    elif last_clv > -0.5:
        clv_label = "tekanan jual ringan"
    else:
        clv_label = "tekanan jual kuat (close dekat low)"

    return {
        "current_ad": round(current_ad, 0),
        "ad_trend_pct": round(ad_trend_pct, 2),
        "price_trend_pct": round(price_trend_pct, 2),
        "last_clv": round(last_clv, 2),
        "clv_label": clv_label,
        "sinyal": sinyal,
        "label": label,
        "lookback_days": lookback_days,
    }
