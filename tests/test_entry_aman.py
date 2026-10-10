"""Harga beli aman -- dan ongkos dari menunggunya.

DIUKUR 11 Okt 2026. Order limit di bawah penutupan, ditunggu 10 hari
bursa, ditahan 20 hari. Dua universe, dan bentuknya IDENTIK di keduanya:

    178 emiten likuid            793 emiten (seluruh IDX)
    diskon  naik   HARAPAN       diskon  naik   HARAPAN
      0%   44,4%   +1,32%          0%   46,3%   +3,39%
      3%   50,2%   +0,97%          3%   51,9%   +2,43%
      8%   54,7%   +0,77%          8%   53,6%   +1,50%

"AMAN" DAN "MENGUNTUNGKAN" BUKAN HAL YANG SAMA, dan itu seluruh isinya.
Menunggu diskon menaikkan win rate sepuluh poin, tapi menurunkan harapan
terus-menerus -- order yang tidak pernah kena berarti peluang yang hilang
sepenuhnya, dan itu dihitung nol.

Berkas ini menguji bahwa pertukaran itu tetap terlihat, tidak diringkas
jadi satu "harga rekomendasi" yang menyembunyikannya.
"""
import pytest

from core.entry_aman import (AMBANG_LIKUID, TANGGA_LIKUID, TANGGA_SEMUA,
                             paling_aman, paling_untung, saran_cicil,
                             tangga_beli)


# ---------------------------------------------------------------------------
# Pertukarannya harus tetap terlihat
# ---------------------------------------------------------------------------

def test_paling_aman_dan_paling_untung_BUKAN_tingkat_yang_sama():
    """Inti seluruh modul ini. Kalau keduanya pernah jadi tingkat yang
    sama, pertukarannya hilang dan "harga aman" boleh diringkas jadi satu
    angka -- tapi datanya bilang sebaliknya."""
    t = tangga_beli(1000.0)
    aman, untung = paling_aman(t), paling_untung(t)
    assert aman.diskon_pct != untung.diskon_pct
    assert aman.naik_pct > untung.naik_pct        # lebih sering benar
    assert untung.harapan_pct > aman.harapan_pct  # tapi lebih menghasilkan


def test_harapan_TURUN_seiring_diskon_makin_dalam():
    """Monoton di kedua universe. Kalau suatu hari ada tabel baru yang
    melanggar ini, ia harus diperiksa sebelum dipercaya -- bukan sesudah
    dipasang."""
    for tabel in (TANGGA_LIKUID, TANGGA_SEMUA):
        harapan = [h for _, _, _, _, h in tabel]
        assert harapan == sorted(harapan, reverse=True), tabel[0]


def test_win_rate_NAIK_seiring_diskon_makin_dalam():
    """Arah yang berlawanan dengan harapan, dan justru itu sebabnya
    keduanya harus ditampilkan bersama."""
    for tabel in (TANGGA_LIKUID, TANGGA_SEMUA):
        naik = [n for _, _, _, n, _ in tabel]
        assert naik[0] < naik[-1]


def test_peluang_terisi_turun_seiring_diskon():
    for tabel in (TANGGA_LIKUID, TANGGA_SEMUA):
        terisi = [t for _, t, _, _, _ in tabel]
        assert terisi == sorted(terisi, reverse=True)


# ---------------------------------------------------------------------------
# Tangga dipilih menurut likuiditas
# ---------------------------------------------------------------------------

def test_saham_tidak_likuid_memakai_tangganya_sendiri():
    """Saham sepi menunjukkan hasil jauh lebih besar (+3,49% vs +1,37%),
    tapi sebagian besar itu selip harga yang tidak terukur. Memakai angka
    saham likuid untuknya akan MENGECILKAN hasil yang tampak; memakai
    angka seluruh universe untuk saham likuid akan MEMBESARKANNYA."""
    likuid = tangga_beli(1000.0, nilai_harian=AMBANG_LIKUID * 5)
    sepi = tangga_beli(1000.0, nilai_harian=AMBANG_LIKUID / 10)
    assert likuid[0].harapan_pct == 1.32
    assert sepi[0].harapan_pct == 3.39


def test_tanpa_keterangan_likuiditas_memakai_angka_yang_konservatif():
    """Bawaan harus yang paling mungkin bisa ditepati, bukan yang paling
    enak dibaca."""
    assert tangga_beli(1000.0)[0].harapan_pct == TANGGA_LIKUID[0][4]


# ---------------------------------------------------------------------------
# Harga dan pemangkasan
# ---------------------------------------------------------------------------

def test_harga_dihitung_dari_diskonnya():
    t = tangga_beli(1000.0)
    assert t[0].harga == 1000
    assert [x.harga for x in t if x.diskon_pct == 3.0][0] == 970


def test_diskon_yang_tenggelam_di_derau_dibuang():
    """Diskon 1% pada saham yang bergerak 6% sehari bukan "menunggu" --
    itu beli pasar dengan langkah tambahan, dan menampilkannya sebagai
    pilihan yang berbeda itu menyesatkan."""
    t = tangga_beli(1000.0, atr_pct=6.0)      # batas bawah 3%
    diskon = [x.diskon_pct for x in t]
    assert 1.0 not in diskon and 2.0 not in diskon
    assert 0.0 in diskon and 3.0 in diskon


def test_saham_tenang_tetap_dapat_tingkat_rapat():
    t = tangga_beli(1000.0, atr_pct=1.0)
    assert 1.0 in [x.diskon_pct for x in t]


@pytest.mark.parametrize("harga", [0, -5, None, "x"])
def test_harga_tidak_sah_memulangkan_kosong(harga):
    assert tangga_beli(harga) == []


# ---------------------------------------------------------------------------
# Saran cicil
# ---------------------------------------------------------------------------

def test_cicil_memakai_harga_pasar_DAN_satu_diskon():
    """Menaruh seluruh posisi di pasar memberi harapan tertinggi tapi win
    rate terendah; seluruhnya di diskon sebaliknya. Membaginya mengambil
    sebagian dari keduanya, dan membuat hasilnya tidak bergantung pada
    tebakan apakah harga akan turun dulu."""
    c = saran_cicil(1000.0)
    assert c["harga_pasar"] == 1000
    assert c["harga_cicil"] is not None and c["harga_cicil"] < 1000
    assert c["naik_cicil_pct"] > c["naik_pasar_pct"]


def test_cicil_tidak_memilih_diskon_yang_jarang_terisi():
    """Bagian kedua yang cuma kena 27% dari waktu lebih sering TIDAK
    terbeli daripada terbeli -- itu bukan cicilan, itu lotere."""
    c = saran_cicil(1000.0)
    assert c["peluang_cicil_terisi_pct"] >= 50


def test_cicil_harga_tidak_sah_memulangkan_None():
    assert saran_cicil(0) is None
    assert saran_cicil(None) is None


# ---------------------------------------------------------------------------
# Payload yang dikirim ke layar
# ---------------------------------------------------------------------------

def test_payload_selalu_mengirim_KEDUA_angka():
    """Meringkasnya jadi satu "harga rekomendasi" akan menyembunyikan
    pertukaran yang justru harus dilihat orang."""
    from web.app import _beli_aman_payload

    p = _beli_aman_payload(450.0, 3.2, 5e9)
    assert p["paling_aman"]["harga"] != p["paling_untung"]["harga"]
    for t in p["tangga"]:
        assert "naik_pct" in t and "harapan_pct" in t and "terisi_pct" in t


def test_payload_tahan_masukan_rusak():
    from web.app import _beli_aman_payload

    assert _beli_aman_payload(0, None, None) is None
    assert _beli_aman_payload(None, None, None) is None


def test_konsensus_emiten_tanpa_liputan_memulangkan_None(monkeypatch):
    """Analis sekuritas hanya meliput saham besar. Emiten tanpa liputan
    harus menjawab None, BUKAN angka kosong yang terbaca seperti
    "target nol"."""
    import web.app as app_module

    monkeypatch.setattr(app_module, "_cache_get", lambda k: None)
    monkeypatch.setattr(app_module, "_cache_set", lambda k, v, ttl=None: None)

    class _T:
        def __init__(self, *a, **k): pass
        @property
        def info(self): return {"currentPrice": 468.0, "recommendationKey": "none"}

    import yfinance
    monkeypatch.setattr(yfinance, "Ticker", _T)
    assert app_module._konsensus_analis("ASLI") is None


def test_konsensus_menyebut_jumlah_analisnya(monkeypatch):
    """Angkanya AKAN berbeda dari aplikasi lain -- Stockbit menyebut MTEL
    avg 644 dari 31 rekomendasi, Yahoo 631 dari 15. Keduanya bukan salah;
    mereka menghitung dari panel analis yang berbeda. Jumlah analisnya
    ditampilkan supaya perbedaan itu terlihat, bukan jadi misteri."""
    import web.app as app_module

    monkeypatch.setattr(app_module, "_cache_get", lambda k: None)
    monkeypatch.setattr(app_module, "_cache_set", lambda k, v, ttl=None: None)

    class _T:
        def __init__(self, *a, **k): pass
        @property
        def info(self):
            return {"targetMeanPrice": 630.67, "targetHighPrice": 800.0,
                    "targetLowPrice": 400.0, "numberOfAnalystOpinions": 15,
                    "recommendationKey": "buy", "currentPrice": 450.0}

    import yfinance
    monkeypatch.setattr(yfinance, "Ticker", _T)
    k = app_module._konsensus_analis("MTEL")
    assert k["jumlah_analis"] == 15
    assert k["target_rata2"] == 631
    assert k["potensi_pct"] == 40.1
    assert k["sumber"] == "Yahoo Finance"
