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

    async def _analisis_palsu(kode):
        return {"kode": kode, "recommendation": "BUY", "signal": "📈", "score": 78.0}

    monkeypatch.setattr(app_module, "plan", _plan_palsu)
    monkeypatch.setattr(app_module, "_analyze_payload", _analisis_palsu)
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
                     "tp_price": 880, "sl_price": 750, "confidence_score": 91,
                     "source": "NR7_52W", "pattern": "NR7 breakout"},
                ]}

    monkeypatch.setattr(sh, "get_signal_report", _report_palsu)
    _daftarkan_approved()

    hasil = _kirim(client, "sinyal").json()["reply"]
    assert "SUDAH" not in hasil, "sinyal yang sudah tutup tidak bisa ditindaklanjuti"
    assert hasil.index("UNGGUL") < hasil.index("BIASA"), "harus urut confidence"
    assert "Rp880" in hasil and "Rp750" in hasil  # TP & SL ikut ditampilkan
    assert "46.8" in hasil or "46,8" in hasil


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

    async def _analisis_palsu(kode):
        return {"kode": kode, "recommendation": "BUY", "signal": "📈", "score": 68.0,
                "grade": "B"}

    monkeypatch.setattr(app_module, "plan", _plan_palsu)
    monkeypatch.setattr(app_module, "_analyze_payload", _analisis_palsu)
    monkeypatch.setattr(app_module, "_load_ticker_directory",
                        lambda: [{"kode": "DSSA", "nama": "Dian Swastatika"}])
    _daftarkan_approved()

    hasil = _kirim(client, "dssa").json()["reply"]
    # Verdict memakai kosakata web (STRONG BUY/BUY/HOLD/WATCH/AVOID).
    assert "*DSSA*" in hasil and "BUY" in hasil
    # Keempat skenario hadir lengkap dengan SL & ukuran posisi.
    for nama in ("Normal", "Pullback", "Deep", "Breakout"):
        assert nama in hasil
    assert "Rp717" in hasil and "47.517 lembar" in hasil
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
    assert "2 pemegang berbeda" in blok  # Budi & Sari, bukan nama terakhir saja
    assert "5.40% → *6.10%*" in blok     # sesi terlama -> terbaru, bukan sebaliknya
    assert "SEPI" not in blok, "satu sesi (walau 2 pelapor) bukan pola berulang"


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
