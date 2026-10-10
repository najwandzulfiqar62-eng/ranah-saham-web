"""Kalkulator pemulihan, rights issue, dan dividen.

Ketiganya menjawab pertanyaan yang sering salah dihitung di kepala, dan
salahnya selalu ke arah yang sama: terlalu optimis. Karena itu yang diuji
paling ketat adalah justru kasus-kasus yang membuat orang keliru.
"""
import pytest

from core.kalkulator import dividen, harga_balik_modal, pemulihan, rights_issue


# ---------------------------------------------------------------------------
# Pemulihan -- rumus yang tidak simetris
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rugi,butuh", [
    (10, 11.11),
    (25, 33.33),
    (40, 66.67),     # kesalahan paling umum: orang mengira 40%
    (50, 100.0),
    (75, 300.0),
    (90, 900.0),
])
def test_kenaikan_yang_dibutuhkan_tidak_sama_dengan_ruginya(rugi, butuh):
    """Inti seluruh kalkulator ini. Rugi 40% butuh naik 66,7%, bukan 40% --
    dan kesalahannya membesar persis saat ia paling berbahaya."""
    assert pemulihan(rugi)["butuh_naik_pct"] == pytest.approx(butuh, abs=0.01)


def test_tidak_rugi_tidak_butuh_naik():
    assert pemulihan(0)["butuh_naik_pct"] == 0.0


def test_rugi_seratus_persen_memulangkan_None():
    """Modalnya habis; tidak ada kenaikan berhingga yang memulihkannya.
    Memulangkan angka besar akan menyiratkan ada jalan kembali."""
    assert pemulihan(100) is None
    assert pemulihan(150) is None


@pytest.mark.parametrize("rusak", [None, "", "abc", float("nan")])
def test_masukan_rusak_memulangkan_None(rusak):
    assert pemulihan(rusak) is None


def test_tanda_minus_diabaikan():
    """"Rugi -40%" dan "rugi 40%" maksudnya sama; orang mengetik keduanya."""
    assert pemulihan(-40)["butuh_naik_pct"] == pemulihan(40)["butuh_naik_pct"]


def test_posisi_yang_sudah_untung_dikatakan_untung():
    h = harga_balik_modal(harga_beli=1000, harga_kini=1200)
    assert h["sudah_untung"] is True and h["untung_pct"] == 20.0


def test_posisi_rugi_menyebut_harga_balik_modalnya():
    h = harga_balik_modal(harga_beli=1000, harga_kini=600)
    assert h["sudah_untung"] is False
    assert h["rugi_pct"] == 40.0
    assert h["butuh_naik_pct"] == pytest.approx(66.67, abs=0.01)
    assert h["harga_balik_modal"] == 1000


# ---------------------------------------------------------------------------
# Rights issue
# ---------------------------------------------------------------------------

def test_terp_dihitung_dengan_pembobotan_rasio():
    """2:1 dengan pasar 1.000 dan tebus 700 -> (2x1000 + 1x700)/3 = 900."""
    r = rights_issue(harga_pasar=1000, harga_tebus=700, rasio_lama=2, rasio_baru=1)
    assert r["terp"] == 900.0
    assert r["turun_ke_terp_pct"] == -10.0


def test_penurunan_ke_terp_bukan_kerugian_bagi_yang_menebus():
    """Nilainya PINDAH ke saham baru, tidak hilang. Yang rugi adalah yang
    TIDAK menebus -- dan itu yang jarang dihitung orang."""
    r = rights_issue(1000, 700, 2, 1)
    assert r["nilai_hak_per_saham_baru"] == 200.0      # TERP 900 - tebus 700
    assert r["dilusi_jika_tidak_tebus_pct"] == pytest.approx(33.33, abs=0.01)


def test_modal_tambahan_per_lot_lama_disebut():
    """Pertanyaan yang sebenarnya ditanyakan orang: "saya pegang 10 lot,
    harus siapkan uang berapa?"."""
    r = rights_issue(1000, 700, 2, 1)
    assert r["tebus_per_lot_lama"] == 35000            # 100 x (1/2) x 700


def test_tebus_di_atas_pasar_menghasilkan_hak_tak_bernilai():
    """Harga tebus di atas harga pasar: tidak ada alasan menebus, dan
    nilai haknya nol -- bukan negatif."""
    r = rights_issue(harga_pasar=500, harga_tebus=800, rasio_lama=1, rasio_baru=1)
    assert r["nilai_hak_per_saham_baru"] == 0.0


@pytest.mark.parametrize("args", [
    (0, 700, 2, 1), (1000, 0, 2, 1), (1000, 700, 0, 1), (1000, 700, 2, 0),
    (None, 700, 2, 1), ("x", 700, 2, 1),
])
def test_rights_issue_masukan_rusak(args):
    assert rights_issue(*args) is None


# ---------------------------------------------------------------------------
# Dividen
# ---------------------------------------------------------------------------

def test_yield_dihitung_dari_harga_sekarang():
    assert dividen(harga=2000, dividen_per_saham=100)["yield_pct"] == 5.0


def test_yield_terhadap_HARGA_BELI_ikut_dihitung():
    """Yang dipajang di mana-mana adalah yield bagi pembeli hari ini. Bagi
    yang sudah memegang, angka yang berarti adalah yield terhadap harga
    belinya sendiri -- dan keduanya bisa jauh berbeda."""
    d = dividen(harga=2000, dividen_per_saham=100, harga_beli=1000)
    assert d["yield_pct"] == 5.0
    assert d["yield_thd_harga_beli_pct"] == 10.0


def test_total_rupiah_dihitung_per_lot_seratus_lembar():
    d = dividen(harga=2000, dividen_per_saham=100, lot=5)
    assert d["total_rp"] == 50000


def test_dividen_nol_tetap_sah():
    """Emiten yang tidak membagi dividen adalah jawaban yang sah, bukan
    kesalahan masukan."""
    assert dividen(harga=2000, dividen_per_saham=0)["yield_pct"] == 0.0


@pytest.mark.parametrize("args", [(0, 100), (-5, 100), (2000, -1), (None, 100)])
def test_dividen_masukan_rusak(args):
    assert dividen(*args) is None


# ---------------------------------------------------------------------------
# Tampilannya di bot
# ---------------------------------------------------------------------------

def _k(kunci, *kata):
    from web.app import _wa_kalkulator
    return _wa_kalkulator(kunci, [kunci, *kata])


def test_desimal_ditulis_dengan_KOMA_bukan_titik():
    """"1.667x" di Indonesia terbaca seribu enam ratus, bukan satu koma
    enam. Titik di sini bukan sekadar kurang rapi -- ia mengubah angkanya
    jadi seribu kali lipat di kepala pembacanya."""
    teks = _k("pulih", "40")
    assert "66,67%" in teks and "1,667x" in teks
    assert "66.67" not in teks and "1.667x" not in teks


def test_titik_ribuan_pada_masukan_diterima():
    """Orang mengetik di HP: "1.000", "40%", "-40" semuanya muncul.
    Perintah yang menolak karena titik akan dibaca sebagai bot yang rusak."""
    assert _k("rights", "1.000", "700", "2", "1") == _k("rights", "1000", "700", "2", "1")
    assert "40%" in _k("pulih", "40%")
    assert "40%" in _k("pulih", "-40")


def test_tanpa_angka_menjelaskan_cara_pakainya():
    """Perintah yang dijawab diam atau error adalah bentuk kegagalan paling
    membingungkan -- orang tidak tahu salah ketik atau botnya mati."""
    for k in ("pulih", "rights", "dividen"):
        teks = _k(k)
        assert teks and "Ketik" in teks


def test_rugi_seratus_persen_dijawab_jujur():
    assert "modalnya habis" in _k("pulih", "100")


def test_kalkulator_mengembalikan_None_untuk_perintah_lain():
    """Supaya `pemulihan` (panel daftar saham) tidak dibajak kalkulator."""
    from web.app import _wa_kalkulator
    assert _wa_kalkulator("sinyal", ["sinyal"]) is None
    assert _wa_kalkulator("pemulihan", ["pemulihan"]) is None


def test_pulih_dengan_angka_TIDAK_dibajak_panel_pemulihan():
    """`pulih` dan `pemulihan` mirip. Tanpa urutan yang benar, `pulih 40`
    menjawab daftar saham -- jawaban yang benar untuk pertanyaan yang
    tidak diajukan."""
    assert "Balik modal" in _k("pulih", "40")


def test_rights_menyebut_dilusi_bagi_yang_TIDAK_menebus():
    """Yang jarang dihitung orang, dan yang justru merugikan."""
    teks = _k("rights", "1000", "700", "2", "1")
    assert "terdilusi" in teks and "33,33%" in teks


def test_dividen_menyebut_yield_terhadap_harga_beli():
    teks = _k("dividen", "2000", "100", "5", "1500")
    assert "harga BELIMU" in teks and "6,67%" in teks


def test_tercantum_di_menu_bantuan():
    from web.app import _WA_BANTUAN
    for k in ("pulih", "rights", "dividen"):
        assert k in _WA_BANTUAN
