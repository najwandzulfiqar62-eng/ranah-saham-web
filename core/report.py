# =========================
# LAPORAN PREMIUM - INSIGHT BUILDER
# =========================
# Menyusun data terhitung bot (AI Score, konteks IHSG, sektor, berita)
# jadi struktur "report_data" yang dirender ke PDF profesional oleh
# core/charts/report_pdf.py. Fungsi di sini MURNI (tanpa I/O) -> caller
# (handler) yang fetch datanya, sehingga bisa di-unit-test tanpa network.
#
# SOAL "INSIGHT YANG LEBIH MAHAL" (penting & jujur):
# Contoh laporan multi-agent yang jadi acuan (debat Bull vs Bear yang
# SALING MERESPONS, analisis makro Fed/geopolitik) butuh LLM beneran --
# penalaran dinamis itu TIDAK bisa ditiru template kondisional, dan ini
# SUDAH dicatat sebagai keputusan sadar di core/insight.py. Yang dibangun
# di sini: insight rule-based yang DIPERKAYA & DISTRUKTUR seperti laporan
# analis (perspektif Bull, Bear, sintesis Netral, skenario, manajemen
# risiko) -- semuanya DITURUNKAN dari indikator SUNGGUHAN, bukan klaim
# makro yang dikarang. Kalau nanti mau penalaran dinamis penuh, ada hook
# LLM opsional di build_report_data() (ENABLE_LLM_NARRATIVE, default mati).
#
# PRINSIP JUJUR yang dipegang (konsisten dengan disiplin proyek):
# - TIDAK mengarang fakta makro/fundamental yang bot tidak hitung
#   (kepemimpinan Fed, geopolitik, P/E, cadangan devisa) -- bagian makro
#   HANYA diisi dari berita yang benar-benar diambil, kalau ada.
# - "Skenario" diberi CONDONG (lean) berdasarkan hitungan konfluensi
#   indikator, BUKAN persentase probabilitas statistik palsu.
# - Level diturunkan dari MA/harga yang sungguhan dihitung ai_score.

ENABLE_LLM_NARRATIVE = False  # hook opsional; lihat build_report_data()


def build_smc_summary(df) -> dict | None:
    """Rangkum Smart Money Concepts dari OHLCV: struktur pasar (BOS/CHoCH),
    order block, dan Fair Value Gap. MURNI pandas (tanpa network) -> bisa
    diuji langsung. Tiap detektor dibungkus try/except: kalau satu gagal,
    yang lain tetap jalan. Return None kalau semua kosong/gagal."""
    from core.smc import detect_bos_choch, detect_order_blocks, detect_fvg, detect_liquidity_pools

    try:
        events = detect_bos_choch(df) or []
    except Exception as e:
        print(f"⚠️ SMC bos_choch gagal: {e}"); events = []
    try:
        obs = detect_order_blocks(df) or []
    except Exception as e:
        print(f"⚠️ SMC order_blocks gagal: {e}"); obs = []
    try:
        fvgs = detect_fvg(df) or []
    except Exception as e:
        print(f"⚠️ SMC fvg gagal: {e}"); fvgs = []
    try:
        pools = detect_liquidity_pools(df) or []
    except Exception as e:
        print(f"⚠️ SMC liquidity gagal: {e}"); pools = []

    if not (events or obs or fvgs or pools):
        return None

    n_bos = sum(1 for e in events if e.get("type") == "BOS")
    n_choch = sum(1 for e in events if e.get("type") == "CHOCH")
    last = events[-1] if events else None
    last_struktur = None
    if last:
        arah = "bullish" if last.get("direction") == "bullish" else "bearish"
        tipe = "Break of Structure" if last.get("type") == "BOS" else "Change of Character"
        last_struktur = f"{tipe} ({arah}) di Rp{_fmt(last.get('price'))}"

    ob_bull = sum(1 for o in obs if o.get("type") == "BULLISH")
    ob_bear = sum(1 for o in obs if o.get("type") == "BEARISH")
    fvg_unfilled = [f for f in fvgs if not f.get("filled")]

    liq_high = sum(1 for p in pools if p.get("type") == "HIGH")
    liq_low = sum(1 for p in pools if p.get("type") == "LOW")
    liq_unswept = [p for p in pools if not p.get("swept")]

    # Narasi jujur: SMC itu deskriptif (area minat & struktur), bukan ramalan.
    bagian = []
    if last_struktur:
        catatan = ("CHoCH menandai potensi pergantian arah; perlu konfirmasi lanjutan."
                   if last and last.get("type") == "CHOCH"
                   else "BOS menandai kelanjutan struktur tren yang ada.")
        bagian.append(f"Struktur pasar terakhir: {last_struktur}. {catatan}")
    if obs:
        bagian.append(f"Terdeteksi {len(obs)} order block ({ob_bull} bullish / {ob_bear} bearish) "
                      f"— area harga tempat institusi diduga menempatkan order.")
    if fvg_unfilled:
        bagian.append(f"Ada {len(fvg_unfilled)} Fair Value Gap belum terisi — celah harga yang "
                      f"sering jadi magnet pergerakan berikutnya.")
    if pools:
        bagian.append(f"Terdeteksi {len(pools)} liquidity pool ({liq_high} di atas / {liq_low} di bawah "
                      f"harga, {len(liq_unswept)} belum tersapu) — area equal high/low tempat likuiditas "
                      f"menumpuk dan harga sering 'diburu'.")
    narasi = (" ".join(bagian) +
              " Catatan: SMC bersifat deskriptif (struktur & area minat), bukan sinyal pasti arah.")

    return {
        "n_bos": n_bos, "n_choch": n_choch,
        "last_struktur": last_struktur,
        "events": events[-3:][::-1],
        "ob_bullish": ob_bull, "ob_bearish": ob_bear,
        "fvg_unfilled": len(fvg_unfilled),
        "fvg_list": fvg_unfilled[-3:][::-1],
        "liq_high": liq_high, "liq_low": liq_low,
        "liq_unswept": len(liq_unswept),
        "liq_list": pools[:3],
        "narasi": narasi,
    }


def build_ihsg_report_data(analysis: dict, sector_data: list[dict] | None = None,
                           market_insight: dict | None = None,
                           news_items: list[dict] | None = None,
                           chart_path: str | None = None,
                           smc: dict | None = None,
                           smc_charts: dict | None = None) -> dict:
    """Susun data laporan IHSG (market-wide) dari analyze_ihsg_with_backtest()
    + rotasi sektor + insight market. Murni (tanpa I/O)."""
    a = analysis
    snapshot = [
        ("Harga Terakhir (Close)", f"Rp{_fmt(a.get('current_price'))}"),
        ("Perubahan Harian", f"{a.get('daily_change', 0):+.2f}%"),
        ("Prediksi", a.get("prediction", "-")),
        ("Keyakinan", a.get("confidence", "-")),
        ("Skor Bullish vs Bearish", f"{a.get('bullish_score')}% vs {a.get('bearish_score')}%"),
        ("Target Pergerakan", a.get("target_move", "-")),
        ("Tren MA", a.get("ma_trend", "-")),
        ("RSI (14)", f"{a.get('rsi')} (divergence: {a.get('rsi_divergence')})"),
        ("MACD", a.get("macd_signal", "-")),
        ("Volume", f"{a.get('volume_trend','-')} ({a.get('volume_ratio')}x)"),
    ]
    levels = [
        ("Resistance 2", f"Rp{_fmt(a.get('resistance_2'))}"),
        ("Resistance 1", f"Rp{_fmt(a.get('resistance_1'))}"),
        ("Support 1", f"Rp{_fmt(a.get('support_1'))}"),
        ("Support 2", f"Rp{_fmt(a.get('support_2'))}"),
        ("Volume Profile (POC)", f"Rp{_fmt(a.get('poc'))}"),
        ("Zona Entry", a.get("entry_zone", "-")),
        ("Stop Loss (acuan)", f"Rp{_fmt(a.get('stop_loss'))}"),
    ]

    # Backtest (kalau ada) — ditampilkan jujur sebagai validasi historis,
    # DENGAN baseline/edge supaya angka win rate tidak menyesatkan.
    bt = a.get("backtest_result")
    backtest_txt = None
    if bt and isinstance(bt, dict):
        wr = bt.get("win_rate")
        occ = bt.get("n") or bt.get("occurrences") or bt.get("total")
        base = bt.get("base_rate")
        edge = bt.get("edge")
        if wr is not None:
            txt = (
                f"Validasi historis: pada kondisi serupa di masa lalu ({occ} kejadian), "
                f"arah prediksi terkonfirmasi sekitar {wr}% dari waktu dalam "
                f"{bt.get('forward_days', 5)} hari berikutnya."
            )
            if base is not None:
                arah_edge = "DI ATAS" if (edge or 0) > 0 else "DI BAWAH" if (edge or 0) < 0 else "SAMA DENGAN"
                txt += (
                    f" Sebagai pembanding, base rate (peluang naik tanpa syarat di periode mana pun) "
                    f"adalah {base}% — jadi sinyal ini {arah_edge} baseline sebesar "
                    f"{abs(edge) if edge is not None else 0} poin persen (edge). "
                )
                if (edge or 0) <= 1:
                    txt += ("Edge yang tipis/negatif berarti sinyal ini TIDAK lebih baik dari "
                            "sekadar mengikuti kecenderungan pasar — perlakukan dengan hati-hati. ")
            txt += "Semua ini statistik historis in-sample, BUKAN jaminan masa depan."
            backtest_txt = txt

    # Rotasi sektor
    sektor_rows = None
    sektor_narasi = (market_insight or {}).get("market_synthesis") or (market_insight or {}).get("sektor")
    if sector_data:
        srt = sorted(sector_data, key=lambda s: s.get("return_pct", 0), reverse=True)
        sektor_rows = [(s.get("nama_sektor", "-"), f"{s.get('return_pct', 0):+.2f}%") for s in srt]

    # Sematkan chart-chart SMC ke dalam dict smc (kalau ada), sama seperti
    # laporan saham. _smc_section di renderer dipakai ulang untuk IHSG.
    if smc is not None and smc_charts:
        smc = {**smc, "charts": smc_charts}

    return {
        "jenis": "ihsg",
        "judul": "LAPORAN ANALISIS IHSG",
        "subjudul": "Indeks Harga Saham Gabungan (^JKSE)",
        "prediction": a.get("prediction"),
        "confidence": a.get("confidence"),
        "action": a.get("action"),
        "chart_path": chart_path,
        "snapshot": snapshot,
        "levels": levels,
        "backtest_txt": backtest_txt,
        "smc": smc,
        "sektor_rows": sektor_rows,
        "sektor_narasi": sektor_narasi,
        "market_narasi": (market_insight or {}).get("teknikal"),
        "market_sintesis": (market_insight or {}).get("sintesis"),
        "berita": news_items or None,
    }


def _fmt(n, desimal=0):
    try:
        return f"{n:,.{desimal}f}"
    except Exception:
        return str(n)


def _bull_case(ai: dict) -> list[str]:
    """Kumpulkan argumen BULLISH yang BENAR-BENAR ada di data ai_score."""
    pts = []
    if ai.get("cond_ma"):
        pts.append("MA5 berada di atas MA20 — momentum jangka pendek condong positif.")
    if ai.get("golden_cross"):
        pts.append("Golden cross aktif (MA50 di atas MA200) — struktur tren menengah-panjang membaik.")
    if ai.get("macd_bullish"):
        pts.append("MACD berada di atas garis sinyal — momentum bullish sedang terbentuk.")
    if ai.get("is_oversold"):
        pts.append(f"RSI di area oversold ({ai.get('rsi')}) — ada potensi rebound teknikal dari titik jenuh jual.")
    ma200 = ai.get("ma200")
    if ma200 and ai.get("price", 0) > ma200:
        pts.append(f"Harga ({_fmt(ai['price'])}) masih di atas MA200 ({_fmt(ma200)}) — tren jangka panjang relatif sehat.")
    if ai.get("cond_volume_spike"):
        pts.append("Terjadi lonjakan volume di atas rata-rata — ada partisipasi/minat beli yang nyata.")
    if ai.get("change_5d", 0) > 0:
        pts.append(f"Momentum 5 hari positif ({ai['change_5d']:+.1f}%).")
    if ai.get("bb_position") is not None and ai["bb_position"] < 25:
        pts.append(f"Harga dekat Bollinger lower band (posisi {ai['bb_position']:.0f}%) — area diskon secara teknikal.")
    if not pts:
        pts.append("Tidak ada argumen bullish yang menonjol dari indikator saat ini.")
    return pts


def _bear_case(ai: dict) -> list[str]:
    """Kumpulkan argumen BEARISH yang BENAR-BENAR ada di data ai_score."""
    pts = []
    if not ai.get("cond_ma"):
        pts.append("MA5 di bawah MA20 — momentum jangka pendek melemah.")
    ma200 = ai.get("ma200")
    if ma200 and ai.get("price", 0) < ma200:
        pts.append(f"Harga ({_fmt(ai['price'])}) di bawah MA200 ({_fmt(ma200)}) — tren jangka panjang masih bearish.")
    if not ai.get("golden_cross") and ma200:
        pts.append("Belum ada golden cross — struktur tren menengah-panjang belum berbalik naik.")
    if not ai.get("macd_bullish"):
        pts.append("MACD masih di bawah garis sinyal — momentum belum berbalik positif.")
    if ai.get("is_overbought"):
        pts.append(f"RSI di area overbought ({ai.get('rsi')}) — rawan koreksi jangka pendek.")
    if ai.get("atr_pct", 0) >= 3:
        pts.append(f"Volatilitas tinggi (ATR {ai['atr_pct']:.1f}% dari harga) — risiko ayunan harga besar, stop loss rentan tersapu.")
    if ai.get("bb_position") is not None and ai["bb_position"] > 80:
        pts.append(f"Harga dekat Bollinger upper band (posisi {ai['bb_position']:.0f}%) — area mahal secara teknikal.")
    if ai.get("change_5d", 0) < 0:
        pts.append(f"Momentum 5 hari negatif ({ai['change_5d']:+.1f}%).")
    if not pts:
        pts.append("Tidak ada argumen bearish yang menonjol dari indikator saat ini.")
    return pts


def _neutral_synthesis(ai: dict) -> str:
    """Sintesis netral: timbang konfluensi indikator (bukan opini)."""
    b = ai.get("bullish_count", 0)
    s = ai.get("bearish_count", 0)
    n = ai.get("netral_count", 0)
    lean = ("condong bullish" if b > s else "condong bearish" if s > b else "seimbang/sideways")
    return (
        f"Skor konfluensi indikator: {b} bullish / {s} bearish / {n} netral, sehingga gambaran teknikal "
        f"saat ini {lean}. AI Score gabungan berada di {ai.get('score')}/100 ({ai.get('rating')}), "
        f"dengan rekomendasi sistem: {ai.get('recommendation')}. Angka ini adalah ringkasan tertimbang "
        f"dari seluruh indikator di atas — bukan jaminan arah, melainkan potret kondisi saat laporan dibuat."
    )


def _scenarios(ai: dict) -> list[dict]:
    """Skenario berbasis level MA sungguhan. CONDONG (lean) diturunkan
    dari konfluensi, BUKAN persentase probabilitas statistik palsu."""
    ma20 = ai.get("ma20")
    ma50 = ai.get("ma50")
    price = ai.get("price")
    b, s = ai.get("bullish_count", 0), ai.get("bearish_count", 0)
    lean_bull = "Lebih mungkin" if b > s else "Kurang mungkin" if b < s else "Seimbang"
    lean_bear = "Lebih mungkin" if s > b else "Kurang mungkin" if s < b else "Seimbang"
    skenario = []
    if ma20 and ma50:
        skenario.append({
            "nama": "BULLISH", "arah": lean_bull,
            "kondisi": f"Break & tahan di atas MA20 ({_fmt(ma20)}) dengan volume",
            "target": f"Menuju MA50 ({_fmt(ma50)})",
        })
        skenario.append({
            "nama": "BEARISH", "arah": lean_bear,
            "kondisi": f"Gagal bertahan di atas MA20 ({_fmt(ma20)})",
            "target": f"Uji support di bawah harga ({_fmt(price)})",
        })
        skenario.append({
            "nama": "KONSOLIDASI", "arah": "Mungkin",
            "kondisi": f"Harga berkisar di sekitar MA20 ({_fmt(ma20)})",
            "target": "Range-bound, tunggu konfirmasi arah",
        })
    return skenario


def _risk_frame(ai: dict) -> str:
    atr = ai.get("atr_pct", 0)
    stop_min = atr * 2 if atr else None
    teks = (
        "Manajemen risiko bukan opsional. "
    )
    if stop_min:
        teks += (
            f"Dengan ATR {atr:.1f}% dari harga, stop loss yang masuk akal minimal sekitar "
            f"{stop_min:.1f}% dari titik masuk (≈2x ATR) agar tidak mudah tersapu noise harian. "
        )
    teks += (
        "Batasi ukuran posisi pada 1–2% dari total portofolio per ide trading, dan hindari menambah "
        "posisi hanya karena harga turun tanpa konfirmasi pembalikan. Gunakan /positionsize untuk "
        "menghitung jumlah lot sesuai risiko yang kamu tetapkan."
    )
    return teks


def build_report_data(ticker: str, nama: str, ai: dict,
                      insight: dict | None = None,
                      ai_ihsg: dict | None = None,
                      rs_data: dict | None = None,
                      sector_data: list[dict] | None = None,
                      news_items: list[dict] | None = None,
                      chart_path: str | None = None,
                      smc: dict | None = None,
                      smc_charts: dict | None = None,
                      vwap_fv: dict | None = None,
                      fixed_entries: dict | None = None,
                      rec_badge: dict | None = None) -> dict:
    """Bangun struktur lengkap untuk dirender PDF. Murni (tanpa I/O).

    HOOK LLM OPSIONAL: kalau ENABLE_LLM_NARRATIVE=True DAN caller
    menyuntikkan fungsi narasi LLM, bagian 'ringkasan_eksekutif' &
    'sintesis' bisa diganti hasil LLM. Default mati -> semua rule-based.
    """
    snapshot = [
        ("Harga Terakhir", f"Rp{_fmt(ai.get('price'))}"),
        ("Perubahan 1 Hari", f"{ai.get('change_1d', 0):+.2f}%"),
        ("Perubahan 5 Hari", f"{ai.get('change_5d', 0):+.2f}%"),
        ("AI Score", f"{ai.get('score')}/100 ({ai.get('rating')})"),
        ("RSI (14)", f"{ai.get('rsi')}"),
        ("MACD vs Signal", "Di atas (bullish)" if ai.get("macd_bullish") else "Di bawah (bearish)"),
        ("Rasio Volume", f"{ai.get('vol_ratio')}x rata-rata"),
        ("Volatilitas (ATR)", f"{ai.get('atr_pct')}% dari harga"),
    ]

    indikator_status = [
        ("Tren MA (5 vs 20)", "BULLISH" if ai.get("cond_ma") else "BEARISH",
         ai.get("ma5_ma20", "")),
        ("Golden/Death Cross", "GOLDEN CROSS" if ai.get("golden_cross") else "BELUM",
         f"MA50 {_fmt(ai.get('ma50'))} vs MA200 {_fmt(ai.get('ma200')) if ai.get('ma200') else 'n/a'}"),
        ("RSI", "OVERSOLD" if ai.get("is_oversold") else "OVERBOUGHT" if ai.get("is_overbought") else "NETRAL",
         f"{ai.get('rsi')}"),
        ("MACD", "BULLISH" if ai.get("macd_bullish") else "BEARISH",
         f"Histogram {ai.get('macd_hist')}"),
        ("Volume", "SPIKE" if ai.get("cond_volume_spike") else "NORMAL",
         f"{ai.get('vol_ratio')}x rata-rata"),
    ]

    # Tambah VWAP ke snapshot kalau ada
    if vwap_fv:
        snapshot.append(("VWAP Fair Value", f"Rp{_fmt(vwap_fv.get('vwap'))} "
                         f"({vwap_fv.get('label', '–')}, {vwap_fv.get('dev_pct', 0):+.1f}% vs VWAP)"))

    # RS vs IHSG
    rs_text = None
    if rs_data:
        diff = rs_data.get("rs_diff", 0)
        rs_text = (
            f"Saham ini {'lebih kuat' if diff > 0 else 'lebih lemah'} dari IHSG dalam "
            f"{rs_data.get('period_days', 20)} hari terakhir "
            f"(saham {rs_data.get('stock_return', 0):+.1f}% vs IHSG "
            f"{rs_data.get('benchmark_return', 0):+.1f}%, selisih {diff:+.1f} pp)."
        )

    # Sematkan SMC charts
    if smc is not None and smc_charts:
        smc = {**smc, "charts": smc_charts}

    data = {
        "ticker": ticker,
        "nama": nama,
        "score": ai.get("score"),
        "rating": ai.get("rating"),
        "recommendation": ai.get("recommendation"),
        "rec_badge": rec_badge,
        "signal": ai.get("signal"),
        "chart_path": chart_path,
        "snapshot": snapshot,
        "ringkasan_eksekutif": _neutral_synthesis(ai),
        "teknikal_narasi": (insight or {}).get("teknikal", ""),
        "indikator_status": indikator_status,
        "bull_case": _bull_case(ai),
        "bear_case": _bear_case(ai),
        "sintesis": (insight or {}).get("sintesis") or _neutral_synthesis(ai),
        "smc": smc,
        "skenario": _scenarios(ai),
        "risiko": _risk_frame(ai),
        "konteks_ihsg": (insight or {}).get("konteks_ihsg") if ai_ihsg else None,
        "rs_text": rs_text,
        "vwap_fv": vwap_fv,
        "fixed_entries": fixed_entries,
        "insight_full": insight,
        "berita": news_items or None,
        "sektor": sector_data or None,
    }

    # ---- HOOK LLM OPSIONAL (default mati) ----
    if ENABLE_LLM_NARRATIVE:
        # Tempat menyuntik narasi LLM (mis. panggil API Anthropic/lokal)
        # dengan GROUNDING ke data 'data' di atas supaya tidak halusinasi.
        # Sengaja dibiarkan sebagai titik ekstensi, bukan diaktifkan.
        pass

    return data
