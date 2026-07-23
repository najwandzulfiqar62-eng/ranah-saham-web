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


MAX_POSISI_PCT = 40.0  # batas konsentrasi 1 saham thd modal (lihat build_portfolio)


def _rp(x: float) -> str:
    """Format rupiah gaya Indonesia (titik sbg pemisah ribuan). Dipakai di
    pesan 'dilewati' yang tampil apa adanya di UI -- f"{x:,.0f}" bawaan Python
    memakai KOMA (gaya Inggris) sehingga tampil tidak konsisten dgn seluruh
    angka lain di antarmuka yang sudah berformat Indonesia."""
    return f"Rp{x:,.0f}".replace(",", ".")


def build_portfolio(modal: float, candidates: list[dict], risk_pct: float = 1.0,
                    max_pos_pct: float = MAX_POSISI_PCT) -> dict | None:
    """Racik portofolio: dari MODAL + daftar saham pilihan USER, hitung berapa
    LOT tiap saham memakai position sizing BERBASIS RISIKO (keputusan user
    2026-07-23), lalu batasi oleh modal yang benar-benar tersedia.

    Tiap posisi diukur supaya kalau stop loss-nya kena, kerugiannya = risk_pct
    dari modal -- jadi saham ber-SL sempit dapat porsi lebih besar, yang lebar
    lebih kecil. Ini memakai calculate_position_size() yang SAMA dengan
    kalkulator risiko yang sudah ada (satu sumber kebenaran, termasuk
    pembulatan KE BAWAH ke kelipatan lot IDX -- lihat catatan LOT_SIZE di
    atas file ini).

    TIGA BATASAN yang WAJIB dipegang bersamaan (ini inti kebenaran fungsi ini):
      1. Batas RISIKO  -- dari calculate_position_size (risk_pct per posisi).
      2. Batas MODAL   -- position sizing berbasis risiko TIDAK dengan
         sendirinya menghormati modal: beberapa saham ber-SL sangat sempit
         bisa menghasilkan total nilai beli JAUH melebihi uang yang ada.
         Karena itu alokasi dilakukan BERURUTAN terhadap sisa modal, dan lot
         dipangkas kalau uangnya kurang (ditandai 'dipangkas_modal': True).
      3. Batas KONSENTRASI (max_pos_pct) -- risk_pct saja TIDAK cukup: saham
         ber-SL sangat rapat (mis. support cuma 0,6% di bawah harga) akan
         diberi posisi raksasa yang menyedot hampir seluruh modal ke SATU
         saham (terukur nyata: BBCA 15 lot = 97% modal). Risiko "1%" itu
         hanya berlaku kalau SL benar-benar tereksekusi di harganya; begitu
         harga LOMPAT (gap) melewati SL -- justru yang paling mungkin pada
         stop serapat itu -- kerugian nyatanya jauh melebihi 1%. Karena itu
         tiap posisi dibatasi maksimal max_pos_pct dari modal (default 40%)
         dan ditandai 'dibatasi_konsentrasi': True bila terkena batas ini.
    Saham yang tidak kebagian (sisa modal tak cukup 1 lot, atau SL tidak wajar)
    TIDAK didiamkan -- dikembalikan di 'dilewati' beserta ALASANnya, supaya
    user tahu kenapa sahamnya tidak muncul (bukan hilang diam-diam).

    candidates: [{'kode', 'entry', 'stop_loss', + field bebas yang diteruskan}]
    -- urutan input DIHORMATI (saham pertama dilayani lebih dulu saat modal
    menipis). MURNI aritmatika, tanpa I/O -- caller (endpoint) yang mengambil
    harga & level SL-nya.

    Returns None kalau modal/risk_pct tidak valid."""
    if modal <= 0 or risk_pct <= 0 or not candidates:
        return None

    posisi: list[dict] = []
    dilewati: list[dict] = []
    sisa = float(modal)

    for c in candidates:
        kode = c.get("kode")
        entry = c.get("entry") or 0
        sl = c.get("stop_loss") or 0

        if entry <= 0:
            dilewati.append({"kode": kode, "alasan": "Harga tidak tersedia."})
            continue
        # SL di atas/sama dengan harga = bukan stop loss yang wajar untuk posisi
        # beli; menghitungnya tetap akan menghasilkan risiko negatif/nol.
        if sl <= 0 or sl >= entry:
            dilewati.append({
                "kode": kode,
                "alasan": "Level stop loss tidak wajar (support di atas harga sekarang), tidak bisa dihitung.",
            })
            continue

        harga_per_lot = entry * LOT_SIZE
        lot_maks_modal = math.floor(sisa / harga_per_lot)
        if lot_maks_modal < 1:
            dilewati.append({
                "kode": kode,
                "alasan": (f"Sisa modal {_rp(sisa)} tidak cukup untuk 1 lot "
                           f"(butuh {_rp(harga_per_lot)})."),
            })
            continue

        sizing = calculate_position_size(modal, risk_pct, entry, sl)
        lot_risiko = sizing["n_lots"] if sizing else 0
        if lot_risiko < 1:
            dilewati.append({
                "kode": kode,
                "alasan": (f"Dengan risiko {risk_pct}% per posisi, jatah untuk saham ini "
                           f"belum cukup 1 lot. Perbesar modal atau naikkan risiko per posisi."),
            })
            continue

        # Batas konsentrasi: berapa lot yang masih di bawah max_pos_pct modal.
        lot_maks_konsentrasi = math.floor((modal * max_pos_pct / 100) / harga_per_lot)
        lot = min(lot_risiko, lot_maks_modal, max(lot_maks_konsentrasi, 1) if lot_maks_konsentrasi >= 1 else 0)
        if lot < 1:
            dilewati.append({
                "kode": kode,
                "alasan": (f"1 lot saham ini ({_rp(harga_per_lot)}) sudah melebihi batas "
                           f"{max_pos_pct:.0f}% modal per saham."),
            })
            continue
        dipangkas = lot < lot_risiko and lot == lot_maks_modal
        dibatasi_konsentrasi = lot == lot_maks_konsentrasi < lot_risiko
        nilai = lot * harga_per_lot
        risiko_rp = lot * LOT_SIZE * (entry - sl)
        sisa -= nilai

        posisi.append({
            **{k: v for k, v in c.items() if k not in ("entry", "stop_loss")},
            "kode": kode,
            "harga": round(entry, 2),
            "stop_loss": round(sl, 2),
            "lot": lot,
            "lembar": lot * LOT_SIZE,
            "nilai": round(nilai, 0),
            "porsi_pct": 0.0,           # diisi setelah total diketahui
            "risiko_rp": round(risiko_rp, 0),
            "risiko_pct_modal": round(risiko_rp / modal * 100, 2),
            "sl_pct": round((entry - sl) / entry * 100, 2),
            "dipangkas_modal": dipangkas,
            "dibatasi_konsentrasi": dibatasi_konsentrasi,
        })

    if not posisi:
        return {
            "modal": round(modal, 0), "risk_pct": risk_pct,
            "posisi": [], "dilewati": dilewati,
            "total_nilai": 0.0, "sisa_modal": round(modal, 0), "terpakai_pct": 0.0,
            "total_risiko_rp": 0.0, "total_risiko_pct": 0.0,
        }

    total_nilai = sum(p["nilai"] for p in posisi)
    total_risiko = sum(p["risiko_rp"] for p in posisi)
    for p in posisi:
        p["porsi_pct"] = round(p["nilai"] / total_nilai * 100, 1)

    return {
        "modal": round(modal, 0),
        "risk_pct": risk_pct,
        "max_pos_pct": max_pos_pct,
        "posisi": posisi,
        "dilewati": dilewati,
        "total_nilai": round(total_nilai, 0),
        "sisa_modal": round(modal - total_nilai, 0),
        "terpakai_pct": round(total_nilai / modal * 100, 1),
        # "kalau SEMUA posisi kena SL" -- skenario terburuk yang realistis,
        # sengaja ditampilkan supaya user melihat total taruhannya sekaligus,
        # bukan cuma per posisi yang kelihatan kecil-kecil.
        "total_risiko_rp": round(total_risiko, 0),
        "total_risiko_pct": round(total_risiko / modal * 100, 2),
    }
