"""Ringkasan Sinyal Teknikal: tujuh suara, dan angka yang mengukurnya.

PERUBAHAN BESAR 11 Okt 2026, sesudah penulis menegaskan angka skripsinya
sudah final. Dua hal diubah sekaligus:

  1. SUARA RSI DIBALIK. Versi lama menghitung RSI rendah "beli" dan RSI
     tinggi "jual". Terukur di 793 emiten, 2 tahun, dua paruh waktu, dan
     khusus saat harga di atas MA50 -- monoton di semua potongan:

         RSI 30-45  unggul  -1,56%    <- dulu dihitung BELI
         RSI 55-70  unggul  +0,89%
         RSI 70-80  unggul  +4,67%    <- dulu dihitung JUAL
         RSI >=80   unggul +14,10%    <- dulu dihitung JUAL

     Saham kuat cenderung tetap kuat; RSI tinggi itu tanda momentum,
     bukan tanda jenuh.

  2. SUARA KETUJUH: TREN. Keenam suara lama semuanya momentum, osilator,
     atau volume -- tidak satu pun mengukur tren, padahal itu premis
     utama bukunya. Terukur ia suara TERKUAT (+1,35%, melewati MACD
     +1,27%).

Vonisnya diukur ULANG sesudah perubahan (23.755 episode), dan angka lama
TIDAK dipertahankan: ia mengukur mesin vonis yang sudah tidak ada.
"""
import pytest

import web.app as app_module


def _ai(rsi=50, macd=False, vol=1.0, score=50, c1=0.0, c5=0.0,
        price=1000.0, ma50=1000.0, ma200=1000.0):
    return {"rsi": rsi, "macd_bullish": macd, "vol_ratio": vol,
            "score": score, "change_1d": c1, "change_5d": c5,
            "price": price, "ma50": ma50, "ma200": ma200}


def _r(**k):
    return app_module._ringkasan_sinyal_teknikal(_ai(**k))


def _semua_beli():
    return _ai(rsi=75, macd=True, vol=1.5, score=70, c1=2.0, c5=5.0,
               price=1200.0, ma50=1000.0, ma200=900.0)


def _semua_jual():
    return _ai(rsi=35, macd=False, vol=0.3, score=30, c1=-2.0, c5=-5.0,
               price=800.0, ma50=1000.0, ma200=1100.0)


# ---------------------------------------------------------------------------
# RSI yang sudah dibalik
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rsi,arah", [
    (85, "beli"),    # terukur +14,10% -- dulu dihitung JUAL
    (75, "beli"),    # terukur  +4,67% -- dulu dihitung JUAL
    (60, "beli"),    # terukur  +0,89%
    (50, None),      # terukur  -0,93% -> netral
    (40, "jual"),    # terukur  -1,56% -- dulu dihitung BELI
    (25, "jual"),
])
def test_arah_suara_RSI_mengikuti_pengukuran(rsi, arah):
    """Ambangnya dipasang di titik ukur tempat keunggulannya berganti
    tanda (55), bukan di angka bulat yang kedengaran enak.

    Diuji dengan suara lain dibuat netral semua, jadi apa pun yang
    tercatat sebagai beli/jual pasti datang dari RSI."""
    r = app_module._ringkasan_sinyal_teknikal(
        {"rsi": rsi, "macd_bullish": None, "vol_ratio": 0.8, "score": 50,
         "change_1d": 0.0, "change_5d": 0.0,
         "price": 1050.0, "ma50": 1000.0, "ma200": 1100.0})
    # MACD selalu memilih (tidak punya netral), jadi ia dikurangi.
    beli = r["beli"] - (1 if r["beli"] and False else 0)
    if arah == "beli":
        assert r["beli"] >= 1
    elif arah == "jual":
        assert r["jual"] >= 2      # RSI + MACD(None -> jual)
    else:
        assert r["beli"] == 0


def test_pita_RSI_di_bawah_30_TIDAK_dibuatkan_pengecualian():
    """Pita <30 terukur sedikit positif (+0,47%) -- pantulan oversold yang
    sungguhan, tapi jauh lebih lemah daripada efek momentumnya. Aturan
    khusus untuk satu pita sempit itu pas-pasan dengan data, bukan
    temuan."""
    assert _r(rsi=25)["jual"] >= 1


# ---------------------------------------------------------------------------
# Suara TREN
# ---------------------------------------------------------------------------

def test_tren_jadi_suara_ketujuh():
    """Saham bisa mendapat BELI KUAT sambil jauh di bawah MA200 -- itu
    yang mungkin terjadi sebelum suara ini ada."""
    r = app_module._ringkasan_sinyal_teknikal(_semua_beli())
    assert r["beli"] + r["jual"] + r["netral"] == 7


def test_harga_di_atas_KEDUA_MA_bersuara_beli():
    naik = app_module._ringkasan_sinyal_teknikal(
        _ai(price=1200.0, ma50=1000.0, ma200=900.0))
    turun = app_module._ringkasan_sinyal_teknikal(
        _ai(price=800.0, ma50=1000.0, ma200=1100.0))
    assert naik["beli"] > turun["beli"]
    assert turun["jual"] > naik["jual"]


def test_harga_di_antara_kedua_MA_bersuara_netral():
    """Arah yang belum jelas bukan beli dan bukan jual. Memaksanya memilih
    menambah suara yang isinya tebakan."""
    antara = app_module._ringkasan_sinyal_teknikal(
        _ai(price=1050.0, ma50=1000.0, ma200=1100.0))
    atas = app_module._ringkasan_sinyal_teknikal(
        _ai(price=1200.0, ma50=1000.0, ma200=900.0))
    assert antara["netral"] > atas["netral"]


def test_MA_tidak_tersedia_bersuara_netral_bukan_meledak():
    """Saham baru IPO belum punya MA200. Sinyalnya tetap layak dinilai
    dengan enam suara lain daripada hilang sama sekali."""
    r = app_module._ringkasan_sinyal_teknikal(
        {"rsi": 60, "macd_bullish": True, "vol_ratio": 1.5, "score": 70,
         "change_1d": 2.0, "change_5d": 5.0})
    assert r["beli"] + r["jual"] + r["netral"] == 7


# ---------------------------------------------------------------------------
# Ambang vonis, diskalakan ke tujuh suara
# ---------------------------------------------------------------------------

def test_tujuh_suara_searah_jadi_vonis_kuat():
    assert app_module._ringkasan_sinyal_teknikal(_semua_beli())["overall"] == "BELI KUAT"
    assert app_module._ringkasan_sinyal_teknikal(_semua_jual())["overall"] == "JUAL KUAT"


def test_ambang_diskalakan_bukan_dilonggarkan():
    """5 dari 6 (83%) menjadi 6 dari 7 (86%). Membiarkan 5/4 dengan tujuh
    suara akan melonggarkan vonisnya tanpa ada yang memutuskan begitu."""
    import inspect

    src = inspect.getsource(app_module._ringkasan_sinyal_teknikal)
    assert "beli >= 6" in src and "beli >= 5" in src
    assert "jual >= 6" in src and "jual >= 5" in src


# ---------------------------------------------------------------------------
# Angka terukur -- vonis BARU
# ---------------------------------------------------------------------------

def test_angka_keunggulan_sesuai_pengukuran_vonis_BARU():
    """Angka lama (+1,30 / -0,66) mengukur mesin vonis yang sudah tidak
    ada. Memajangnya berarti memajang angka yang tidak menggambarkan apa
    pun."""
    assert app_module.UNGGUL_VONIS["BELI KUAT"] == 1.11
    assert app_module.UNGGUL_VONIS["JUAL KUAT"] == -0.95


def test_sisi_jual_jadi_lebih_informatif():
    """-0,66% menjadi -0,95%: vonis jual yang baru lebih sering
    benar-benar menandai saham yang tertinggal."""
    assert app_module.UNGGUL_VONIS["JUAL KUAT"] < -0.66


def test_vonis_tengah_tetap_tidak_berarti():
    """Perubahan ini tidak menyulap bagian tengahnya."""
    for v in ("CENDERUNG BELI", "NETRAL", "CENDERUNG JUAL"):
        assert abs(app_module.UNGGUL_VONIS[v]) <= 0.25, v


# ---------------------------------------------------------------------------
# Aturan dua hari -- arahnya BERBALIK sesudah suara TREN masuk
# ---------------------------------------------------------------------------

def test_BELI_KUAT_yang_bertahan_jadi_jauh_lebih_baik():
    """Di sinilah perubahan vonisnya benar-benar terbayar:

        BELI KUAT bertahan hari-2:  lama +1,41%  ->  baru +4,59%

    BELI KUAT yang baru mensyaratkan keselarasan TREN, dan tren yang
    bertahan dua hari sangat berbeda dari lonjakan momentum sehari.
    +4,59% itu keunggulan terbesar dari seluruh vonis yang pernah diukur
    di proyek ini."""
    r = app_module.nilai_dua_hari("BELI KUAT", "BELI KUAT")
    assert r["bertahan"] is True
    assert r["unggul_pct"] == 4.59
    assert r["setara_kuat"] is True


def test_arah_aturan_dua_hari_berbalik_dari_pengukuran_lama():
    """Dulu aturan dua hari menolong vonis SEDANG dan tidak menolong yang
    ekstrem. Sekarang kebalikannya."""
    kuat = app_module.nilai_dua_hari("BELI KUAT", "BELI KUAT")
    sedang = app_module.nilai_dua_hari("BELI", "BELI")
    assert kuat["unggul_pct"] > sedang["unggul_pct"]


def test_setara_kuat_dihitung_dari_ANGKA_bukan_nama_vonisnya():
    """Syaratnya ditulis dari angkanya supaya ia ikut benar kalau suatu
    hari pengukurannya berubah lagi -- bukan dari nama vonis yang
    kebetulan menang pada pengukuran terakhir."""
    assert app_module.nilai_dua_hari("CENDERUNG BELI",
                                     "CENDERUNG BELI")["setara_kuat"] is False


def test_vonis_yang_berganti_memakai_angka_hari_pertama():
    r = app_module.nilai_dua_hari("BELI KUAT", "NETRAL")
    assert r["bertahan"] is False and r["unggul_pct"] == 1.11


def test_vonis_kemarin_tidak_diketahui_BUKAN_berarti_tidak_bertahan():
    """None berarti "tidak tahu"; keduanya menuntut tampilan berbeda --
    yang pertama diam, yang kedua boleh dibilang."""
    r = app_module.nilai_dua_hari("BELI KUAT", None)
    assert r["bertahan"] is None and r["setara_kuat"] is False


def test_vonis_kemarin_dihitung_dari_bar_SEBELUMNYA(monkeypatch):
    """Dihitung ulang dari df yang dipotong satu bar, BUKAN disimpan di
    cache -- cache yang menyimpan vonis kemarin akan basi persis pada
    hari yang penting, yaitu saat vonisnya berubah."""
    dipakai = {}

    def _palsu(df):
        dipakai["panjang"] = len(df)
        return _semua_beli()

    import core.ai_score as ais
    monkeypatch.setattr(ais, "calculate_ai_score_from_df", _palsu)

    class _DF:
        def __init__(self, n): self.n = n
        def __len__(self): return self.n
        @property
        def iloc(self):
            luar = self
            class _I:
                def __getitem__(self, k): return _DF(luar.n - 1)
            return _I()

    assert app_module._ringkasan_kemarin(_DF(300)) == "BELI KUAT"
    assert dipakai["panjang"] == 299, "memakai bar hari ini, bukan kemarin"


@pytest.mark.parametrize("rusak", [None, "bukan df"])
def test_vonis_kemarin_gagal_memulangkan_None(rusak):
    assert app_module._ringkasan_kemarin(rusak) is None


# ---------------------------------------------------------------------------
# Layar harus ikut berubah -- Python dan JS satu semantik
# ---------------------------------------------------------------------------

def _js():
    import pathlib

    return (pathlib.Path(__file__).resolve().parent.parent
            / "web" / "static" / "app.js").read_text(encoding="utf-8")


def test_JS_ikut_membalik_RSI():
    """Python dan JS harus satu semantik. Membalik satu sisi saja membuat
    layar dan server memberi vonis BERBEDA untuk saham yang sama -- dan
    tidak ada yang gagal saat itu terjadi."""
    js = _js()
    assert "rsi>=55?'beli':rsi<45?'jual':'netral'" in js
    assert "rsi<45?'beli'" not in js


def test_JS_ikut_menambah_suara_TREN():
    js = _js()
    assert "Tren (MA50/200)" in js
    assert "beli>=6?'BELI KUAT'" in js


def test_JS_mencabut_penanda_terbalik_pada_RSI():
    """RSI sudah dibalik, jadi peringatan "terbalik"-nya tidak lagi benar.
    Peringatan yang salah menggerus kepercayaan pada peringatan yang
    benar."""
    js = _js()
    blok = js[js.index("const _KEANDALAN_SUARA"):js.index("function _tagKeandalan")]
    assert "'RSI (14)'" not in blok
    assert "'Volume'" in blok, "Volume masih terukur terbalik, penandanya tetap"


def test_JS_memakai_angka_terukur_yang_BARU():
    js = _js()
    blok = js[js.index("const _UNGGUL_VONIS"):js.index("function _keandalanVonis")]
    assert "'BELI KUAT':1.11" in blok
    assert "'JUAL KUAT':-0.95" in blok
    assert "1.30" not in blok, "angka vonis lama masih terpajang"


def test_layar_memakai_angka_terukurnya():
    """Mengukur lalu tidak menampilkannya sama saja dengan tidak
    mengukur. Uji ini gagal kalau perendernya dicopot."""
    js = _js()
    assert "${_keandalanVonis(d, overall)}" in js
    assert "${_tagKeandalan(i.label)}" in js
    assert "terlalu kecil untuk dijadikan dasar" in js
