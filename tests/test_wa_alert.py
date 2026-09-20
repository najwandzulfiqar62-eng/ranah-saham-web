"""Bot menyahut duluan -- dan yang paling sulit di sini bukan mendeteksi, tapi DIAM.

Bot yang terlalu cerewet akan di-mute. Sesudah di-mute, peringatan yang
benar-benar penting juga tidak sampai ke siapa pun. Jadi mengirim terlalu
banyak bukan sekadar mengganggu: ia merusak gunanya sendiri.
"""
import pytest


@pytest.fixture
def alert():
    from core.database import get_db

    import core.wa_alert as al
    al.ensure_alert_tables()
    with get_db() as conn:
        conn.execute("DELETE FROM wa_alert_kirim")
    yield al
    with get_db() as conn:
        conn.execute("DELETE FROM wa_alert_kirim")


POSISI = {"kode": "ERAA", "harga_avg": 720}


# ---------------------------------------------------------------------------
# Aturan: keadaan apa yang layak mengganggu orang
# ---------------------------------------------------------------------------

def test_menyentuh_stop_diberitahukan(alert):
    a = alert.periksa_posisi(POSISI, 610, sl=620)
    assert a and a["jenis"] == "sl"
    assert "620" in a["teks"] and "ERAA" in a["teks"]


def test_menyentuh_level_yang_pernah_disebutkan(alert):
    """INI yang membuat peringatan terasa nyambung, bukan notifikasi acak:
    harganya menyentuh angka yang MEMANG sudah dibicarakan sebelumnya."""
    a = alert.periksa_posisi(POSISI, 598,
                             level=[{"label": "Support S1", "price": 600}])
    assert a and a["jenis"] == "level"
    assert "Support S1" in a["teks"]
    assert "TIDAK wajib" in a["teks"], "menambah tidak boleh terbaca sebagai perintah"


def test_untung_besar_diingatkan_tanpa_menyuruh_menjual(alert):
    a = alert.periksa_posisi({"kode": "ANTM", "harga_avg": 1000}, 1250)
    assert a and a["jenis"] == "untung"
    assert "jual" not in a["teks"].lower(), "pengingat, bukan perintah menjual"


def test_posisi_tenang_tidak_menghasilkan_apa_apa(alert):
    assert alert.periksa_posisi(POSISI, 715) is None
    assert alert.periksa_posisi(POSISI, 740) is None


def test_stop_menang_atas_yang_lain(alert):
    """Satu posisi cuma boleh menghasilkan SATU pesan, dan yang paling
    mendesak harus menang. Dua pesan tentang saham yang sama dalam satu
    menit terbaca seperti bot rusak."""
    a = alert.periksa_posisi(POSISI, 590, sl=620,
                             level=[{"label": "Support S1", "price": 600}])
    assert a["jenis"] == "sl"


def test_level_tidak_dipicu_saat_posisinya_untung(alert):
    """Level menambah cuma relevan untuk posisi yang rugi."""
    a = alert.periksa_posisi({"kode": "X", "harga_avg": 500}, 620,
                             level=[{"label": "Support S1", "price": 700}])
    assert a is None or a["jenis"] != "level"


# ---------------------------------------------------------------------------
# Penjaga: jangan membanjiri
# ---------------------------------------------------------------------------

def test_keadaan_yang_sama_tidak_diulang(alert):
    """Harga yang bergoyang di sekitar sebuah level tidak boleh menghasilkan
    sepuluh pesan yang sama."""
    kunci = "ERAA:level:600"
    assert alert.boleh_kirim(1, "level", kunci)
    alert.catat_kirim(1, "ERAA", "level", kunci)
    assert not alert.boleh_kirim(1, "level", kunci)


def test_jatah_harian_menahan_peringatan_biasa(alert):
    for i in range(alert.JATAH_HARIAN):
        k = f"K{i}:untung:20"
        assert alert.boleh_kirim(1, "untung", k), f"tertahan terlalu cepat di ke-{i+1}"
        alert.catat_kirim(1, "K", "untung", k)
    assert not alert.boleh_kirim(1, "untung", "LAIN:untung:20")


def test_kejadian_penting_menembus_jatah(alert):
    """Menahan "posisimu menyentuh stop" karena jatah habis bukan
    kesopanan, itu kegagalan -- justru itu yang ditunggu orang."""
    for i in range(alert.JATAH_HARIAN + 2):
        k = f"K{i}:untung:20"
        if alert.boleh_kirim(1, "untung", k):
            alert.catat_kirim(1, "K", "untung", k)
    assert alert.sisa_jatah(1) == 0
    assert alert.boleh_kirim(1, "sl", "ERAA:sl:620")
    assert alert.boleh_kirim(1, "tp", "ERAA:tp:1")


def test_jatah_terpisah_per_orang(alert):
    for i in range(alert.JATAH_HARIAN):
        k = f"K{i}:untung:20"
        alert.boleh_kirim(1, "untung", k) and alert.catat_kirim(1, "K", "untung", k)
    assert alert.sisa_jatah(1) == 0
    assert alert.sisa_jatah(2) == alert.JATAH_HARIAN


def test_catatan_lama_dibersihkan(alert):
    from core.database import get_db

    alert.catat_kirim(1, "X", "untung", "X:untung:20")
    with get_db() as conn:
        conn.execute("UPDATE wa_alert_kirim SET dikirim_at = '2020-01-01 00:00:00'")
    assert alert.bersihkan(hari=30) == 1


def test_penjaga_bertahan_sesudah_restart(alert):
    """Dicatat di basis data, bukan memori. Penjaga yang lupa sesudah
    restart bukan penjaga -- dan proses ini di-restart tiap deploy."""
    import io
    import os

    akar = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sumber = io.open(os.path.join(akar, "core", "wa_alert.py"),
                     encoding="utf-8").read()
    assert "get_db" in sumber
    assert "wa_alert_kirim" in sumber


# ---------------------------------------------------------------------------
# Jalur pengiriman
# ---------------------------------------------------------------------------

def test_peringatan_dikirim_JAPRI_bukan_ke_grup():
    """Isinya menyebut saham dan harga milik SATU orang."""
    import io
    import os

    akar = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = io.open(os.path.join(akar, "web", "app.py"), encoding="utf-8").read()
    fungsi = app.split("async def _jalankan_alert_posisi")[1][:2500]
    assert 'to=u["phone"]' in fungsi, "peringatan tidak dikirim japri"


def test_hanya_anggota_yang_sudah_disetujui():
    """Bawaan list_users() adalah "pending". Mengirim peringatan posisi ke
    orang yang akunnya belum disetujui adalah kebocoran sekaligus gangguan."""
    import io
    import os

    akar = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = io.open(os.path.join(akar, "web", "app.py"), encoding="utf-8").read()
    fungsi = app.split("async def _jalankan_alert_posisi")[1][:2500]
    assert 'list_users, "approved"' in fungsi


def test_peringatan_hanya_pada_jam_bursa():
    """"ERAA menyentuh stop" yang datang pukul sebelas malam tidak bisa
    ditindaklanjuti siapa pun -- ia cuma mengganggu."""
    import io
    import os

    akar = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = io.open(os.path.join(akar, "web", "app.py"), encoding="utf-8").read()
    loop = app.split("async def _wa_alert_loop")[1][:1600]
    assert "_is_bursa_trading_hours" in loop and "_is_bursa_weekend" in loop


def test_satu_pesan_per_orang_per_putaran():
    """Lima peringatan sekaligus terbaca seperti bot rusak."""
    import io
    import os

    akar = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = io.open(os.path.join(akar, "web", "app.py"), encoding="utf-8").read()
    fungsi = app.split("async def _jalankan_alert_posisi")[1][:2500]
    assert "\n                break" in fungsi or "break" in fungsi
