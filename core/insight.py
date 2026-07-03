# =========================
# INSIGHT (RULE-BASED NARRATIVE SYNTHESIS)
# =========================
# /insight KODE -- merangkai data dari AI Score (teknikal saham),
# konteks IHSG, dan berita jadi satu narasi yang enak dibaca.
# /insight IHSG (atau /insight tanpa argumen) -- insight market-wide
# untuk IHSG itu sendiri, dengan narasi rotasi sektor.
#
# REVISI KEDUA (Juni 2026): user menunjukkan contoh laporan analisis
# trading multi-agent (gaya "TradingAgents" -- 4 analis spesialis +
# debat Bull/Bear + debat Risk Management + keputusan Portfolio
# Manager). KEPUTUSAN EKSPLISIT setelah dijelaskan bahwa level laporan
# itu BUTUH LLM beneran (penalaran dinamis merespons argumen lawan,
# BUKAN sesuatu yang bisa ditiru template kondisional): TETAP RULE-
# BASED & GRATIS, perkaya template yang ada. Perkayaan yang dilakukan:
# 1. _narrate_technical() jauh lebih detail -- MA200 alignment, MACD
#    histogram + arah, Bollinger position, ATR (volatilitas), DAN
#    ringkasan konfluensi eksplisit ("X Bullish/Y Bearish/Z Netral",
#    terinspirasi gaya "Skor Konfluensi: 5 Bearish/1 Bullish/2 Netral"
#    di contoh laporan user -- TAPI dihitung dari kondisi data asli,
#    bukan ditulis manusia). Semua field BARU ini SEBENARNYA SUDAH
#    DIHITUNG secara internal di calculate_ai_score_from_df()
#    (core/ai_score.py) untuk keperluan skoring -- cuma di-expose ke
#    return dict sekarang (PURE ADDITION, tidak mengubah field lama).
# 2. /insight IHSG (BARU) -- generate_market_insight(), insight
#    market-wide TERPISAH dari insight per-saham karena membandingkan
#    "IHSG vs IHSG" tidak masuk akal. Sebagai gantinya: narasi ROTASI
#    SEKTOR (sektor mana memimpin/tertinggal, REUSE get_sector_
#    performance() dari core/sector_rotation.py, logic SAMA yang
#    dipakai /sektor) DAN breadth analysis (apakah penguatan/pelemahan
#    IHSG didukung MAYORITAS sektor / broad-based, atau cuma
#    segelintir saham besar / narrow -- distingsi teknis yang
#    sungguhan, bukan cuma kalimat hiasan).
#
# REVISI PERTAMA (sesi sebelumnya): komponen FUNDAMENTAL diganti TOTAL
# dengan KONTEKS IHSG (lihat _narrate_ihsg_context & _narrate_synthesis
# di bawah) -- alasan: arah saham individual sangat dipengaruhi arah
# IHSG, dan data fundamental yfinance py unya ketidakpastian unit yang
# sudah diakui jujur (lihat core/fundamental.py).
#
# KEPUTUSAN ARSITEKTUR: rule-based (template kondisional), BUKAN LLM --
# pilihan eksplisit user demi menghindari biaya API berbayar, DIKONFIRMASI
# ULANG di revisi kedua ini meski user sempat menunjukkan contoh yang
# levelnya jauh melampaui kemampuan rule-based. Setiap "kalimat" dipilih
# dari variasi berdasarkan kondisi data, disambung jadi paragraf -- BUKAN
# AI generatif sungguhan.
#
# CATATAN KRUSIAL SOAL BAHASA (terkait diskusi regulasi OJK finfluencer):
# narasi DIDESAIN SECARA SENGAJA memakai bahasa DESKRIPTIF ("data
# menunjukkan", "RSI berada di zona X") BUKAN PRESKRIPTIF ("sebaiknya
# beli", "rekomendasi kami"). Disclaimer di akhir SELALU ditampilkan.
#
# CATATAN PENGEMBANGAN: saat ini setiap kondisi cuma punya 1 variasi
# kalimat (deterministik, gampang ditest), belum random.choice([...]).


from core.messages import sanitize_for_markdown


def _narrate_technical(ai: dict) -> str:
    """Bangun narasi kondisi teknikal dari hasil AI Score -- DIPERKAYA
    (revisi kedua, Juni 2026) dengan trend MA detail, momentum (RSI+
    MACD+StochRSI), volatilitas (Bollinger+ATR), volume, dan ringkasan
    konfluensi eksplisit. Dipakai untuk insight per-saham MAUPUN
    insight market-wide IHSG.

    PENTING SOAL AKURASI/KONSISTENSI (ditemukan & diperbaiki saat
    membangun versi ini): narasi SELALU memakai detail string yang
    SAMA PERSIS dipakai untuk klasifikasi confluence count di
    core/ai_score.py (ma_detail, macd_detail, rsi_detail, vol_detail,
    bb_detail) -- BUKAN re-derive perbandingan baru (mis. cek ulang
    "price>MA50>MA200" secara terpisah), supaya narasi TIDAK PERNAH
    kelihatan kontradiksi dengan angka konfluensi yang ditampilkan di
    kalimat terakhir (keduanya berasal dari satu sumber klasifikasi
    yang sama)."""
    sentences = []

    # ===== TREND (pakai ma_detail -- satu sumber kebenaran) =====
    ma_value_text = f"MA20 Rp{ai['ma20']:,.0f}, MA50 Rp{ai['ma50']:,.0f}"
    if ai["ma200"] is not None:
        ma_value_text += f", MA200 Rp{ai['ma200']:,.0f}"
    sentences.append(f"Dari sisi tren: {ai['ma_detail']}. Posisi rata-rata bergerak saat ini: {ma_value_text}.")

    # ===== MOMENTUM (pakai rsi_detail & macd_detail -- satu sumber kebenaran) =====
    momentum_sentence = f"{ai['rsi_detail']}. {ai['macd_detail']}."
    if ai["golden_cross"]:
        momentum_sentence += f" StochRSI baru saja membentuk golden cross (K={ai['stoch_k']} > D={ai['stoch_d']})."
    sentences.append(momentum_sentence)

    # ===== VOLATILITAS (pakai bb_detail -- satu sumber kebenaran -- + ATR) =====
    atr_label = "tergolong tinggi" if ai["atr_pct"] > 3 else "tergolong moderat" if ai["atr_pct"] > 1.5 else "tergolong rendah"
    sentences.append(
        f"Dari sisi volatilitas: {ai['bb_detail']}. ATR harian sekitar {ai['atr_pct']:.1f}% dari harga ({atr_label})."
    )

    # ===== VOLUME (pakai vol_detail -- satu sumber kebenaran) =====
    sentences.append(f"{ai['vol_detail']}.")

    # ===== KONFLUENSI SINYAL =====
    sentences.append(
        f"Secara konfluensi dari 6 indikator yang dipantau: {ai['bullish_count']} bullish, "
        f"{ai['bearish_count']} bearish, {ai['netral_count']} netral."
    )

    return " ".join(sentences)


def _narrate_ihsg_context(ai_ihsg: dict, rs_data: dict | None) -> str:
    """Bangun narasi kondisi IHSG saat ini DAN posisi relatif saham
    terhadap IHSG -- DIPAKAI KHUSUS untuk insight PER-SAHAM (BUKAN
    untuk insight IHSG itu sendiri, lihat generate_market_insight).

    ai_ihsg: hasil calculate_ai_score_from_df() pada data OHLCV IHSG.
    rs_data: hasil calculate_relative_strength() (core/relative_
    strength.py, logic SAMA yang dipakai /rs) -- bisa None."""
    sentences = []

    if ai_ihsg["score"] >= 60:
        ihsg_kondisi = "cenderung menguat"
    elif ai_ihsg["score"] < 40:
        ihsg_kondisi = "cenderung melemah"
    else:
        ihsg_kondisi = "bergerak relatif sideways/netral"

    sentences.append(
        f"IHSG sendiri saat ini {ihsg_kondisi} (RSI {ai_ihsg['rsi']}, {ai_ihsg['ma5_ma20']})."
    )

    if rs_data:
        diff = rs_data["rs_diff"]
        period = rs_data["period_days"]
        if diff > 5:
            relasi = (
                f"jauh lebih kuat dibanding IHSG dalam {period} hari terakhir "
                f"(saham {rs_data['stock_return']:+.1f}% vs IHSG {rs_data['benchmark_return']:+.1f}%, "
                f"selisih {diff:+.1f} poin persentase)"
            )
        elif diff > 1:
            relasi = (
                f"sedikit lebih kuat dibanding IHSG dalam {period} hari terakhir "
                f"(selisih {diff:+.1f} poin persentase)"
            )
        elif diff > -1:
            relasi = (
                f"bergerak relatif sejalan dengan IHSG dalam {period} hari terakhir, "
                f"tidak menunjukkan kekuatan atau kelemahan relatif yang signifikan"
            )
        elif diff > -5:
            relasi = (
                f"sedikit lebih lemah dibanding IHSG dalam {period} hari terakhir "
                f"(selisih {diff:+.1f} poin persentase)"
            )
        else:
            relasi = (
                f"jauh lebih lemah dibanding IHSG dalam {period} hari terakhir "
                f"(saham {rs_data['stock_return']:+.1f}% vs IHSG {rs_data['benchmark_return']:+.1f}%, "
                f"selisih {diff:+.1f} poin persentase)"
            )
        sentences.append(f"Saham ini {relasi}.")

    return " ".join(sentences)


def _narrate_sector_leadership(sector_data: list[dict] | None) -> str:
    """Narasikan sektor mana yang memimpin/tertinggal pergerakan IHSG
    -- KHUSUS insight market-wide (IHSG), TIDAK dipakai di insight
    per-saham.

    CATATAN: dokumentasi lama fungsi ini bilang sector_data "REUSE
    get_sector_performance() dari core/sector_rotation.py" -- itu TIDAK
    akurat untuk semua caller. /api/insight/{kode} (web/app.py) sebenarnya
    memberi data dari endpoint sektor() lokalnya sendiri, bentuknya beda
    (nama_sektor/return_pct/n_saham, TANPA field 'ticker'). Makanya kode
    di bawah dedup pakai 'nama_sektor' (ada di SEMUA bentuk data sektor
    yang beredar di codebase ini), bukan 'ticker' (ditemukan nyata:
    versi awal fix ini pakai 'ticker' dan crash KeyError persis di jalur
    /api/insight/IHSG)."""
    if not sector_data:
        return "Data performa sektor tidak tersedia untuk melengkapi insight ini."

    leaders = sector_data[:3]
    # Laggard TIDAK BOLEH tumpang tindih dengan leader -- ditemukan nyata:
    # data performa sektor bisa gagal SEBAGIAN (rate-limit Yahoo Finance),
    # jadi sector_data bisa tersisa <=6 entri. Pada kondisi itu,
    # sector_data[:3] dan sector_data[-3:] overlap -- sektor yang SAMA
    # disebut "paling kuat" SEKALIGUS "paling lemah" di kalimat yang sama
    # (pola bug yang sama dengan get_leader_laggard() di
    # core/sector_rotation.py).
    leader_keys = {s["nama_sektor"] for s in leaders}
    laggards = [s for s in reversed(sector_data) if s["nama_sektor"] not in leader_keys][:3]

    leader_text = ", ".join(f"{s['nama_sektor']} ({s['return_pct']:+.1f}%)" for s in leaders)
    laggard_text = (", ".join(f"{s['nama_sektor']} ({s['return_pct']:+.1f}%)" for s in laggards)
                    if laggards else "tidak ada (semua sektor yang berhasil dimuat sudah masuk daftar terkuat)")

    n_positive = sum(1 for s in sector_data if s["return_pct"] > 0)
    n_total = len(sector_data)

    if n_positive >= n_total * 0.6:
        breadth_text = "menunjukkan penguatan yang cukup merata (broad-based) di seluruh sektor."
    elif n_positive >= n_total * 0.3:
        breadth_text = "menunjukkan penguatan yang terkonsentrasi di sektor tertentu saja (narrow), bukan merata."
    else:
        breadth_text = "menunjukkan pelemahan yang cukup merata di kebanyakan sektor."

    return (
        f"Sektor paling kuat saat ini: {leader_text}. Sektor paling lemah: {laggard_text}. "
        f"Dari {n_total} sektor resmi IDX-IC, {n_positive} di antaranya bergerak positif -- {breadth_text}"
    )


def _narrate_news(news_items: list[dict] | None) -> str:
    """Bangun narasi keberadaan berita terkini, TANPA menyimpulkan
    sentimen berita (bot tidak melakukan analisis sentimen otomatis,
    lihat catatan jujur di core/news.py).

    PENTING: judul berita SUMBER EKSTERNAL -- disanitasi via
    sanitize_for_markdown() SEBELUM dirangkai jadi kalimat narasi
    (lihat catatan lengkap di core/messages.py)."""
    if not news_items:
        return "Tidak ditemukan berita terkini yang secara spesifik menyebut topik ini."

    n = len(news_items)
    judul_pertama = sanitize_for_markdown(news_items[0]["title"])
    if n == 1:
        return f"Ada 1 berita terkini terkait: \"{judul_pertama}\"."
    return (
        f"Ditemukan {n} berita terkini yang relevan, salah satunya: "
        f"\"{judul_pertama}\". Cek /news untuk daftar lengkapnya."
    )


def _derive_recommendation(ai_stock: dict, ai_ihsg: dict | None) -> dict:
    """Derive rekomendasi BUY / HOLD / SELL dari skor teknikal saham + konteks IHSG.
    Berbasis aturan sederhana, bukan LLM. BUKAN nasihat keuangan -- hanya
    ringkasan kondisi teknikal dari data yang sudah dihitung sebelumnya."""
    score = ai_stock.get("score", 50)
    bullish = ai_stock.get("bullish_count", 0)
    bearish = ai_stock.get("bearish_count", 0)
    netral = ai_stock.get("netral_count", 0)
    ihsg_score = ai_ihsg.get("score", 50) if ai_ihsg else 50

    if score >= 65:
        if ihsg_score >= 55:
            label = "BUY"
            strength = "kuat" if score >= 78 else "moderat"
            reason = (
                f"Skor teknikal tinggi ({score}/100, {bullish} dari 6 indikator bullish) "
                f"dan IHSG juga mendukung (skor {ihsg_score}) — momentum sejajar."
            )
        else:
            label = "HOLD"
            strength = "tipis"
            reason = (
                f"Teknikal saham cukup kuat (skor {score}) tetapi IHSG sedang melemah "
                f"(skor {ihsg_score}) — konfirmasi arah pasar lebih lanjut disarankan sebelum entry."
            )
    elif score >= 45:
        label = "HOLD"
        strength = "moderat" if 50 <= score < 65 else "tipis"
        reason = (
            f"Sinyal campuran: {bullish} indikator bullish, {bearish} bearish, {netral} netral dari 6 yang dipantau "
            f"(skor total {score}/100) — tidak ada edge teknikal yang jelas ke salah satu arah."
        )
    else:
        if ihsg_score >= 65:
            label = "HOLD"
            strength = "tipis"
            reason = (
                f"Teknikal saham lemah (skor {score}, {bearish} dari 6 indikator bearish) meski IHSG "
                f"menguat (skor {ihsg_score}) — ada tekanan jual yang spesifik pada saham ini."
            )
        else:
            label = "SELL"
            strength = "kuat" if score < 30 else "moderat"
            reason = (
                f"Teknikal melemah (skor {score}/100, {bearish} dari 6 indikator bearish) dan "
                f"IHSG juga tidak mendukung (skor {ihsg_score}) — kondisi tidak kondusif untuk hold/buy."
            )

    return {"label": label, "strength": strength, "reason": reason}


def _narrate_synthesis(ai_stock: dict, ai_ihsg: dict) -> str:
    """Kalimat penutup insight PER-SAHAM yang menggabungkan sinyal
    teknikal saham dengan arah IHSG -- MENYOROT KESELARASAN ATAU
    PERBEDAAN, BUKAN kesimpulan beli/jual. Bahasa SENGAJA deskriptif."""
    stock_bullish = ai_stock["score"] >= 60
    stock_bearish = ai_stock["score"] < 40
    ihsg_bullish = ai_ihsg["score"] >= 60
    ihsg_bearish = ai_ihsg["score"] < 40

    if stock_bullish and ihsg_bullish:
        return (
            "Secara keseluruhan, momentum teknikal saham ini SEARAH dengan IHSG yang sedang "
            "menguat -- pergerakan harga kemungkinan turut terdorong sentimen pasar secara umum, "
            "bukan murni faktor spesifik saham ini."
        )
    elif stock_bearish and ihsg_bearish:
        return (
            "Secara keseluruhan, tekanan teknikal pada saham ini SEARAH dengan IHSG yang sedang "
            "melemah -- pelemahan kemungkinan turut dipengaruhi sentimen pasar secara umum."
        )
    elif stock_bullish and ihsg_bearish:
        return (
            "Menarik: saham ini menunjukkan kekuatan teknikal di tengah IHSG yang sedang melemah "
            "-- ini mengindikasikan ada faktor SPESIFIK pada saham ini yang mendorong minat beli, "
            "terlepas dari kondisi pasar secara umum saat ini."
        )
    elif stock_bearish and ihsg_bullish:
        return (
            "Menarik: saham ini melemah meski IHSG sedang menguat -- ini mengindikasikan ada "
            "tekanan jual yang SPESIFIK pada saham ini, bukan sekadar imbas pelemahan pasar."
        )
    else:
        return (
            "Sinyal teknikal saham ini dan arah IHSG saat ini sama-sama belum menunjukkan "
            "kondisi yang ekstrem ke salah satu arah -- gambaran relatif campur/netral."
        )


def _narrate_market_synthesis(ai_ihsg: dict, sector_data: list[dict] | None) -> str:
    """Kalimat penutup insight MARKET-WIDE (IHSG) -- menyoroti apakah
    pergerakan IHSG didukung partisipasi luas sektor atau terkonsentrasi
    di segelintir saham/sektor besar saja (distingsi teknis sungguhan,
    bukan hiasan kalimat)."""
    if ai_ihsg["score"] >= 60:
        kondisi = "cenderung menguat"
    elif ai_ihsg["score"] < 40:
        kondisi = "cenderung melemah"
    else:
        kondisi = "bergerak campuran/netral"

    base = (
        f"Secara keseluruhan, IHSG saat ini {kondisi} dengan konfluensi "
        f"{ai_ihsg['bullish_count']} indikator bullish dari 6 yang dipantau."
    )

    if sector_data:
        n_positive = sum(1 for s in sector_data if s["return_pct"] > 0)
        n_total = len(sector_data)
        if n_positive >= n_total * 0.7 and ai_ihsg["score"] >= 60:
            base += " Penguatan ini didukung partisipasi luas dari sebagian besar sektor, bukan cuma segelintir saham besar."
        elif n_positive <= n_total * 0.3 and ai_ihsg["score"] < 40:
            base += " Pelemahan ini juga tercermin merata di sebagian besar sektor."
        elif n_positive >= n_total * 0.7 and ai_ihsg["score"] < 60:
            base += (
                " Menariknya, mayoritas sektor sebenarnya masih positif meski skor teknikal IHSG "
                "belum menunjukkan kondisi kuat -- bisa jadi indeks tertahan oleh saham-saham "
                "berbobot besar yang melemah."
            )

    return base


async def generate_insight(ticker: str, ai_score: dict, ai_ihsg: dict | None,
                              rs_data: dict | None, news_items: list[dict] | None) -> dict:
    """Rangkai data jadi narasi insight PER-SAHAM. Fungsi ini PURE
    (caller bertanggung jawab fetch data dari modul masing-masing).

    ai_ihsg & rs_data BISA None (kalau data IHSG gagal diambil) --
    fungsi ini TETAP menghasilkan narasi yang masuk akal, BUKAN crash."""
    teknikal_text = _narrate_technical(ai_score)

    if ai_ihsg is not None:
        ihsg_text = _narrate_ihsg_context(ai_ihsg, rs_data)
        synthesis_text = _narrate_synthesis(ai_score, ai_ihsg)
    else:
        ihsg_text = "Data IHSG tidak berhasil diambil, konteks pasar tidak tersedia untuk insight ini."
        synthesis_text = (
            "Sintesis dengan arah IHSG tidak bisa dilakukan karena data IHSG gagal diambil -- "
            "insight ini hanya berdasarkan kondisi teknikal saham itu sendiri."
        )

    news_text = _narrate_news(news_items)

    full_narrative = f"{teknikal_text}\n\n{ihsg_text}\n\n{news_text}\n\n{synthesis_text}"

    recommendation = _derive_recommendation(ai_score, ai_ihsg)

    return {
        "ticker": ticker,
        "recommendation": recommendation,
        "teknikal": teknikal_text,
        "konteks_ihsg": ihsg_text,
        "berita": news_text,
        "sintesis": synthesis_text,
        "narasi_lengkap": full_narrative,
    }


async def generate_market_insight(ai_ihsg: dict, sector_data: list[dict] | None,
                                     news_items: list[dict] | None) -> dict:
    """Rangkai data jadi narasi insight MARKET-WIDE untuk IHSG itu
    sendiri (BARU). BEDA dari generate_insight (per-saham): TIDAK ADA
    perbandingan "vs IHSG" (membandingkan IHSG dengan dirinya sendiri
    tidak masuk akal) -- diganti narasi ROTASI SEKTOR (sektor mana
    memimpin/tertinggal + breadth analysis).

    ai_ihsg: hasil calculate_ai_score_from_df() pada data OHLCV IHSG --
    REUSE fungsi yang sama dipakai saham, IHSG diperlakukan sebagai
    "saham" untuk keperluan skoring teknikal ini, sah karena cuma data
    OHLCV biasa.
    sector_data: hasil get_sector_performance() (core/sector_rotation.py).
    Bisa None kalau gagal diambil -- TETAP menghasilkan narasi masuk
    akal, BUKAN crash."""
    teknikal_text = _narrate_technical(ai_ihsg)
    sektor_text = _narrate_sector_leadership(sector_data)
    news_text = _narrate_news(news_items)
    synthesis_text = _narrate_market_synthesis(ai_ihsg, sector_data)

    full_narrative = f"{teknikal_text}\n\n{sektor_text}\n\n{news_text}\n\n{synthesis_text}"

    return {
        "ticker": "IHSG",
        "teknikal": teknikal_text,
        "sektor": sektor_text,
        "berita": news_text,
        "sintesis": synthesis_text,
        "narasi_lengkap": full_narrative,
    }
