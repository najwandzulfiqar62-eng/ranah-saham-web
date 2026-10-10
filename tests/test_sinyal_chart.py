"""Penjaga sinyal beli/jual yang digambar di chart.

GEJALA YANG MELAHIRKAN BERKAS INI: penulis menolak versi pertama --
"area buy dan sell kedeketan". Benar, dan sebabnya cacat nyata, bukan
selera: sinyalnya digambar sbg ZONA HARGA di support/resistance
terdekat, sehingga ketika harga terjepit di antara dua level berdekatan,
kedua garis nyaris menempel. Diukur pada IHSG saat itu: beli -1,7%,
jual +2,1%.

Sekarang sinyal adalah KEJADIAN bertanggal, dan berkas ini menjaga
sifat-sifat yang membuatnya tetap begitu.
"""
import inspect

import pandas as pd
import pytest

import web.app as app_module


def _df(vonis_urut):
    """DataFrame boneka; isinya tidak dipakai karena vonisnya dipalsukan.

    Panjangnya menentukan berapa bar yang dipindai.
    """
    n = len(vonis_urut) + 60
    idx = pd.bdate_range("2025-01-01", periods=n)
    return pd.DataFrame({"Open": [100.0] * n, "High": [101.0] * n,
                         "Low": [99.0] * n, "Close": [100.0] * n,
                         "Volume": [1e6] * n}, index=idx)


def _pakai_vonis(monkeypatch, urut):
    """Paksa _ringkasan_sinyal_teknikal mengikuti urutan vonis yang diberi.

    Dipanggil sekali per bar mulai dari indeks 60.
    """
    monkeypatch.setattr(app_module, "_cache_get", lambda k: None)
    monkeypatch.setattr(app_module, "_cache_set", lambda k, v, ttl=None: None)
    import core.ai_score as ai_mod
    monkeypatch.setattr(ai_mod, "calculate_ai_score_from_df",
                        lambda d: {"_n": len(d)})
    def _r(ai):
        i = ai["_n"] - 1 - 60
        return {"overall": urut[i] if 0 <= i < len(urut) else "NETRAL"}
    monkeypatch.setattr(app_module, "_ringkasan_sinyal_teknikal", _r)


# ---------------------------------------------------------------------------
# Aturan
# ---------------------------------------------------------------------------

def test_vonis_sehari_TIDAK_memicu_sinyal(monkeypatch):
    """Inti akurasinya. Terukur, BELI KUAT sehari cuma +1,11% sementara
    yang bertahan ke hari kedua +4,59% -- empat kali lipat. Menandai yang
    sehari berarti menggambar segitiga untuk kejadian yang terukur empat
    kali lebih lemah."""
    urut = ["NETRAL", "BELI KUAT", "NETRAL", "NETRAL"]
    _pakai_vonis(monkeypatch, urut)
    assert app_module._sinyal_chart_payload("X", _df(urut)) == []


def test_vonis_bertahan_dua_hari_memicu_sinyal(monkeypatch):
    urut = ["NETRAL", "BELI KUAT", "BELI KUAT", "NETRAL"]
    _pakai_vonis(monkeypatch, urut)
    out = app_module._sinyal_chart_payload("X", _df(urut))
    assert len(out) == 1
    assert out[0]["jenis"] == "BELI"
    assert out[0]["bertahan"] is True


def test_sisi_jual_memakai_aturan_yang_SAMA(monkeypatch):
    """Kalau sisi jual memakai syarat yang lebih longgar, segitiga merah
    akan muncul jauh lebih sering daripada hijau -- dan ketimpangan itu
    akan terbaca sbg pasar yang bearish, padahal cuma ambang yang
    berbeda."""
    urut = ["NETRAL", "JUAL KUAT", "JUAL KUAT", "NETRAL"]
    _pakai_vonis(monkeypatch, urut)
    out = app_module._sinyal_chart_payload("X", _df(urut))
    assert len(out) == 1 and out[0]["jenis"] == "JUAL"


def test_vonis_tengah_tidak_pernah_jadi_sinyal(monkeypatch):
    """Empat vonis tengah terukur berada dalam rentang +-0,25% dari
    pasar. Menggambar segitiga untuk mereka berarti menandai sesuatu yang
    tidak berbeda dari menebak."""
    for v in ("BELI", "CENDERUNG BELI", "NETRAL", "CENDERUNG JUAL", "JUAL"):
        urut = ["NETRAL", v, v, v, "NETRAL"]
        _pakai_vonis(monkeypatch, urut)
        assert app_module._sinyal_chart_payload("X", _df(urut)) == [], v


def test_vonis_panjang_dihitung_SATU_kejadian(monkeypatch):
    """Vonis yang bertahan dua minggu adalah SATU kejadian. Menandainya
    sepuluh kali adalah kesalahan yang sudah tiga kali menggelembungkan
    angka di proyek ini -- kali ini dalam bentuk gambar."""
    urut = ["NETRAL"] + ["BELI KUAT"] * 14 + ["NETRAL"]
    _pakai_vonis(monkeypatch, urut)
    out = app_module._sinyal_chart_payload("X", _df(urut))
    assert len(out) == 1, [x["t"] for x in out]


def test_sinyal_sejenis_diberi_jarak_minimum(monkeypatch):
    """Vonis yang berkedip di sekitar ambangnya melahirkan segitiga
    berdempetan -- yang menyiratkan beberapa kesempatan berbeda padahal
    itu satu keadaan yang sama. Inilah keluhan yang melahirkan berkas
    ini, dalam bentuknya yang lain."""
    kedip = ["BELI KUAT", "BELI KUAT", "NETRAL"] * 6
    urut = ["NETRAL"] + kedip
    _pakai_vonis(monkeypatch, urut)
    out = app_module._sinyal_chart_payload("X", _df(urut))
    # 6 kedipan, tapi jarak minimum 10 bar -> jauh lebih sedikit
    assert len(out) < 6, [x["t"] for x in out]
    assert app_module.JEDA_SINYAL_BAR >= 5


# ---------------------------------------------------------------------------
# Ongkos & keamanan
# ---------------------------------------------------------------------------

def test_sinyal_di_cache():
    """18,7 ms per bar x 170 bar = 3,2 detik. Chart menyegarkan dirinya
    tiap 30 detik; tanpa cache itu 3,2 detik CPU tiap setengah menit
    untuk SETIAP penonton."""
    src = inspect.getsource(app_module._sinyal_chart_payload)
    assert "_cache_get(" in src and "_cache_set(" in src
    assert "sinyalchart:v1:" in src, "kunci cache harus berversi"


def test_sinyal_dihitung_di_worker_thread():
    """Tiga detik di event loop membekukan SELURUH server, bukan cuma
    chart yang memintanya."""
    src = inspect.getsource(app_module.ohlc)
    assert "asyncio.to_thread(_sinyal_chart_payload" in src


def test_sinyal_payload_sinkron():
    assert not inspect.iscoroutinefunction(app_module._sinyal_chart_payload)


def test_data_cacat_tidak_meledak(monkeypatch):
    monkeypatch.setattr(app_module, "_cache_get", lambda k: None)
    monkeypatch.setattr(app_module, "_cache_set", lambda k, v, ttl=None: None)
    assert app_module._sinyal_chart_payload("X", pd.DataFrame()) == []


def test_angka_sinyal_TIDAK_memakai_tabel_vonis_sehari():
    """UNGGUL_VONIS mengukur vonis SEHARI. Memasangnya pada segitiga yang
    menandai aturan BERTAHAN berarti menempelkan label yang mengukur
    aturan berbeda dari yang digambar -- dan bedanya empat kali lipat."""
    src = inspect.getsource(app_module._sinyal_chart_payload)
    assert "UNGGUL_SINYAL_CHART" in src
    assert "UNGGUL_VONIS" not in src


def test_angka_belum_diukur_dikirim_None_bukan_nol():
    """Nol adalah klaim ("tidak ada keunggulan"); "belum diukur" bukan."""
    for v in app_module.UNGGUL_SINYAL_CHART.values():
        assert v is None or isinstance(v, (int, float))
    assert set(app_module.UNGGUL_SINYAL_CHART) == {"BELI KUAT", "JUAL KUAT"}


# ---------------------------------------------------------------------------
# Layar
# ---------------------------------------------------------------------------

def test_layar_tidak_menggambar_garis_beli_jual_duplikat():
    """CACAT NYATA: price-line "AREA BELI" dipasang di harga yang PERSIS
    SAMA dengan level "Support Terdekat" yang sudah tergambar -- dua
    garis bertumpuk di satu harga, yang membuat chart terlihat sesak dan
    ikut membuat penulis menyangka area beli & jualnya berdempetan."""
    js = open("web/static/app.js", encoding="utf-8").read()
    i = js.index("function _gambarRencana(")
    j = js.index("function _gambarSinyal(", i)
    blok = js[i:j]
    assert "AREA BELI" not in blok, "garis beli masih digambar dua kali"
    assert "AREA JUAL" not in blok
    # Penandanya pindah ke judul garis S/R.
    assert "_tandaRencana" in js


def test_layar_menggambar_sinyal_di_tanggalnya():
    """Bukan di bar terakhir sbg "area". Menempelkan panah di bar
    terakhir untuk harga yang belum tentu tersentuh menyiratkan kejadian
    yang tidak pernah ada."""
    js = open("web/static/app.js", encoding="utf-8").read()
    i = js.index("function _gambarSinyal(")
    blok = js[i:i + 1200]
    assert "time:x.t" in blok, "panah tidak ditempel di tanggal sinyalnya"
    assert "arrowUp" in blok and "arrowDown" in blok


def test_imbal_risiko_dihitung_dan_ditandai():
    """Dua garis berdempetan bukan rencana. Kalau imbalannya lebih kecil
    dari risikonya, ia harus DITANDAI, bukan disajikan seolah peluang."""
    from core.rencana_chart import susun
    lv = lambda h, t, n=3: {"harga": h, "tipe": t, "sentuh": n,
                            "terakhir": "2026-09-01", "pertama": "2026-05-01",
                            "kuat": n >= 3, "nama": "L"}
    # jual cuma sedikit di atas beli, stop jauh -> tidak layak
    r = susun(1000, [lv(995, "support"), lv(1005, "resistance")], [],
              atr_pct=5.0)
    assert r["imbal_risiko"] is not None
    assert r["terlalu_sempit"] is True
    # jarak wajar -> layak
    r2 = susun(1000, [lv(980, "support"), lv(970, "support"),
                      lv(1100, "resistance")], [])
    assert r2["terlalu_sempit"] is False
