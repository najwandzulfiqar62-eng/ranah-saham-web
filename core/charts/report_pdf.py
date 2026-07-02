# =========================
# LAPORAN PREMIUM - RENDERER PDF
# =========================
# Merender struktur report_data (dari core/report.py) jadi PDF analis
# yang rapi & berlogo. MURNI rendering -> bisa dites tanpa network
# (cukup beri report_data sintetis). Memakai reportlab Platypus.
#
# Bagian yang opsional (konteks IHSG, berita, sektor) di-skip otomatis
# kalau datanya None -> laporan tetap valid untuk saham tanpa konteks.

import os
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image,
    HRFlowable, KeepTogether,
)

# ---- Palet brand ----
NAVY = colors.HexColor("#16243C")
NAVY_SOFT = colors.HexColor("#22304A")
ACCENT = colors.HexColor("#C8A24B")      # emas tenang -> kesan "mahal"
GREEN = colors.HexColor("#1E7A46")
GREEN_BG = colors.HexColor("#E7F3EC")
RED = colors.HexColor("#A4262C")
RED_BG = colors.HexColor("#F7E9EA")
GREY = colors.HexColor("#5B6470")
LIGHT = colors.HexColor("#F4F5F7")

_DEFAULT_LOGO = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                             "assets", "logo_ranah_saham.png")


def _styles():
    ss = getSampleStyleSheet()
    s = {}
    s["title"] = ParagraphStyle("title", parent=ss["Title"], fontName="Helvetica-Bold",
                                fontSize=22, textColor=colors.white, leading=26, alignment=TA_LEFT)
    s["subtitle"] = ParagraphStyle("subtitle", fontName="Helvetica", fontSize=10.5,
                                   textColor=ACCENT, leading=14, alignment=TA_LEFT)
    s["h2"] = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=13.5, textColor=NAVY,
                             spaceBefore=14, spaceAfter=6, leading=16)
    s["h3"] = ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=11, textColor=NAVY_SOFT,
                             spaceBefore=8, spaceAfter=3, leading=14)
    s["body"] = ParagraphStyle("body", fontName="Helvetica", fontSize=9.7, textColor=colors.HexColor("#1F2733"),
                               leading=14.5, alignment=TA_JUSTIFY, spaceAfter=4)
    s["small"] = ParagraphStyle("small", fontName="Helvetica", fontSize=8, textColor=GREY, leading=11)
    s["cell"] = ParagraphStyle("cell", fontName="Helvetica", fontSize=8.8, textColor=colors.HexColor("#1F2733"), leading=12)
    s["cellb"] = ParagraphStyle("cellb", fontName="Helvetica-Bold", fontSize=8.8, textColor=NAVY, leading=12)
    s["bull"] = ParagraphStyle("bull", fontName="Helvetica", fontSize=8.8, textColor=colors.HexColor("#16341F"), leading=12.5)
    s["bear"] = ParagraphStyle("bear", fontName="Helvetica", fontSize=8.8, textColor=colors.HexColor("#3A1416"), leading=12.5)
    return s


def _header(report_data, S, logo_path):
    """Banner header navy + logo + judul + skor besar."""
    title_cell = [
        Paragraph("LAPORAN ANALISIS SAHAM", S["title"]),
        Paragraph(
            f"{report_data['ticker']} &nbsp;•&nbsp; {report_data.get('nama','')} &nbsp;•&nbsp; "
            f"{datetime.now().strftime('%d %B %Y')}", S["subtitle"]),
    ]
    score = report_data.get("score")
    rating = report_data.get("rating", "")
    score_style = ParagraphStyle("score", fontName="Helvetica-Bold", fontSize=26,
                                 textColor=colors.white, alignment=TA_CENTER, leading=28)
    rating_style = ParagraphStyle("ratingS", fontName="Helvetica", fontSize=8.5,
                                  textColor=ACCENT, alignment=TA_CENTER, leading=11)
    score_cell = [Paragraph(f"{score}<font size=11>/100</font>", score_style),
                  Paragraph(f"{rating}", rating_style)]

    logo = ""
    if logo_path and os.path.exists(logo_path):
        try:
            logo = Image(logo_path, width=21 * mm, height=21 * mm)
        except Exception:
            logo = ""

    inner = Table([[logo, title_cell, score_cell]], colWidths=[30 * mm, 105 * mm, 35 * mm])
    inner.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("BOX", (2, 0), (2, 0), 0, NAVY), ("BACKGROUND", (2, 0), (2, 0), NAVY_SOFT),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
    ]))
    return inner


def _section(title, S):
    return [Spacer(1, 4), Paragraph(title, S["h2"]),
            HRFlowable(width="100%", thickness=1.2, color=ACCENT, spaceAfter=6)]


def _kv_table(rows, S, col_widths):
    data = [[Paragraph(str(k), S["cellb"]), Paragraph(str(v), S["cell"])] for k, v in rows]
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDE1E7")),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHT]),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


def _status_color(status):
    up = status.upper()
    if any(w in up for w in ("BULLISH", "GOLDEN", "OVERSOLD", "SPIKE")):
        return GREEN, GREEN_BG
    if any(w in up for w in ("BEARISH", "OVERBOUGHT", "DEATH")):
        return RED, RED_BG
    return GREY, LIGHT


def _indicator_table(rows, S):
    data = [[Paragraph("Indikator", S["cellb"]), Paragraph("Status", S["cellb"]),
             Paragraph("Detail", S["cellb"])]]
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDE1E7")),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
    ]
    for i, (nama, status, detail) in enumerate(rows, start=1):
        fg, bg = _status_color(status)
        badge = ParagraphStyle(f"b{i}", fontName="Helvetica-Bold", fontSize=8.5, textColor=fg, leading=11)
        data.append([Paragraph(nama, S["cell"]), Paragraph(status, badge), Paragraph(str(detail), S["cell"])])
        style.append(("BACKGROUND", (1, i), (1, i), bg))
    for r in range(1, len(rows) + 1):
        style.append(("TEXTCOLOR", (0, 0), (-1, 0), colors.white))
    t = Table(data, colWidths=[48 * mm, 32 * mm, 90 * mm])
    t.setStyle(TableStyle(style))
    return t


def _bull_bear_panel(bull, bear, S):
    bull_items = [Paragraph("▲ ARGUMEN BULLISH", ParagraphStyle("bh", fontName="Helvetica-Bold",
                  fontSize=9.5, textColor=GREEN, leading=13, spaceAfter=4))]
    bull_items += [Paragraph(f"• {p}", S["bull"]) for p in bull]
    bear_items = [Paragraph("▼ ARGUMEN BEARISH", ParagraphStyle("brh", fontName="Helvetica-Bold",
                  fontSize=9.5, textColor=RED, leading=13, spaceAfter=4))]
    bear_items += [Paragraph(f"• {p}", S["bear"]) for p in bear]
    t = Table([[bull_items, bear_items]], colWidths=[85 * mm, 85 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (0, 0), GREEN_BG), ("BACKGROUND", (1, 0), (1, 0), RED_BG),
        ("BOX", (0, 0), (0, 0), 0.6, GREEN), ("BOX", (1, 0), (1, 0), 0.6, RED),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    return t


def _scenario_table(skenario, S):
    if not skenario:
        return None
    data = [[Paragraph("Skenario", S["cellb"]), Paragraph("Kecondongan", S["cellb"]),
             Paragraph("Pemicu", S["cellb"]), Paragraph("Arah/Target", S["cellb"])]]
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY_SOFT), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDE1E7")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
    ]
    for sk in skenario:
        fg, _ = _status_color(sk["nama"])
        nm = ParagraphStyle("sk", fontName="Helvetica-Bold", fontSize=8.6, textColor=fg, leading=11)
        data.append([Paragraph(sk["nama"], nm), Paragraph(sk["arah"], S["cell"]),
                     Paragraph(sk["kondisi"], S["cell"]), Paragraph(sk["target"], S["cell"])])
    t = Table(data, colWidths=[26 * mm, 26 * mm, 62 * mm, 56 * mm])
    t.setStyle(TableStyle(style))
    return t


def _chart_image(path, max_width_mm=174):
    """Sisipkan chart PNG, diskala proporsional ke lebar konten. Skip
    diam-diam kalau file tidak ada / gagal dibaca (laporan tetap valid)."""
    if not path or not os.path.exists(path):
        return None
    try:
        from reportlab.lib.utils import ImageReader
        iw, ih = ImageReader(path).getSize()
        w = max_width_mm * mm
        h = w * ih / iw
        return Image(path, width=w, height=h)
    except Exception:
        return None


def _smc_section(smc, S):
    """Bagian Smart Money Concepts: narasi + tabel ringkas + chart tiap
    komponen (BOS/CHoCH, Order Block, FVG, Liquidity Pools)."""
    flow = [Paragraph(smc.get("narasi", ""), S["body"]), Spacer(1, 4)]
    rows = [(
        "Struktur (BOS/CHoCH)",
        f"{smc.get('n_bos', 0)} BOS / {smc.get('n_choch', 0)} CHoCH",
        smc.get("last_struktur") or "—",
    ), (
        "Order Block",
        f"{smc.get('ob_bullish', 0)} bullish / {smc.get('ob_bearish', 0)} bearish",
        "Area minat institusi",
    ), (
        "Fair Value Gap (belum terisi)",
        f"{smc.get('fvg_unfilled', 0)} gap",
        "Potensi magnet harga",
    ), (
        "Liquidity Pools",
        f"{smc.get('liq_high', 0)} high / {smc.get('liq_low', 0)} low",
        f"{smc.get('liq_unswept', 0)} belum tersapu",
    )]
    flow.append(_indicator_table(rows, S))

    # Chart tiap komponen SMC, masing-masing dengan sub-judul.
    charts = smc.get("charts") or {}
    for label, path in charts.items():
        img = _chart_image(path)
        if img is not None:
            flow.append(Spacer(1, 8))
            flow.append(Paragraph(label, S["h3"]))
            flow.append(img)
    return flow


def _rec_badge_block(rec_badge, S):
    """Blok rekomendasi BUY/HOLD/SELL berwarna."""
    if not rec_badge:
        return []
    label = rec_badge.get("label", "HOLD")
    strength = rec_badge.get("strength", "")
    reason = rec_badge.get("reason", "")
    is_buy = label == "BUY"
    is_sell = label == "SELL"
    col_fg = GREEN if is_buy else RED if is_sell else colors.HexColor("#B8860B")
    col_bg = GREEN_BG if is_buy else RED_BG if is_sell else colors.HexColor("#FFF8E1")
    icon = "▲" if is_buy else "▼" if is_sell else "◆"
    lbl_style = ParagraphStyle("rec_lbl", fontName="Helvetica-Bold", fontSize=18,
                               textColor=col_fg, leading=22, alignment=TA_CENTER)
    sub_style = ParagraphStyle("rec_sub", fontName="Helvetica", fontSize=8,
                               textColor=col_fg, leading=10, alignment=TA_CENTER)
    reason_style = ParagraphStyle("rec_reason", fontName="Helvetica", fontSize=9,
                                  textColor=colors.HexColor("#1F2733"), leading=13)
    t = Table(
        [[
            [Paragraph(f"{icon} {label}", lbl_style), Paragraph(strength, sub_style)],
            Paragraph(reason, reason_style),
        ]],
        colWidths=[42 * mm, 128 * mm],
    )
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (0, 0), col_bg),
        ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#FAFAFA")),
        ("BOX", (0, 0), (-1, -1), 1.2, col_fg),
        ("LINEAFTER", (0, 0), (0, 0), 0.6, col_fg),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    return [t, Spacer(1, 4),
            Paragraph("Berdasarkan kondisi teknikal saat ini. Bukan nasihat keuangan — lakukan riset mandiri.",
                      ParagraphStyle("disc", fontName="Helvetica", fontSize=7.5, textColor=GREY, leading=10))]


def _vwap_block(vwap_fv, S):
    """Blok VWAP Fair Value."""
    if not vwap_fv:
        return []
    label = vwap_fv.get("label", "")
    vwap = vwap_fv.get("vwap")
    dev = vwap_fv.get("dev_pct", 0)
    z = vwap_fv.get("z", 0)
    is_disc = "Discount" in label
    is_prem = "Premium" in label
    col = GREEN if is_disc else RED if is_prem else GREY
    rows = [
        ("VWAP (Nilai Wajar)", f"Rp{vwap:,.0f}" if vwap else "–"),
        ("Label", label),
        ("Deviasi vs VWAP", f"{dev:+.2f}%"),
        ("Dislokasi (z-score)", f"{z:+.1f}σ"),
    ]
    t = _kv_table(rows, S, [70 * mm, 100 * mm])
    lbl_s = ParagraphStyle("vlbl", fontName="Helvetica-Bold", fontSize=11, textColor=col, leading=14)
    return [Paragraph(label, lbl_s), Spacer(1, 4), t]


def _fixed_entries_table(fixed_entries, S):
    """Tabel 4 skenario trading plan (entry levels)."""
    if not fixed_entries or not fixed_entries.get("scenarios"):
        return []
    scenarios = fixed_entries["scenarios"]
    price_at_create = fixed_entries.get("price_at_create", 0)

    header_style = ParagraphStyle("feh", fontName="Helvetica-Bold", fontSize=8.5,
                                  textColor=colors.white, leading=11)
    data = [[
        Paragraph("Skenario", header_style),
        Paragraph("Entry", header_style),
        Paragraph("Stop Loss", header_style),
        Paragraph("Risk", header_style),
        Paragraph("TP1", header_style),
        Paragraph("TP2", header_style),
        Paragraph("TP3", header_style),
    ]]
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDE1E7")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    sc_order = ["normal", "pullback", "deep", "breakout"]
    sc_labels = {"normal": "Normal", "pullback": "Pullback (S1)", "deep": "Deep (S2)", "breakout": "Breakout"}
    sc_colors = {"normal": GREY, "pullback": colors.HexColor("#2E6DA4"),
                 "deep": RED, "breakout": GREEN}
    for key in sc_order:
        sc = scenarios.get(key)
        if not sc:
            continue
        col = sc_colors.get(key, GREY)
        nm_s = ParagraphStyle(f"sc{key}", fontName="Helvetica-Bold", fontSize=8.5, textColor=col, leading=11)
        cell_s = ParagraphStyle(f"c{key}", fontName="Helvetica", fontSize=8.5,
                                textColor=colors.HexColor("#1F2733"), leading=11)
        data.append([
            Paragraph(sc_labels.get(key, key), nm_s),
            Paragraph(f"Rp{sc.get('entry', 0):,.0f}", cell_s),
            Paragraph(f"Rp{sc.get('sl', 0):,.0f}", ParagraphStyle(f"sl{key}", parent=cell_s, textColor=RED)),
            Paragraph(f"−{sc.get('risk_pct', 0):.1f}%", ParagraphStyle(f"r{key}", parent=cell_s, textColor=RED)),
            Paragraph(f"Rp{sc.get('tp1', 0):,.0f}\n+{sc.get('tp1_pct', 0):.1f}%",
                      ParagraphStyle(f"t1{key}", parent=cell_s, textColor=GREEN)),
            Paragraph(f"Rp{sc.get('tp2', 0):,.0f}\n+{sc.get('tp2_pct', 0):.1f}%",
                      ParagraphStyle(f"t2{key}", parent=cell_s, textColor=GREEN)),
            Paragraph(f"Rp{sc.get('tp3', 0):,.0f}\n+{sc.get('tp3_pct', 0):.1f}%",
                      ParagraphStyle(f"t3{key}", parent=cell_s, textColor=GREEN)),
        ])

    t = Table(data, colWidths=[34 * mm, 24 * mm, 24 * mm, 14 * mm, 26 * mm, 26 * mm, 26 * mm])
    t.setStyle(TableStyle(style))
    note_s = ParagraphStyle("fenote", fontName="Helvetica", fontSize=7.5, textColor=GREY, leading=10)
    return [
        t,
        Spacer(1, 4),
        Paragraph(
            f"Level dihitung dari harga Rp{price_at_create:,.0f} saat laporan dibuat · "
            "SL = support terdekat − 0.2×ATR · TP berbasis kelipatan risk · Bukan saran investasi.",
            note_s,
        ),
    ]


def generate_report_pdf(report_data: dict, output_path: str, logo_path: str | None = None) -> str:
    """Render report_data -> file PDF di output_path. Return output_path."""
    logo_path = logo_path or _DEFAULT_LOGO
    S = _styles()
    doc = SimpleDocTemplate(output_path, pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=14 * mm, bottomMargin=16 * mm,
                            title=f"Laporan {report_data.get('ticker','')}")
    flow = []

    flow.append(_header(report_data, S, logo_path))
    flow.append(Spacer(1, 10))

    # Rekomendasi BUY/HOLD/SELL badge
    rec_blk = _rec_badge_block(report_data.get("rec_badge"), S)
    if rec_blk:
        flow += _section("Rekomendasi Teknikal", S)
        flow += rec_blk

    # Ringkasan eksekutif
    flow += _section("Ringkasan Eksekutif", S)
    flow.append(Paragraph(report_data.get("ringkasan_eksekutif", ""), S["body"]))

    # Snapshot
    flow += _section("Snapshot Pasar", S)
    flow.append(_kv_table(report_data.get("snapshot", []), S, [60 * mm, 110 * mm]))

    # VWAP Fair Value
    vwap_blk = _vwap_block(report_data.get("vwap_fv"), S)
    if vwap_blk:
        flow += _section("VWAP Fair Value", S)
        flow += vwap_blk

    # Chart utama
    chart = _chart_image(report_data.get("chart_path"))
    if chart is not None:
        flow += _section("Grafik Harga & Indikator", S)
        flow.append(chart)

    # Teknikal
    flow += _section("Analisis Teknikal", S)
    if report_data.get("teknikal_narasi"):
        flow.append(Paragraph(report_data["teknikal_narasi"], S["body"]))
        flow.append(Spacer(1, 4))
    flow.append(_indicator_table(report_data.get("indikator_status", []), S))

    # Bull vs Bear
    flow += _section("Perspektif: Bull vs Bear", S)
    flow.append(_bull_bear_panel(report_data.get("bull_case", []),
                                 report_data.get("bear_case", []), S))
    flow.append(Spacer(1, 6))
    flow.append(Paragraph("<b>Sintesis.</b> " + report_data.get("sintesis", ""), S["body"]))

    # Rencana Trading — Fixed Entry Levels
    fe_blk = _fixed_entries_table(report_data.get("fixed_entries"), S)
    if fe_blk:
        flow += _section("Rencana Trading — Entry / SL / TP", S)
        flow += fe_blk

    # Skenario MA
    sc = _scenario_table(report_data.get("skenario"), S)
    if sc is not None:
        flow += _section("Skenario Teknikal (berbasis MA)", S)
        flow.append(sc)
        flow.append(Spacer(1, 3))
        flow.append(Paragraph(
            "Kecondongan skenario diturunkan dari konfluensi indikator — bukan probabilitas statistik.",
            S["small"]))

    # Smart Money Concepts
    if report_data.get("smc"):
        flow += _section("Smart Money Concepts (SMC)", S)
        flow += _smc_section(report_data["smc"], S)

    # Konteks Pasar (IHSG) + RS
    ihsg_txt = report_data.get("konteks_ihsg")
    rs_txt = report_data.get("rs_text")
    if ihsg_txt or rs_txt:
        flow += _section("Konteks Pasar (IHSG)", S)
        if ihsg_txt:
            flow.append(Paragraph(ihsg_txt, S["body"]))
        if rs_txt:
            flow.append(Spacer(1, 4))
            flow.append(Paragraph(rs_txt, S["body"]))

    # Insight naratif lengkap (sintesis dari seluruh data)
    insight_full = report_data.get("insight_full") or {}
    berita_narasi = insight_full.get("berita")
    if berita_narasi:
        flow += _section("Insight — Berita & Sentimen", S)
        flow.append(Paragraph(berita_narasi, S["body"]))

    # Berita (list judul)
    if report_data.get("berita"):
        flow += _section("Berita Terkait", S)
        for it in report_data["berita"][:6]:
            judul = it.get("title", "")
            src = it.get("source", "")
            flow.append(Paragraph(f"• <b>{judul}</b> <font color='#5B6470'>({src})</font>", S["cell"]))

    # Manajemen Risiko
    flow += _section("Manajemen Risiko", S)
    flow.append(Paragraph(report_data.get("risiko", ""), S["body"]))

    # Disclaimer
    flow.append(Spacer(1, 10))
    flow.append(HRFlowable(width="100%", thickness=0.5, color=GREY))
    flow.append(Spacer(1, 4))
    flow.append(Paragraph(
        "<b>Disclaimer.</b> Laporan ini dihasilkan otomatis dari analisis teknikal kuantitatif "
        "(rule-based) atas data harga historis, dan BUKAN rekomendasi jual/beli, ajakan investasi, "
        "atau nasihat keuangan. Analisis teknikal menggambarkan kondisi historis & saat ini, tidak "
        "menjamin pergerakan harga ke depan. Keputusan investasi sepenuhnya tanggung jawab pembaca. "
        "Lakukan riset mandiri (DYOR) dan kelola risiko.", S["small"]))

    doc.build(flow)
    return output_path


def _ihsg_header(data, S, logo_path):
    title_cell = [
        Paragraph(data.get("judul", "LAPORAN ANALISIS IHSG"), S["title"]),
        Paragraph(f"{data.get('subjudul','')} &nbsp;•&nbsp; {datetime.now().strftime('%d %B %Y')}",
                  S["subtitle"]),
    ]
    pred = (data.get("prediction") or "-")
    fg = GREEN if "BULLISH" in pred.upper() and "BEAR" not in pred.upper() else \
        RED if "BEARISH" in pred.upper() else ACCENT
    pred_style = ParagraphStyle("pred", fontName="Helvetica-Bold", fontSize=12,
                                textColor=colors.white, alignment=TA_CENTER, leading=15)
    conf_style = ParagraphStyle("conf", fontName="Helvetica", fontSize=8,
                                textColor=ACCENT, alignment=TA_CENTER, leading=10)
    pred_cell = [Paragraph(pred, pred_style),
                 Paragraph(f"Keyakinan: {data.get('confidence','-')}", conf_style)]
    logo = ""
    if logo_path and os.path.exists(logo_path):
        try:
            logo = Image(logo_path, width=21 * mm, height=21 * mm)
        except Exception:
            logo = ""
    inner = Table([[logo, title_cell, pred_cell]], colWidths=[30 * mm, 100 * mm, 40 * mm])
    inner.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("BACKGROUND", (2, 0), (2, 0), NAVY_SOFT),
    ]))
    return inner


def generate_ihsg_report_pdf(data: dict, output_path: str, logo_path: str | None = None) -> str:
    """Render laporan IHSG (market-wide) -> PDF. Sama gaya dengan laporan
    saham, tapi seksi disesuaikan (prediksi, level, rotasi sektor)."""
    logo_path = logo_path or _DEFAULT_LOGO
    S = _styles()
    doc = SimpleDocTemplate(output_path, pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=14 * mm, bottomMargin=16 * mm, title="Laporan IHSG")
    flow = [_ihsg_header(data, S, logo_path), Spacer(1, 10)]

    # Rekomendasi / action
    flow += _section("Prediksi & Rekomendasi", S)
    flow.append(Paragraph(f"<b>Prediksi:</b> {data.get('prediction','-')} "
                          f"&nbsp;|&nbsp; <b>Keyakinan:</b> {data.get('confidence','-')}", S["body"]))
    if data.get("action"):
        flow.append(Paragraph(f"<b>Rekomendasi:</b> {data['action']}", S["body"]))
    if data.get("backtest_txt"):
        flow.append(Spacer(1, 3))
        flow.append(Paragraph(data["backtest_txt"], S["body"]))

    # Chart
    chart = _chart_image(data.get("chart_path"))
    if chart is not None:
        flow += _section("Grafik IHSG", S)
        flow.append(chart)

    # Snapshot
    flow += _section("Ringkasan Indikator", S)
    flow.append(_kv_table(data.get("snapshot", []), S, [70 * mm, 100 * mm]))

    # Levels
    if data.get("levels"):
        flow += _section("Level Kunci", S)
        flow.append(_kv_table(data["levels"], S, [70 * mm, 100 * mm]))

    # Smart Money Concepts (opsional) — sama seperti laporan saham
    if data.get("smc"):
        flow += _section("Smart Money Concepts (SMC)", S)
        flow += _smc_section(data["smc"], S)

    # Rotasi sektor
    if data.get("sektor_rows"):
        flow += _section("Rotasi Sektor", S)
        if data.get("sektor_narasi"):
            flow.append(Paragraph(data["sektor_narasi"], S["body"]))
            flow.append(Spacer(1, 4))
        srows = [[Paragraph("Sektor", S["cellb"]), Paragraph("Return", S["cellb"])]]
        sstyle = [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDE1E7")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ]
        for i, (nama, ret) in enumerate(data["sektor_rows"], start=1):
            fg = GREEN if ret.startswith("+") else RED if ret.startswith("-") else GREY
            rs = ParagraphStyle(f"r{i}", fontName="Helvetica-Bold", fontSize=8.8, textColor=fg, leading=12)
            srows.append([Paragraph(nama, S["cell"]), Paragraph(ret, rs)])
        st = Table(srows, colWidths=[120 * mm, 50 * mm])
        st.setStyle(TableStyle(sstyle))
        flow.append(st)

    # Narasi teknikal IHSG (dari market insight)
    if data.get("market_narasi"):
        flow += _section("Analisis Teknikal IHSG", S)
        flow.append(Paragraph(data["market_narasi"], S["body"]))

    # Sintesis market (dari generate_market_insight)
    if data.get("market_sintesis"):
        flow += _section("Sintesis Pasar", S)
        flow.append(Paragraph(data["market_sintesis"], S["body"]))

    # Berita
    if data.get("berita"):
        flow += _section("Berita Pasar Terkait", S)
        for it in data["berita"][:5]:
            flow.append(Paragraph(f"• <b>{it.get('title','')}</b> "
                                  f"<font color='#5B6470'>({it.get('source','')})</font>", S["cell"]))

    # Disclaimer
    flow.append(Spacer(1, 10))
    flow.append(HRFlowable(width="100%", thickness=0.5, color=GREY))
    flow.append(Spacer(1, 4))
    flow.append(Paragraph(
        "<b>Disclaimer.</b> Laporan IHSG ini dihasilkan otomatis dari analisis teknikal kuantitatif "
        "atas data indeks historis, dan BUKAN rekomendasi atau nasihat keuangan. Analisis teknikal "
        "tidak menjamin pergerakan ke depan. Lakukan riset mandiri (DYOR) dan kelola risiko.", S["small"]))

    doc.build(flow)
    return output_path
