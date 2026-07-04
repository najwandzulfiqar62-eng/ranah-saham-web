# =========================
# RISK MANAGEMENT
# =========================
# FITUR BARU. /rr, /target, /cutloss, /positionsize. Modul ini murni
# kalkulasi matematis (sebagian dari data historis via indikator yang
# sudah ada, sebagian dari input user langsung) -- TIDAK ada
# rekomendasi "harus beli/jual", hanya menyediakan angka untuk user
# buat keputusan sendiri (konsisten dengan <legal_and_financial_advice>:
# Claude bukan financial advisor).
#
# CATATAN KRUSIAL -- SATUAN LOT IDX (dikonfirmasi via riset web, bukan
# diasumsikan): Bursa Efek Indonesia mewajibkan transaksi saham dalam
# satuan LOT, BUKAN per lembar. 1 LOT = 100 LEMBAR SAHAM (berlaku sejak
# 2014, sebelumnya 500 lembar/lot). calculate_position_size() WAJIB
# membulatkan hasil ke kelipatan 100 lembar (1 lot) -- bukan ke lembar
# individual seperti formula umum yang ditulis untuk pasar AS/forex.
# Tanpa penyesuaian ini, hasil position sizing akan menyarankan jumlah
# lembar yang TIDAK BISA DIEKSEKUSI user di aplikasi sekuritasnya.
#
# CATATAN soal pembulatan: SELALU membulatkan KE BAWAH (floor), tidak
# pernah ke atas atau round-to-nearest. Membulatkan ke atas akan
# membuat risiko sesungguhnya MELEBIHI persentase yang diminta user --
# ini bukan detail kosmetik, ini langsung berkaitan dengan keakuratan
# jumlah uang yang dipertaruhkan (dikonfirmasi dari riset: "Always
# round down to the nearest whole unit — rounding up puts you over
# your risk budget").

import math

from core.indicators import calculate_atr, calculate_support_resistance_deep

LOT_SIZE = 100  # 1 lot IDX = 100 lembar saham


def calculate_risk_reward(entry: float, stop_loss: float, take_profit: float) -> dict | None:
    """Hitung rasio risk/reward dari 3 harga yang user berikan.

    Returns None kalau input tidak valid (misal entry == stop_loss,
    yang akan menyebabkan pembagian oleh nol)."""
    risk_per_share = abs(entry - stop_loss)
    reward_per_share = abs(take_profit - entry)

    if risk_per_share == 0:
        return None

    rr_ratio = reward_per_share / risk_per_share
    is_long = take_profit > entry  # asumsi: TP di atas entry = posisi long, di bawah = short

    return {
        "risk_per_share": round(risk_per_share, 2),
        "reward_per_share": round(reward_per_share, 2),
        "rr_ratio": round(rr_ratio, 2),
        "is_long": is_long,
        "risk_pct": round((risk_per_share / entry) * 100, 2),
        "reward_pct": round((reward_per_share / entry) * 100, 2),
    }


def calculate_target_levels(df) -> dict:
    """Target harga berbasis Fibonacci + Support/Resistance (memakai
    calculate_support_resistance_deep yang sudah ada & teruji di
    core/indicators.py -- TIDAK menulis ulang logic pivot/fibonacci,
    cukup membungkus & memformat ulang untuk konteks /target)."""
    sr = calculate_support_resistance_deep(df)
    current_price = float(df["Close"].iloc[-1])

    return {
        "current_price": round(current_price, 2),
        "pivot": sr["Pivot"],
        "resistance_levels": [sr["R1"], sr["R2"], sr["R3"]],
        "support_levels": [sr["S1"], sr["S2"], sr["S3"]],
        "high_20d": sr["High20"],
        "high_50d": sr["High50"],
    }


def calculate_cutloss_levels(df) -> dict:
    """Area cut loss ideal berbasis ATR (volatilitas riil saham, BUKAN
    persentase arbitrer/sama untuk semua saham). Memberikan 2 opsi:
    konservatif (1.5x ATR) dan agresif (2.5x ATR) -- semakin lebar
    stop, semakin jarang ter-trigger oleh noise tapi makin besar risk
    per share."""
    atr = calculate_atr(df)
    current_price = float(df["Close"].iloc[-1])

    conservative_distance = atr * 1.5
    aggressive_distance = atr * 2.5

    return {
        "current_price": round(current_price, 2),
        "atr": round(atr, 2),
        "atr_pct": round((atr / current_price) * 100, 2),
        "cutloss_conservative": round(current_price - conservative_distance, 2),
        "cutloss_aggressive": round(current_price - aggressive_distance, 2),
        "conservative_distance_pct": round((conservative_distance / current_price) * 100, 2),
        "aggressive_distance_pct": round((aggressive_distance / current_price) * 100, 2),
    }


def calculate_position_size(modal: float, risk_pct: float, entry: float, stop_loss: float) -> dict | None:
    """Hitung jumlah LOT yang bisa dibeli supaya risiko maksimal sesuai
    risk_pct dari modal, kalau stop_loss benar2 ter-trigger.

    Formula standar (dikonfirmasi dari riset multi-sumber):
    Position Size = (Modal x Risk%) / (Entry - Stop Loss)
    DIMODIFIKASI untuk IDX: hasil lembar dibulatkan KE BAWAH ke
    kelipatan LOT_SIZE (100 lembar), karena BEI mewajibkan transaksi
    dalam satuan lot.

    Returns None kalau input tidak valid (entry == stop_loss, atau
    modal/risk_pct <= 0)."""
    if entry == stop_loss or modal <= 0 or risk_pct <= 0:
        return None

    risk_amount = modal * (risk_pct / 100)
    risk_per_share = abs(entry - stop_loss)

    raw_shares = risk_amount / risk_per_share

    # PEMBULATAN KE BAWAH ke kelipatan LOT_SIZE -- lihat catatan krusial
    # di atas file ini. math.floor dipakai dua kali: sekali untuk lot
    # (raw_shares // LOT_SIZE), bukan untuk lembar individual.
    n_lots = math.floor(raw_shares / LOT_SIZE)
    actual_shares = n_lots * LOT_SIZE
    actual_value = actual_shares * entry
    actual_risk_amount = actual_shares * risk_per_share

    if n_lots == 0:
        return {
            "n_lots": 0, "actual_shares": 0, "actual_value": 0.0,
            "actual_risk_amount": 0.0, "actual_risk_pct": 0.0,
            "warning": (
                f"Modal/risk% terlalu kecil untuk beli minimal 1 lot ({LOT_SIZE} lembar) "
                f"saham ini dengan jarak stop-loss tersebut. Perbesar modal, naikkan risk%, "
                f"atau cari entry/stop-loss yang lebih rapat."
            ),
        }

    return {
        "n_lots": n_lots,
        "actual_shares": actual_shares,
        "actual_value": round(actual_value, 0),
        "actual_risk_amount": round(actual_risk_amount, 0),
        "actual_risk_pct": round((actual_risk_amount / modal) * 100, 3),
        "warning": None,
    }


def calculate_average_down(avg_price: float, lots_held: int, current_price: float, add_lots: int = 0) -> dict | None:
    """Hitung harga rata-rata baru & P/L kalau menambah average down di
    harga sekarang -- murni aritmatika tertimbang lot (bukan lembar,
    lihat catatan LOT_SIZE di atas). SAMA seperti kalkulator lain di
    modul ini: TIDAK ada rekomendasi "harus average down atau tidak",
    cuma angka hasilnya -- verdict fundamental (undervalued/overvalued)
    ditambahkan TERPISAH oleh caller (endpoint) sebagai KONTEKS, bukan
    bagian dari fungsi murni ini, supaya fungsi ini tetap testable tanpa
    perlu mock fetch fundamental.

    add_lots=0 valid (dipakai buat sekadar cek P/L posisi sekarang tanpa
    menambah apa-apa) -- new_avg_price akan sama dengan avg_price.

    Returns None kalau input tidak valid (harga <= 0 atau lot yang
    dipegang <= 0 atau add_lots negatif)."""
    if avg_price <= 0 or current_price <= 0 or lots_held <= 0 or add_lots < 0:
        return None

    shares_held = lots_held * LOT_SIZE
    shares_add = add_lots * LOT_SIZE
    total_shares = shares_held + shares_add

    cost_held = avg_price * shares_held
    cost_add = current_price * shares_add
    new_avg_price = (cost_held + cost_add) / total_shares

    return {
        "current_price": round(current_price, 2),
        "old_avg_price": round(avg_price, 2),
        "new_avg_price": round(new_avg_price, 2),
        "avg_price_change_pct": round((new_avg_price / avg_price - 1) * 100, 2),
        "old_lots": lots_held,
        "add_lots": add_lots,
        "total_lots": lots_held + add_lots,
        "additional_capital": round(cost_add, 0),
        "pl_before_pct": round((current_price / avg_price - 1) * 100, 2),
        "pl_after_pct": round((current_price / new_avg_price - 1) * 100, 2),
    }
