# =========================
# WYCKOFF PHASE (HEURISTIK)
# =========================
# Deteksi fase pasar gaya Wyckoff dari OHLCV: Accumulation, Markup,
# Distribution, Markdown, Ranging. MURNI pandas (tanpa network) -> bisa
# diuji langsung.
#
# JUJUR SOAL BATASAN: ini HEURISTIK sederhana berbasis kemiringan moving
# average + posisi harga, BUKAN analisis Wyckoff manual yang sesungguhnya
# (yang menilai volume, spread, dan event spesifik seperti spring/upthrust
# secara diskresioner). Anggap label ini sebagai perkiraan struktur, bukan
# kebenaran pasti.

import pandas as pd


def detect_phases(df: pd.DataFrame, ma_window: int = 30, slope_span: int = 5,
                  flat_threshold: float = 0.0018, min_segment: int = 6) -> list[dict]:
    """Segmentasi histori harga jadi fase Wyckoff (perkiraan).

    Logika: hitung MA, lalu kemiringannya (perubahan MA selama `slope_span`
    hari, dinormalisasi terhadap harga). Tren naik -> Markup; tren turun ->
    Markdown; datar -> Accumulation (kalau sebelumnya turun) / Distribution
    (kalau sebelumnya naik) / Ranging. Segmen pendek digabung ke tetangga.

    Return list segmen: [{start, end, phase}] dengan tanggal ISO.
    """
    if df is None or len(df) < ma_window + slope_span + 2:
        return []

    close = df["Close"].astype(float)
    ma = close.rolling(ma_window).mean()
    slope = ma.diff(slope_span) / ma  # kemiringan relatif

    labels = []
    prev_trend = "flat"
    for i in range(len(df)):
        s = slope.iloc[i]
        if pd.isna(s):
            labels.append(None)
            continue
        if s > flat_threshold:
            lab, prev_trend = "Markup", "up"
        elif s < -flat_threshold:
            lab, prev_trend = "Markdown", "down"
        else:
            if prev_trend == "up":
                lab = "Distribution"
            elif prev_trend == "down":
                lab = "Accumulation"
            else:
                lab = "Ranging"
        labels.append(lab)

    # Bentuk segmen kontigu
    segs = []
    start = None
    for i, lab in enumerate(labels):
        if lab is None:
            continue
        if start is None:
            start, cur = i, lab
        elif lab != cur:
            segs.append([start, i - 1, cur])
            start, cur = i, lab
    if start is not None:
        segs.append([start, len(labels) - 1, cur])

    # Gabung segmen terlalu pendek ke tetangga sebelumnya
    merged = []
    for seg in segs:
        length = seg[1] - seg[0] + 1
        if merged and length < min_segment:
            merged[-1][1] = seg[1]  # perpanjang segmen sebelumnya
        else:
            merged.append(seg)

    idx = df.index
    out = []
    for s, e, phase in merged:
        out.append({
            "start": idx[s].strftime("%Y-%m-%d"),
            "end": idx[e].strftime("%Y-%m-%d"),
            "phase": phase,
            "bars": e - s + 1,
        })
    return out


def current_phase(df: pd.DataFrame) -> str | None:
    """Fase terkini (segmen terakhir)."""
    segs = detect_phases(df)
    return segs[-1]["phase"] if segs else None
