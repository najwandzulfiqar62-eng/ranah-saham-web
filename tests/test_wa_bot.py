"""Perintah interaktif bot WhatsApp.

Dua hal yang paling gampang jadi bencana dan karena itu diuji paling ketat:
bot menyahut obrolan biasa (grup jadi berisik, nomor makin gampang dianggap
mesin oleh WhatsApp), dan bot melayani nomor yang belum di-approve (alur
daftar->persetujuan admin jadi sia-sia).
"""

import pytest

SECRET = "rahasia-wa-bot-khusus-pytest"


@pytest.fixture
def wa_bersih(monkeypatch):
    """DB akses kosong + secret bot terpasang + jeda per-nomor direset."""
    import web.app as app_module
    from core.access import ensure_access_tables, ensure_bootstrap_admin, invalidate_session_cache
    from core.database import get_db

    ensure_access_tables()
    with get_db() as conn:
        conn.execute("DELETE FROM access_session")
        conn.execute("DELETE FROM access_user")
    invalidate_session_cache()
    ensure_bootstrap_admin()

    monkeypatch.setattr(app_module, "WA_BOT_SECRET", SECRET)
    # Daftar emiten dibuat pasti, tidak bergantung isi data/saham.xlsx.
    monkeypatch.setattr(app_module, "_load_ticker_directory",
                        lambda: [{"kode": "BBCA", "nama": "Bank Central Asia"}])
    app_module._wa_last_reply.clear()
    app_module._wa_last_invite.clear()
    yield
    with get_db() as conn:
        conn.execute("DELETE FROM access_session")
        conn.execute("DELETE FROM access_user")
    invalidate_session_cache()
    app_module._wa_last_reply.clear()
    app_module._wa_last_invite.clear()


def _kirim(client, teks, nomor="6281234567890", secret=SECRET):
    return client.post("/api/wa/command",
                       json={"from": f"{nomor}@s.whatsapp.net", "text": teks},
                       headers={"Authorization": f"Bearer {secret}"})


def _daftarkan_approved(nomor="081234567890"):
    from core.access import list_users, register_user, set_user_status

    register_user("Anggota Bot", "bot@example.com", "password-pengguna-aman", "bukti.jpg", nomor)
    set_user_status(list_users("pending")[0]["id"], "approved")


def test_endpoint_menolak_pemanggil_tanpa_secret_yang_benar(client, wa_bersih):
    assert client.post("/api/wa/command", json={"from": "62812@s.whatsapp.net", "text": "sinyal"}).status_code == 401
    assert _kirim(client, "sinyal", secret="secret-palsu").status_code == 401


def test_endpoint_gagal_tertutup_saat_secret_belum_diisi(client, wa_bersih, monkeypatch):
    import web.app as app_module

    monkeypatch.setattr(app_module, "WA_BOT_SECRET", "")
    # Jalur ini dikecualikan dari access_gate, jadi ia TIDAK BOLEH terbuka
    # begitu saja ketika secretnya kosong.
    assert _kirim(client, "sinyal", secret="").status_code == 503


def test_obrolan_biasa_tidak_pernah_disahut(client, wa_bersih):
    _daftarkan_approved()
    for obrolan in ["halo semuanya", "pagi", "OKE", "makasih infonya ya bang"]:
        res = _kirim(client, obrolan)
        assert res.status_code == 200
        assert res.json()["reply"] is None, f"bot menyahut obrolan biasa: {obrolan!r}"


def test_nomor_belum_terdaftar_diarahkan_mendaftar_lalu_didiamkan(client, wa_bersih):
    pertama = _kirim(client, "BBCA", nomor="6289999999999").json()["reply"]
    assert "daftar" in pertama.lower()
    # Undangan hanya sekali; sesudah itu jangan menceramahi orang berulang kali.
    assert _kirim(client, "BBCA", nomor="6289999999999").json()["reply"] is None


def test_anggota_approved_dilayani(client, wa_bersih, monkeypatch):
    """Fokus tes ini: kontrol akses (anggota ter-approve dilayani, bukan
    disuruh mendaftar). Isi & format balasannya diuji terpisah di
    test_kode_emiten_membalas_rencana_trading_lengkap."""
    import web.app as app_module

    _daftarkan_approved()

    async def _plan_palsu(kode):
        return {"ticker_symbol": kode, "current_price": 9000, "daily_change_pct": 1.25,
                "confidence": 70, "sr": {}, "scenarios": {}, "account_size": 100_000_000,
                "target_risk_pct": 3.0}

    async def _rd_palsu(kode):
        return {"ticker": kode, "score": 78, "rating": "BAGUS", "recommendation": "BUY",
                "signal": "📈", "snapshot": [("Harga Terakhir", "Rp9.000")]}

    monkeypatch.setattr(app_module, "plan", _plan_palsu)
    monkeypatch.setattr(app_module, "_wa_report_data", _rd_palsu)
    balasan = _kirim(client, "bbca").json()["reply"]
    assert "daftar" not in balasan.lower()
    assert "BBCA" in balasan and "Rp9.000" in balasan


def test_pengirim_ber_lid_tetap_dikenali_lewat_kandidat_nomor(client, wa_bersih):
    """WhatsApp modern mengirim identitas peserta grup sebagai LID acak
    ("12345@lid"), bukan nomor telepon. Kalau hanya field itu yang dipakai,
    anggota yang sah tidak akan pernah cocok dengan akunnya -- dan karena
    ajakan mendaftar dijeda 6 jam, gejalanya jadi "bot diam saja"."""
    _daftarkan_approved("081234567890")

    res = client.post("/api/wa/command", json={
        "from": "199887766554433@lid",
        "candidates": ["199887766554433@lid", "6281234567890@s.whatsapp.net"],
        "text": "bantuan",
    }, headers={"Authorization": f"Bearer {SECRET}"})

    balasan = res.json()["reply"]
    assert balasan is not None and "daftar" not in balasan.lower()
    assert "Bot Ranah Saham" in balasan


def test_lid_tanpa_nomor_asli_tetap_diarahkan_mendaftar(client, wa_bersih):
    """Kalau memang tidak ada satu pun kandidat yang berupa nomor telepon,
    jangan diam-diam melayani siapa pun -- tetap perlakukan sebagai tamu."""
    _daftarkan_approved("081234567890")

    res = client.post("/api/wa/command", json={
        "from": "199887766554433@lid", "candidates": ["199887766554433@lid"], "text": "bantuan",
    }, headers={"Authorization": f"Bearer {SECRET}"})
    assert "daftar" in res.json()["reply"].lower()


def test_screener_memakai_minervini_dan_breakout_pindah_kata_kunci(client, wa_bersih, monkeypatch):
    """`screener` = saringan Minervini (permintaan user). Bentuk itemnya
    mengikuti core/screening_pro.py: {ticker, skor, harga, criteria_met,
    rs_score} -- BUKAN {ticker, price, signal} milik screener breakout."""
    import web.app as app_module

    async def _minervini_palsu():
        return {"items": [{"ticker": "DSSA", "skor": 78.5, "harga": 780,
                           "criteria_met": 7, "rs_score": 88, "rsi": 72.9,
                           "vol_ratio": 0.9, "macd_bullish": True}], "universe": 178}

    async def _breakout_palsu():
        return {"items": [{"ticker": "BBCA", "price": 9000, "volume": 1,
                           "signal": "STRONG BUY"}], "universe": 178}

    monkeypatch.setattr(app_module, "screenerpro", _minervini_palsu)
    monkeypatch.setattr(app_module, "screener", _breakout_palsu)
    _daftarkan_approved()

    minervini = _kirim(client, "screener").json()["reply"]
    assert "Minervini" in minervini
    assert "DSSA" in minervini and "7/8 kriteria" in minervini and "Rp780" in minervini

    app_module._wa_last_reply.clear()
    breakout = _kirim(client, "breakout").json()["reply"]
    assert "BBCA" in breakout and "Rp9.000" in breakout


def test_sinyal_menyaring_yang_masih_berjalan_dan_mengurut_confidence(client, wa_bersih, monkeypatch):
    """"Rekomendasi terbaik" harus: (a) hanya sinyal yang masih bisa
    ditindaklanjuti, (b) urut confidence, bukan urut waktu."""
    import web.app as app_module
    import core.signal_history as sh

    def _report_palsu():
        return {"stats": {"win_rate": 46.8}, "n_total": 77, "n_open": 2,
                "signals": [
                    {"kode": "SUDAH", "status": "TP_HIT", "entry_price": 400,
                     "confidence_score": 99, "source": "TOP_PICK"},
                    {"kode": "BIASA", "status": "OPEN", "entry_price": 500,
                     "tp_price": 550, "sl_price": 470, "confidence_score": 60,
                     "source": "MACD_CROSS"},
                    {"kode": "UNGGUL", "status": "PENDING_ENTRY", "entry_price": 800,
                     "tp_price": 880, "tp2_price": 960, "tp3_price": 1040,
                     "sl_price": 750, "confidence_score": 91, "tp_level_hit": 1,
                     "source": "NR7_52W", "pattern": "NR7 breakout"},
                ]}

    monkeypatch.setattr(sh, "get_signal_report", _report_palsu)
    _daftarkan_approved()

    hasil = _kirim(client, "sinyal").json()["reply"]
    assert "SUDAH" not in hasil, "sinyal yang sudah tutup tidak bisa ditindaklanjuti"
    # Dikelompokkan per EMITEN, bukan per baris sinyal.
    assert "2 emiten aktif" in hasil
    # Pertanyaan nyata anggota grup ("yg berjalan sm yg belum entry?") harus
    # terjawab oleh daftarnya sendiri, bukan perlu ditanyakan ke admin.
    assert "*Menunggu entry* (1)" in hasil
    assert "*Sedang berjalan* (1)" in hasil
    assert hasil.index("Menunggu entry") < hasil.index("Sedang berjalan")
    assert "TETAP di daftar selama posisinya belum ditutup" in hasil
    assert hasil.index("UNGGUL") < hasil.index("BIASA"), "harus urut confidence"
    # Yang bisa ditindaklanjuti sekarang disebut terpisah & lengkap.
    assert "*Sinyal terbaru*" in hasil
    assert "entry Rp800 · SL Rp750" in hasil
    assert "✅TP1 Rp880" in hasil                   # sudah tercapai
    assert "TP2 Rp960" in hasil and "TP3 Rp1.040" in hasil
    assert "46.8" in hasil or "46,8" in hasil


def test_sinyal_menyebut_puncak_sejak_muncul(client, wa_bersih, monkeypatch):
    """Keluhan berulang: "ERAA TAPG CSMI GIAA harusnya udah profit puluhan
    bahkan ratusan persen jika entry dari awal muncul sinyal". Selama
    angkanya tidak dipajang itu cuma terasa; dipajang, bisa diperiksa."""
    import web.app as app_module
    import core.signal_history as sh

    def _report_palsu():
        return {"stats": {"win_rate": 50.0}, "n_total": 1, "n_open": 1,
                "signals": [{"kode": "ERAA", "status": "OPEN", "entry_price": 400,
                             "tp_price": 440, "sl_price": 380, "confidence_score": 70,
                             "source": "TOP_PICK",
                             "entry_filled_at": "2026-07-01 09:00:00"}]}

    async def _puncak_palsu(signals):
        for s in signals:
            s.update({"mulai_dilacak": "2026-07-01", "hari_sejak_sinyal": 45,
                      "puncak_return_pct": 132.5, "puncak_date": "2026-08-20",
                      "sejak_sinyal_return_pct": 87.25,
                      "masuk_lagi": {
                          "pullback": {"entry": 745, "sl": 690, "risk_pct": 7.4, "tp1": 800},
                          "deep": {"entry": 700, "sl": 650, "risk_pct": 7.1, "tp1": 750}}})

    monkeypatch.setattr(sh, "get_signal_report", _report_palsu)
    monkeypatch.setattr(app_module, "_tempel_puncak_sejak_sinyal", _puncak_palsu)
    _daftarkan_approved()

    hasil = _kirim(client, "sinyal").json()["reply"]
    assert "Sejak 2026-07-01 di Rp400" in hasil
    assert "+87.2%" in hasil or "+87.3%" in hasil
    assert "Puncak *+132.5%*" in hasil and "2026-08-20" in hasil
    # Puncak terjauh ikut diringkas di atas, beserta penyangkalannya.
    assert "*Puncak terjauh sejak sinyal muncul*" in hasil
    assert "bukan hasil yang direalisasikan" in hasil
    # Entry aslinya sudah lewat jauh, jadi yang berguna level HARI INI --
    # disampaikan sebagai anjuran, bukan sekadar angka.
    assert "area terbaik Rp700 (SL Rp650)" in hasil
    assert "alternatif lebih dangkal Rp745" in hasil
    assert "dikejar" in hasil


def test_kode_emiten_membalas_rencana_trading_lengkap(client, wa_bersih, monkeypatch):
    """Balasan kode emiten = rencana trading (4 skenario + SL/TP + ukuran
    posisi), memakai angka dari /api/plan yang SAMA dipakai web."""
    import web.app as app_module

    def _skenario(entry, sl, risk_pct, pos, tp1, tp2, tp3):
        return {"entry": entry, "sl": sl, "risk_abs": entry - sl, "risk_pct": risk_pct,
                "position_size": pos, "position_value": pos * entry,
                "tp": {"tp1": tp1, "tp2": tp2, "tp3": tp3, "rr1": 1.0, "rr2": 2.0,
                       "rr3": 3.0, "tp1_pct": 8.1, "tp2_pct": 16.2, "tp3_pct": 24.3}}

    async def _plan_palsu(kode):
        return {
            "ticker_symbol": kode, "current_price": 780, "daily_change_pct": 0.65,
            "atr": 101, "rsi": 72.96, "rsi_status": "OVERBOUGHT ⚠️ (Hati-hati beli)",
            "trend": "BULLISH 🟢 (Moderate)", "vol_ratio": 0.9, "vol_status": "📊 NORMAL",
            "breakout_status": "❌ Belum breakout", "confidence": 60,
            "sr": {"S1": 737, "S2": 723, "S3": 700, "S4": 677,
                   "R1": 783, "R2": 797, "R3": 820, "R4": 843, "R5": 857},
            "scenarios": {
                "normal": _skenario(780, 717, 8.1, 47517, 843, 906, 969),
                "pullback": _skenario(737, 703, 4.7, 87274, 771, 806, 840),
                "deep": _skenario(723, 680, 6.0, 69550, 766, 809, 852),
                "breakout": _skenario(803, 717, 10.7, 34775, 889, 976, 1062),
            },
            "account_size": 100_000_000, "target_risk_pct": 3.0,
            "max_risk_amount": 3_000_000,
        }

    async def _rd_palsu(kode):
        return {"ticker": kode, "score": 68, "rating": "BAGUS", "recommendation": "BUY",
                "signal": "📈"}

    monkeypatch.setattr(app_module, "plan", _plan_palsu)
    monkeypatch.setattr(app_module, "_wa_report_data", _rd_palsu)
    monkeypatch.setattr(app_module, "_load_ticker_directory",
                        lambda: [{"kode": "DSSA", "nama": "Dian Swastatika"}])
    _daftarkan_approved()

    hasil = _kirim(client, "dssa").json()["reply"]
    # Verdict memakai kosakata web (STRONG BUY/BUY/HOLD/WATCH/AVOID).
    assert "*DSSA*" in hasil and "BUY" in hasil
    # Keempat skenario hadir lengkap dengan SL & ukuran posisi.
    for nama in ("Normal", "Pullback", "Deep", "Breakout"):
        assert nama in hasil
    assert "Rp717" in hasil
    # Skenario modal & ukuran posisi TIDAK ditampilkan: Rp100 juta itu contoh,
    # bukan modal pembacanya, dan "47.517 lembar" gampang terbaca sebagai
    # anjuran membeli sebanyak itu.
    assert "lembar" not in hasil and "modal" not in hasil.lower()
    assert "Rp843" in hasil and "Rp969" in hasil
    assert "Confidence: 60/100" in hasil
    assert "Support: 737 · 723" in hasil
    assert "bukan ajakan" in hasil.lower()


def test_kepemilikan_menyertakan_akumulasi_berulang_sebulan(client, wa_bersih, monkeypatch):
    """Aturan akumulasi berulang harus sama dengan panel di web: dikelompokkan
    per KODE, beberapa pelapor di HARI yang sama = satu hari, dan hanya yang
    muncul di >=2 sesi yang dianggap pola."""
    import web.app as app_module

    def _item(kode, nama, sebelum, sesudah):
        # "jenis" wajib ada: _split_x15_items hanya menghitung akumulasi dari
        # filing beli DENGAN perubahan > 0.
        return {"kode": kode, "nama": nama, "perusahaan": "", "jenis": "beli",
                "pct_sebelum": sebelum, "pct_setelah": sesudah,
                "perubahan": sesudah - sebelum, "pengendali": False,
                "jabatan": "", "tanggal": "2026-09-01"}

    async def _x15_palsu(days_back=0):
        # days_back 0 = HARI INI, 2 = dua hari lalu. Jadi urutan kronologisnya
        # hari 2 dulu, baru hari 0 -- kepemilikan MICE naik 5,40% -> 6,10%.
        # MICE: dibeli di 2 sesi berbeda -> pola berulang.
        # SEPI: cuma satu sesi, walau dua pelapor -> BUKAN pola.
        if days_back == 0:
            return [_item("MICE", "Budi", 5.4, 6.1), _item("SEPI", "Ani", 6.0, 6.2),
                    _item("SEPI", "Cici", 7.0, 7.1)]
        if days_back == 2:
            return [_item("MICE", "Sari", 5.0, 5.4)]
        return []

    monkeypatch.setattr(app_module, "_fetch_x15_today", _x15_palsu)
    monkeypatch.setattr(app_module, "_cache_get", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "_cache_set", lambda *a, **k: None)
    _daftarkan_approved()

    hasil = _kirim(client, "kepemilikan").json()["reply"]
    assert "Akumulasi berulang" in hasil
    # SEPI tetap SAH muncul di bagian "filing hari ini" -- yang diuji di sini
    # khusus bagian polanya, jadi pesannya dipotong dulu.
    blok = hasil.split("Akumulasi berulang", 1)[1]
    assert "MICE" in blok and "2 hari" in blok
    # Tiap pemegang punya barisnya sendiri, dengan pergerakan porsinya SENDIRI.
    assert "Budi" in blok and "Sari" in blok
    assert "5.40% → *6.10%*" in blok, "porsi Budi: sebelum filing terlamanya -> sesudah terbarunya"
    assert "5.00% → *5.40%*" in blok, "porsi Sari dihitung terpisah, tidak dicampur"
    assert "2 pemegang berbeda" not in blok, "nama pemegang harus disebut, bukan cuma jumlahnya"
    assert "SEPI" not in blok, "satu sesi (walau 2 pelapor) bukan pola berulang"


def test_daftar_ditampilkan_lengkap_tanpa_dipotong(client, wa_bersih, monkeypatch):
    """Permintaan user: "gausah make yg lainnya saya mau nya lengkap".
    Daftar TIDAK boleh dipangkas ke N teratas lalu ditutup "...dan sekian
    lainnya" -- semua baris harus ikut terkirim."""
    import web.app as app_module

    async def _minervini_palsu():
        return {"items": [{"ticker": f"SH{i:02d}", "skor": 90 - i, "harga": 1000 + i,
                           "criteria_met": 7, "rs_score": 80} for i in range(18)],
                "universe": 178}

    monkeypatch.setattr(app_module, "screenerpro", _minervini_palsu)
    _daftarkan_approved()

    hasil = _kirim(client, "screener").json()["reply"]
    for i in range(18):
        assert f"SH{i:02d}" in hasil, f"saham ke-{i} hilang dari daftar"
    assert "lainnya" not in hasil
    assert "18 saham" in hasil


def test_kode_emiten_menyertakan_grafik_dan_laporan_pdf(client, wa_bersih, monkeypatch):
    """Balasan kode emiten ikut membawa grafik; `laporan KODE` membawa PDF.
    Berkasnya TIDAK dikirim di JSON perintah -- hanya petunjuk supaya wa-bot
    mengambilnya dari /api/wa/media."""
    import web.app as app_module

    async def _plan_palsu(kode):
        return {"ticker_symbol": kode, "current_price": 535, "daily_change_pct": -0.93,
                "confidence": 40, "sr": {}, "scenarios": {}, "account_size": 100_000_000,
                "target_risk_pct": 3.0}

    async def _analisis_palsu(kode):
        return {"kode": kode, "recommendation": "WATCH", "signal": "👀", "score": 30.0}

    monkeypatch.setattr(app_module, "plan", _plan_palsu)
    monkeypatch.setattr(app_module, "_analyze_payload", _analisis_palsu)
    monkeypatch.setattr(app_module, "_load_ticker_directory",
                        lambda: [{"kode": "CYBR", "nama": "Cyber Network"}])
    _daftarkan_approved()

    data = _kirim(client, "cybr").json()
    assert data["media"]["kind"] == "image"
    assert data["media"]["jenis"] == "chart" and data["media"]["kode"] == "CYBR"
    assert "CYBR" in data["reply"]

    app_module._wa_last_reply.clear()
    lap = _kirim(client, "laporan cybr").json()
    assert lap["media"]["kind"] == "document"
    assert lap["media"]["filename"] == "Laporan_CYBR.pdf"
    assert lap["media"]["mimetype"] == "application/pdf"


def test_balasan_emiten_mengikuti_isi_pdf_laporan(client, wa_bersih, monkeypatch):
    """Permintaan user: isi balasan emiten mengikuti PDF Laporan Analisis --
    termasuk SMC dan berita. Datanya dirakit build_report_data() yang SAMA
    dipakai PDF, jadi tes ini memakai bentuk keluarannya yang sebenarnya."""
    import web.app as app_module

    async def _rd_palsu(kode):
        return {
            "ticker": kode, "score": 30, "rating": "CUKUP", "recommendation": "WATCH",
            "signal": "👀",
            "rec_badge": {"label": "SELL", "strength": "moderat",
                          "reason": "Teknikal melemah (skor 30/100)."},
            "ringkasan_eksekutif": "Gambaran teknikal saat ini seimbang/sideways.",
            "snapshot": [("Harga Terakhir", "Rp535"), ("RSI (14)", "25.0"),
                         ("VWAP Fair Value", "Rp565 (Discount, -5.4% vs VWAP)")],
            "indikator_status": [("Tren MA (5 vs 20)", "BEARISH", "MA5 < MA20"),
                                 ("RSI", "OVERSOLD", "25.0")],
            "bull_case": ["Momentum 5 hari positif (+0.9%)."],
            "bear_case": ["MA5 di bawah MA20 — momentum jangka pendek melemah."],
            "sintesis": "Gambaran relatif campur/netral.",
            "skenario": [{"nama": "BULLISH", "arah": "Seimbang",
                          "kondisi": "Break & tahan di atas MA20 (555)",
                          "target": "Menuju MA50 (572)"}],
            "smc": {"narasi": "Struktur pasar terakhir: Break of Structure (bearish).",
                    "n_bos": 7, "n_choch": 6, "last_struktur": "BOS bearish di Rp530",
                    "ob_bullish": 2, "ob_bearish": 3, "fvg_unfilled": 0,
                    "liq_high": 5, "liq_low": 0, "liq_unswept": 5},
            "konteks_ihsg": "Saham ini jauh lebih lemah dibanding IHSG.",
            "rs_text": "Saham -5.3% vs IHSG +4.5%.",
            "berita": [{"title": "CYBR menang tender proyek", "link": "https://contoh.id/a"}],
            "risiko": "Manajemen risiko bukan opsional. Batasi 1–2% per ide trading.",
        }

    async def _plan_palsu(kode):
        return {"ticker_symbol": kode, "current_price": 535, "breakout_status": "Belum breakout",
                "sr": {}, "scenarios": {"normal": {"entry": 535, "sl": 518, "risk_pct": 3.1,
                                                   "position_size": 176000, "position_value": 94160000,
                                                   "tp": {"tp1": 552, "tp2": 569, "tp3": 585,
                                                          "rr1": 1.0, "rr2": 2.0, "rr3": 3.0}}},
                "account_size": 100_000_000, "target_risk_pct": 3.0, "confidence": 40}

    monkeypatch.setattr(app_module, "_wa_report_data", _rd_palsu)
    monkeypatch.setattr(app_module, "plan", _plan_palsu)
    monkeypatch.setattr(app_module, "_load_ticker_directory",
                        lambda: [{"kode": "CYBR", "nama": "Cyber Network"}])
    _daftarkan_approved()

    hasil = _kirim(client, "cybr").json()["reply"]
    # Bagian-bagian yang ada di PDF harus ada juga di sini.
    assert "Skor 30/100 (CUKUP)" in hasil
    assert "Rekomendasi teknikal: *SELL* (moderat)" in hasil
    assert "Harga Terakhir: Rp535" in hasil and "VWAP Fair Value" in hasil
    assert "Tren MA (5 vs 20): *BEARISH* — MA5 < MA20" in hasil
    assert "Argumen bullish" in hasil and "Argumen bearish" in hasil
    assert "Smart Money Concepts" in hasil
    assert "7 BOS / 6 CHoCH" in hasil and "2 bullish / 3 bearish" in hasil
    assert "Konteks pasar (IHSG)" in hasil
    assert "CYBR menang tender proyek" in hasil and "https://contoh.id/a" in hasil
    assert "Manajemen risiko" in hasil
    # Rencana entry tetap ikut, tanpa mengulang judul emiten dua kali.
    assert "Rencana masuk" in hasil and "Entry Rp535" in hasil
    assert hasil.count("*CYBR*") == 1


def test_perintah_ihsg_memakai_analisis_yang_sama_dengan_web(client, wa_bersih, monkeypatch):
    """Bentuk payload mengikuti /api/ihsg yang sebenarnya, supaya bot &
    kartu IHSG di web tidak bisa bercerita beda."""
    import web.app as app_module

    async def _ihsg_palsu():
        return {"prediction": "SIDEWAYS", "action": "WAIT", "confidence": 62,
                "target_move": "+0.3% s/d -0.4%", "current_price": 7812.35,
                "daily_change": 0.41, "bullish_score": 4, "bearish_score": 3,
                "rsi": 71.9, "macd_signal": "bullish", "ma_trend": "MA5 > MA20",
                "bb_position": "atas", "volume_trend": "menurun",
                "fib_position": "0.618", "entry_zone": "7.750–7.780",
                "stop_loss": "7.690", "potensi_naik_pct": 2.4,
                "risiko_turun_pct": 1.8,
                "bandar": {"label": "Akumulasi", "sinyal": "positif"},
                "backtest": {"win_rate": 58.0, "base_rate": 51.0}}

    monkeypatch.setattr(app_module, "ihsg", _ihsg_palsu)
    _daftarkan_approved()

    jawaban = _kirim(client, "ihsg").json()
    hasil = jawaban["reply"]
    # IHSG ikut membawa chart 4-panel, seperti balasan kode emiten.
    assert jawaban["media"]["jenis"] == "chart_ihsg"
    assert jawaban["media"]["kind"] == "image"
    assert "IHSG — analisis pasar" in hasil
    assert "7.812,35" in hasil.replace(",", ",") or "7.812" in hasil
    assert "*SIDEWAYS*" in hasil and "WAIT" in hasil and "62%" in hasil
    assert "RSI: 71.9" in hasil and "MA5 > MA20" in hasil
    assert "Akumulasi" in hasil
    assert "7.750–7.780" in hasil and "7.690" in hasil
    assert "58.0% benar" in hasil and "dasar 51.0%" in hasil


def test_perintah_news_dan_news_per_emiten(client, wa_bersih, monkeypatch):
    import datetime as dt

    import web.app as app_module

    dipanggil = {}

    async def _news_palsu(keyword=None, limit=15):
        dipanggil["keyword"] = keyword
        return [{"title": "IHSG ditutup menguat", "link": "https://contoh.id/x",
                 "source": "Kontan", "_parsed_date": dt.datetime(2026, 9, 6, 9, 30)}]

    monkeypatch.setattr(app_module, "fetch_news", _news_palsu)
    monkeypatch.setattr(app_module, "_load_ticker_directory",
                        lambda: [{"kode": "BBCA", "nama": "Bank Central Asia"}])
    _daftarkan_approved()

    umum = _kirim(client, "news").json()["reply"]
    assert dipanggil["keyword"] is None, "tanpa kode = berita pasar, bukan disaring"
    assert "IHSG ditutup menguat" in umum
    assert "Kontan" in umum and "https://contoh.id/x" in umum

    app_module._wa_last_reply.clear()
    per_emiten = _kirim(client, "news bbca").json()["reply"]
    assert dipanggil["keyword"] == "BBCA"
    assert "*Berita BBCA*" in per_emiten


def test_endpoint_media_juga_gagal_tertutup(client, wa_bersih, monkeypatch):
    """Jalur /api/wa/ dikecualikan dari access_gate, jadi endpoint media pun
    WAJIB menolak tanpa secret yang benar -- kalau tidak, grafik & laporan
    bisa diambil siapa saja tanpa akun."""
    import web.app as app_module

    assert client.get("/api/wa/media?jenis=chart&kode=BBCA").status_code == 401
    assert client.get("/api/wa/media?jenis=chart&kode=BBCA",
                      headers={"Authorization": "Bearer salah"}).status_code == 401
    monkeypatch.setattr(app_module, "WA_BOT_SECRET", "")
    assert client.get("/api/wa/media?jenis=chart&kode=BBCA",
                      headers={"Authorization": "Bearer "}).status_code == 503


def test_sinyal_dibatasi_20_terbaik(client, wa_bersih, monkeypatch):
    """Daftar lain tampil utuh, tapi sinyal berjalan bisa puluhan dan tiap
    barisnya memuat entry/TP/SL. Dibatasi 20 TERATAS -- dan karena sudah
    terurut confidence, yang terpotong memang yang paling lemah."""
    import core.signal_history as sh

    def _report_palsu():
        return {"stats": {"win_rate": 50.0}, "n_total": 30, "n_open": 30,
                "signals": [{"kode": f"SG{i:02d}", "status": "OPEN", "entry_price": 100 + i,
                             "tp_price": 120, "sl_price": 90, "confidence_score": 100 - i,
                             "source": "TOP_PICK"} for i in range(30)]}

    monkeypatch.setattr(sh, "get_signal_report", _report_palsu)
    _daftarkan_approved()

    hasil = _kirim(client, "sinyal").json()["reply"]
    assert "20 teratas dari 30 emiten aktif" in hasil
    assert "SG00" in hasil and "SG19" in hasil     # confidence tertinggi ikut
    assert "SG20" not in hasil and "SG29" not in hasil  # yang terlemah dipotong


def test_kepemilikan_bisa_melacak_satu_emiten(client, wa_bersih, monkeypatch):
    import web.app as app_module

    async def _pemegang_palsu(kode):
        return {"kode": kode, "total": 2, "holders": [
            {"nama_tampil": "TUNGGAL JAYA INVESTAMA", "is_insider": False,
             "pct_sebelum": 39.76, "pct_setelah": 38.39, "perubahan": -1.37,
             "tanggal": "2026-09-01"},
            {"nama_tampil": "BUDI SANTOSO", "is_insider": True,
             "pct_sebelum": 1.0, "pct_setelah": 1.4, "perubahan": 0.4,
             "tanggal": "2026-08-28"},
        ]}

    monkeypatch.setattr(app_module, "api_pemegang_saham", _pemegang_palsu)
    monkeypatch.setattr(app_module, "_load_ticker_directory",
                        lambda: [{"kode": "IMPC", "nama": "Impack Pratama"}])
    _daftarkan_approved()

    hasil = _kirim(client, "kepemilikan impc").json()["reply"]
    assert "Kepemilikan IMPC" in hasil
    assert "TUNGGAL JAYA INVESTAMA" in hasil and "38.39%" in hasil
    assert "(insider)" in hasil
    # Kode polos tetap berarti rencana trading, bukan kepemilikan.
    assert "Rencana" not in hasil


def test_jeda_menahan_banjir_balasan_dari_satu_nomor(client, wa_bersih):
    _daftarkan_approved()
    assert _kirim(client, "bantuan").json()["reply"] is not None
    # Permintaan beruntun dari nomor yang sama didiamkan -- grup tidak banjir
    # dan pola kirimnya tidak terlihat seperti mesin.
    assert _kirim(client, "bantuan").json()["reply"] is None


def test_puncak_tidak_pernah_memicu_unduhan_dari_permintaan_user(monkeypatch):
    """Disiplin repo (scaling #1): permintaan USER tidak boleh memicu fetch
    Yahoo dingin. Riwayat ~200 kode itu mahal, jadi saat cache dingin
    laporan tetap dikirim tanpa kolom puncak -- yang mengisi cache adalah
    _cache_warmer_loop (boleh_fetch=True), bukan pengunjung halaman."""
    import asyncio

    import web.app as app_module

    ditembak = []

    async def _jangan_diunduh(*a, **k):
        ditembak.append(a)
        raise AssertionError("permintaan user memicu unduhan Yahoo")

    monkeypatch.setattr(app_module, "_cache_get", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "async_download_many", _jangan_diunduh)

    sinyal = [{"kode": "ERAA", "entry_price": 358.0, "status": "OPEN",
               "recorded_at": "2026-07-04 17:15:35"}]
    asyncio.run(app_module._tempel_puncak_sejak_sinyal(sinyal))

    assert ditembak == [], "permintaan user tidak boleh menembak Yahoo"
    assert "puncak_return_pct" not in sinyal[0]

    # Pemanas cache BOLEH mengunduh -- di situlah biayanya ditanggung.
    # (Kegagalan unduhannya sendiri sudah ditangani fungsi ini: dicatat ke
    # log lalu keluar, tidak merambat ke pemanggil -- jadi yang diperiksa
    # di sini "apakah dicoba", bukan "apakah melempar".)
    asyncio.run(app_module._tempel_puncak_sejak_sinyal(sinyal, boleh_fetch=True))
    assert ditembak, "pemanas cache justru tidak pernah mencoba mengunduh"


def test_sinyal_menyebut_yang_terbang_sesudah_sl_tanpa_mengklaimnya_untung(client, wa_bersih, monkeypatch):
    """User minta CSMI/GIAA yang kena SL lalu terbang ikut tampil di
    ringkasan. Ditampilkan -- TAPI tidak boleh dipajang seperti keuntungan:
    posisinya sudah ditutup rugi, jadi angka itu tidak pernah diraih siapa
    pun yang mengikuti aturannya."""
    import core.signal_history as sh
    import web.app as app_module

    def _report_palsu():
        return {"stats": {"win_rate": 50.0}, "n_total": 3, "n_open": 1,
                "signals": [
                    {"kode": "CSMI", "status": "SL_HIT", "entry_price": 200,
                     "puncak_return_pct": 88.4, "puncak_date": "2026-08-19",
                     "emiten_rekap": {"tanggal_pertama": "2026-07-05",
                                      "entry_pertama": 190.0, "dari_pertama_pct": 74.2}},
                    {"kode": "GIAA", "status": "SL_HIT", "entry_price": 55,
                     "puncak_return_pct": 31.0, "puncak_date": "2026-08-11"},
                    # Di bawah ambang, tidak perlu diramaikan.
                    {"kode": "SEPI", "status": "SL_HIT", "entry_price": 100,
                     "puncak_return_pct": 2.0},
                    {"kode": "JALAN", "status": "OPEN", "entry_price": 400,
                     "tp_price": 440, "sl_price": 380, "confidence_score": 70},
                ]}

    async def _lewati_pengayaan(*a, **k):
        return None

    monkeypatch.setattr(sh, "get_signal_report", _report_palsu)
    monkeypatch.setattr(app_module, "_tempel_puncak_sejak_sinyal", _lewati_pengayaan)
    _daftarkan_approved()

    hasil = _kirim(client, "sinyal").json()["reply"]
    assert "*Puncak terjauh sejak sinyal muncul* (2 emiten di atas +20%)" in hasil
    assert "CSMI" in hasil and "+88.4%" in hasil
    # GIAA (+31%) WAJIB ikut: dipotong oleh ambang persentase, bukan oleh
    # "N teratas" -- dengan potongan 5 teratas ia dulu hilang.
    assert "GIAA" in hasil and "+31.0%" in hasil
    assert hasil.index("CSMI") < hasil.index("GIAA"), "urut dari puncak tertinggi"
    # Wajib jujur: posisinya sudah ditutup rugi, angka itu tidak pernah diraih.
    assert "posisi sudah ditutup di SL" in hasil
    assert "bukan hasil yang direalisasikan" in hasil



def test_sinyal_memberi_anjuran_untuk_yang_sudah_punya_dan_yang_belum(client, wa_bersih, monkeypatch):
    """User minta bot bertindak seperti asisten: "ini misalkan udah naik
    hold jika yg sudah punya barang, atau jika belum bisa entry di berapa".
    Dua sisi itu keputusannya berbeda, jadi dijawab terpisah."""
    import core.signal_history as sh
    import web.app as app_module

    async def _lewati(*a, **k):
        return None

    def _report_palsu():
        return {"stats": {"win_rate": 50.0}, "n_total": 3, "n_open": 2,
                "signals": [
                    # Sudah TP1 dan harga sudah jalan jauh -> jangan kejar.
                    {"kode": "TERBANG", "status": "OPEN", "entry_price": 400,
                     "tp_price": 440, "sl_price": 380, "tp_level_hit": 1,
                     "confidence_score": 90, "sejak_sinyal_return_pct": 48.0,
                     "masuk_lagi": {"pullback": {"entry": 520, "sl": 480},
                                    "deep": {"entry": 500, "sl": 465}}},
                    # Masih dekat entry -> boleh masuk di sekitar entry.
                    {"kode": "DEKAT", "status": "OPEN", "entry_price": 1000,
                     "tp_price": 1080, "sl_price": 940, "confidence_score": 70,
                     "sejak_sinyal_return_pct": 1.2},
                    # Belum kena entry sama sekali.
                    {"kode": "NUNGGU", "status": "PENDING_ENTRY", "entry_price": 250,
                     "tp_price": 270, "sl_price": 235, "confidence_score": 60},
                ]}

    monkeypatch.setattr(sh, "get_signal_report", _report_palsu)
    monkeypatch.setattr(app_module, "_tempel_puncak_sejak_sinyal", _lewati)
    _daftarkan_approved()

    hasil = _kirim(client, "sinyal").json()["reply"]

    # Sudah TP1 -> stop digeser ke titik impas (tangga stop yang dipakai audit).
    assert "*Sudah punya*: HOLD, stop digeser ke titik impas (Rp400)" in hasil
    # Area masuk dipimpin yang PALING DALAM (Rp500), pullback jadi
    # alternatif -- diurutkan dari harganya, bukan dari namanya.
    assert "area terbaik Rp500 (SL Rp465)" in hasil
    assert "alternatif lebih dangkal Rp520" in hasil
    assert "jangan" in hasil and "dikejar" in hasil
    # Tidak ada level masuk lagi -> pakai entry sinyalnya, tapi tetap
    # "kalau harga menyentuh", bukan disuruh beli di harga sekarang.
    assert "masuk kalau harga menyentuh Rp1.000, SL Rp940" in hasil
    # Belum entry -> pasang beli, bukan disuruh HOLD.
    assert "*Belum punya*: pasang beli di Rp250, SL Rp235" in hasil
    assert "stop tetap Rp940" in hasil
