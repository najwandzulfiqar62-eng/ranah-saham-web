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
    import web.app as app_module

    _daftarkan_approved()

    async def _analisis_palsu(kode):
        return {"kode": kode, "rating": "Bagus", "price": 9000.0, "change_1d": 1.25,
                "score": 78.0, "grade": "A", "recommendation": "Akumulasi bertahap",
                "rsi": 55.0, "vol_ratio": 1.4, "potensi_naik_pct": 8.0,
                "risiko_turun_pct": 3.0, "likuiditas": "Sangat likuid",
                "insight": "Tren naik didukung volume."}

    monkeypatch.setattr(app_module, "_analyze_payload", _analisis_palsu)
    balasan = _kirim(client, "bbca").json()["reply"]
    assert "BBCA" in balasan
    assert "9.000" in balasan  # harga diformat gaya Indonesia
    assert "bukan ajakan" in balasan.lower()


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


def test_screener_dan_sinyal_dibaca_dari_bentuk_data_yang_sebenarnya(client, wa_bersih, monkeypatch):
    """Formatter gampang membusuk diam-diam kalau bentuk payload berubah:
    /api/screener memberi {"items": [{ticker, price, signal}]} -- BUKAN
    {"hasil": [{kode, harga}]}. Tes ini memakai bentuk asli endpoint-nya."""
    import web.app as app_module

    async def _screener_palsu():
        return {"items": [{"ticker": "BBCA", "price": 9000, "volume": 12345678,
                           "signal": "STRONG BUY"}], "universe": 178}

    async def _sinyal_palsu():
        return {"stats": {"win_rate": 46.8}, "n_total": 77, "n_open": 5,
                "signals": [{"kode": "ELSA", "status": "TP_HIT", "entry_price": 400,
                             "direction": "BUY", "tp_level_hit": 2, "source": "TOP_PICK"}]}

    monkeypatch.setattr(app_module, "screener", _screener_palsu)
    monkeypatch.setattr(app_module, "signals_ringkas", _sinyal_palsu)
    _daftarkan_approved()

    hasil_screener = _kirim(client, "screener").json()["reply"]
    assert "BBCA" in hasil_screener and "9.000" in hasil_screener and "STRONG BUY" in hasil_screener

    app_module._wa_last_reply.clear()  # lewati jeda, ini permintaan kedua
    hasil_sinyal = _kirim(client, "sinyal").json()["reply"]
    assert "46.8" in hasil_sinyal or "46,8" in hasil_sinyal
    assert "ELSA" in hasil_sinyal and "TP tercapai" in hasil_sinyal
    assert "Top Pick" in hasil_sinyal


def test_jeda_menahan_banjir_balasan_dari_satu_nomor(client, wa_bersih):
    _daftarkan_approved()
    assert _kirim(client, "bantuan").json()["reply"] is not None
    # Permintaan beruntun dari nomor yang sama didiamkan -- grup tidak banjir
    # dan pola kirimnya tidak terlihat seperti mesin.
    assert _kirim(client, "bantuan").json()["reply"] is None
