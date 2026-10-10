"""Ringkasan Sinyal Teknikal: mana vonis yang benar-benar berarti.

DIUKUR 10 Okt 2026 pada 173 emiten likuid, 2 tahun, 25.097 EPISODE vonis
(bukan per bar -- bar berurutan dengan vonis sama itu nyaris duplikat dan
hasil 20-harinya saling tumpang tindih). Dasar pembanding +0,88%:

    BELI KUAT        n=1186   unggul +1,30%
    BELI             n=1813   unggul +0,13%
    CENDERUNG BELI   n=6353   unggul +0,04%
    NETRAL           n=4870   unggul +0,12%
    CENDERUNG JUAL   n=6671   unggul -0,10%
    JUAL             n=3533   unggul -0,42%
    JUAL KUAT        n= 671   unggul -0,66%

HANYA DUA UJUNGNYA YANG BERARTI. Empat vonis di tengah semuanya berada
dalam rentang +-0,13% dari pasar -- tidak bisa dibedakan dari tidak tahu
apa-apa. Tangga tujuh tingkat menjanjikan tujuh derajat ketelitian yang
tidak dimilikinya, dan orang yang membaca "CENDERUNG BELI" wajar mengira
ia mendapat sesuatu.

ATURAN DUA HARI (Edwards & Magee, lewat Edianto Ong) juga diukur, dan ia
menolong justru pada vonis yang SEDANG:

    BELI awal episode     n=1813   unggul +0,13%
    BELI bertahan hari-2  n= 294   unggul +1,63%
    BELI KUAT awal        n=1186   unggul +1,30%
    BELI KUAT hari-2      n= 150   unggul +1,41%

BELI yang bertahan sehari lagi setara nilainya dengan BELI KUAT. Yang
sudah ekstrem tidak bertambah baik dengan ditunggu -- saat ia bertahan,
geraknya sudah terjadi.

KONFIRMASI VOLUME dari buku yang sama TIDAK menolong di sini (+1,40%
dengan volume vs +1,63% tanpa), dan sebabnya masuk akal: volume sudah
jadi salah satu dari enam suara pembentuk vonisnya. Dicatat sebagai hasil
negatif supaya tidak ditambahkan lagi oleh orang berikutnya.
"""
import pytest

import web.app as app_module


def _ai(rsi=50, macd=False, vol=1.0, score=50, c1=0.0, c5=0.0):
    return {"rsi": rsi, "macd_bullish": macd, "vol_ratio": vol,
            "score": score, "change_1d": c1, "change_5d": c5}


def _vonis(**k):
    return app_module._ringkasan_sinyal_teknikal(_ai(**k))


# ---------------------------------------------------------------------------
# Vonisnya sendiri TIDAK boleh bergeser
# ---------------------------------------------------------------------------

def test_vonis_lama_tidak_berubah():
    """Sinyal yang SUDAH tercatat di signal_history memakai semantik ini.
    Menggesernya diam-diam membuat riwayat lama dan baru tidak lagi
    sebanding, tanpa satu pun tanda bahwa itu terjadi."""
    semua_beli = _vonis(rsi=40, macd=True, vol=1.5, score=70, c1=2.0, c5=5.0)
    assert semua_beli["overall"] == "BELI KUAT"
    assert semua_beli["beli"] == 6

    semua_jual = _vonis(rsi=75, macd=False, vol=0.3, score=30, c1=-2.0, c5=-5.0)
    assert semua_jual["overall"] == "JUAL KUAT"

    assert _vonis()["overall"] in ("NETRAL", "CENDERUNG BELI", "CENDERUNG JUAL")


# ---------------------------------------------------------------------------
# Keandalan yang diukur
# ---------------------------------------------------------------------------

def test_hanya_dua_ujung_yang_ditandai_berarti():
    """Empat vonis di tengah semuanya dalam rentang +-0,13% dari pasar.
    Menandainya "berarti" akan menjual ketelitian yang tidak ada."""
    kuat_beli = _vonis(rsi=40, macd=True, vol=1.5, score=70, c1=2.0, c5=5.0)
    kuat_jual = _vonis(rsi=75, macd=False, vol=0.3, score=30, c1=-2.0, c5=-5.0)
    assert kuat_beli["terukur_berarti"] is True
    assert kuat_jual["terukur_berarti"] is True

    # Empat suara beli = "BELI", yang terukur cuma +0,13%.
    sedang = _vonis(rsi=40, macd=True, vol=1.5, score=70, c1=0.0, c5=0.0)
    assert sedang["overall"] == "BELI"
    assert sedang["terukur_berarti"] is False


def test_angka_keunggulan_sesuai_yang_diukur():
    """Kalau suatu hari angkanya digeser tanpa pengukuran baru, uji ini
    memaksa penggesernya berhenti dan mengukur dulu."""
    kuat_beli = _vonis(rsi=40, macd=True, vol=1.5, score=70, c1=2.0, c5=5.0)
    kuat_jual = _vonis(rsi=75, macd=False, vol=0.3, score=30, c1=-2.0, c5=-5.0)
    assert kuat_beli["unggul_terukur_pct"] == 1.30
    assert kuat_jual["unggul_terukur_pct"] == -0.66


def test_vonis_tengah_tidak_menjanjikan_angka():
    """None, BUKAN nol. Nol adalah klaim ("terukur tidak unggul"); None
    mengatakan yang sebenarnya ("tidak cukup berbeda untuk disebut")."""
    sedang = _vonis(rsi=40, macd=True, vol=1.5, score=70)
    assert sedang["unggul_terukur_pct"] is None


# ---------------------------------------------------------------------------
# Aturan dua hari
# ---------------------------------------------------------------------------

def test_vonis_kemarin_dihitung_dari_bar_sebelumnya(monkeypatch):
    """Dihitung ulang dari df yang dipotong satu bar, BUKAN disimpan di
    cache -- cache yang menyimpan vonis kemarin akan basi persis pada hari
    yang penting, yaitu saat vonisnya berubah."""
    dipakai = {}

    def _palsu(df):
        dipakai["panjang"] = len(df)
        return _ai(rsi=40, macd=True, vol=1.5, score=70, c1=2.0, c5=5.0)

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
    """None berarti "tidak tahu", dan pemanggilnya harus memperlakukannya
    begitu -- BUKAN sebagai "tidak bertahan". Keduanya menuntut tindakan
    yang berbeda."""
    assert app_module._ringkasan_kemarin(rusak) is None


def test_data_terlalu_pendek_memulangkan_None():
    class _DF:
        def __len__(self): return 10
    assert app_module._ringkasan_kemarin(_DF()) is None


# ---------------------------------------------------------------------------
# Hasil negatif yang ikut dicatat
# ---------------------------------------------------------------------------

def test_volume_sudah_jadi_salah_satu_suara():
    """Konfirmasi volume dari buku TIDAK ditambahkan lagi di atas vonis,
    karena volume SUDAH salah satu dari enam suaranya. Diukur: +1,40%
    dengan saringan volume vs +1,63% tanpa -- menambahkannya justru
    sedikit memperburuk."""
    tinggi = _vonis(vol=1.5)
    rendah = _vonis(vol=0.3)
    assert tinggi["beli"] > rendah["beli"]


# ---------------------------------------------------------------------------
# Aturan dua hari yang BENAR-BENAR DIPAKAI
# ---------------------------------------------------------------------------
# `ringkasan_kemarin` sempat dihitung tanpa ada satu pun pembacanya --
# 1,4 detik per pemindaian 178 emiten untuk field yang langsung dibuang.
# Pekerjaan yang tak terpakai tidak gagal dan tidak terlihat; ia cuma
# memperlambat. Uji di bawah ini memastikan ia punya pemakai.

def test_beli_yang_bertahan_setara_BELI_KUAT():
    """Temuan utama dari aturan dua hari Edwards & Magee, terukur:
    BELI awal episode +0,13% (n=1813) -> bertahan hari-2 +1,63% (n=294).
    Itu setara BELI KUAT (+1,30%), dari vonis yang sendirian nyaris tidak
    berarti apa-apa."""
    r = app_module.nilai_dua_hari("BELI", "BELI")
    assert r["bertahan"] is True
    assert r["unggul_pct"] == 1.63
    assert r["setara_kuat"] is True


def test_BELI_KUAT_tidak_bertambah_baik_dengan_ditunggu():
    """Diukur: BELI KUAT awal +1,30% -> hari-2 +1,41%, nyaris tak
    berubah. Yang sudah ekstrem tidak perlu dikonfirmasi -- saat ia
    bertahan, geraknya sudah terjadi."""
    r = app_module.nilai_dua_hari("BELI KUAT", "BELI KUAT")
    assert r["setara_kuat"] is False
    assert abs(r["unggul_pct"] - 1.41) < 0.01


def test_vonis_yang_berganti_memakai_angka_hari_pertama():
    r = app_module.nilai_dua_hari("BELI", "NETRAL")
    assert r["bertahan"] is False and r["unggul_pct"] == 0.13


def test_vonis_kemarin_tidak_diketahui_BUKAN_berarti_tidak_bertahan():
    """None berarti "tidak tahu", dan keduanya menuntut tampilan yang
    berbeda: yang pertama diam, yang kedua boleh dibilang."""
    r = app_module.nilai_dua_hari("BELI", None)
    assert r["bertahan"] is None
    assert r["setara_kuat"] is False


def test_vonis_tengah_tetap_tidak_berarti_walau_bertahan():
    """Bertahan tidak menyulap vonis yang memang tidak informatif. Diukur,
    CENDERUNG BELI cuma +0,04% -- dan dua hari berturut-turut tetap
    +0,04%."""
    r = app_module.nilai_dua_hari("CENDERUNG BELI", "CENDERUNG BELI")
    assert r["setara_kuat"] is False
    assert abs(r["unggul_pct"]) < 0.5


def test_angka_keunggulan_tiap_vonis_sesuai_yang_diukur():
    assert app_module.UNGGUL_VONIS["BELI KUAT"] == 1.30
    assert app_module.UNGGUL_VONIS["JUAL KUAT"] == -0.66
    # Empat vonis tengah, semuanya dalam rentang +-0,13%.
    for v in ("BELI", "CENDERUNG BELI", "NETRAL", "CENDERUNG JUAL"):
        assert abs(app_module.UNGGUL_VONIS[v]) <= 0.13, v


def test_layar_memakai_angka_terukurnya():
    """Mengukur lalu tidak menampilkannya sama saja dengan tidak
    mengukur. Uji ini gagal kalau perendernya dicopot."""
    import pathlib

    js = (pathlib.Path(__file__).resolve().parent.parent
          / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "_keandalanVonis" in js
    assert "${_keandalanVonis(d, overall)}" in js
    assert "terlalu kecil untuk dijadikan dasar" in js


# ---------------------------------------------------------------------------
# Keandalan TIAP SUARA -- keenamnya tidak setara
# ---------------------------------------------------------------------------
# Diukur 11 Okt 2026 (178 emiten likuid, 37.195 bar, horizon 20 hari).
# Angka = SELISIH keunggulan antara sinyal "beli" dan "jual" suara itu:
#
#     TREN (calon)  +1,35%   belum ada di Ringkasan
#     MACD          +1,27%
#     %5 Hari       +0,72%
#     %1 Hari       +0,54%
#     AI Score      +0,24%   praktis tidak memisahkan
#     Volume        -0,77%   TERBALIK
#     RSI           -2,18%   TERBALIK, dan parah

def test_layar_menandai_suara_yang_TERBALIK():
    """Suara yang memilih ke arah salah tetap ikut menentukan vonis.
    Selama itu tidak dikatakan, pembacanya menimbangnya sama berat dengan
    suara yang benar."""
    import pathlib

    js = (pathlib.Path(__file__).resolve().parent.parent
          / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "_KEANDALAN_SUARA" in js
    assert "${_tagKeandalan(i.label)}" in js, "tag tidak dipakai kartu indikator"
    assert "TERBALIK" in js


def test_angka_keandalan_suara_sesuai_yang_diukur():
    """Kalau digeser tanpa pengukuran baru, uji ini memaksa penggesernya
    berhenti dan mengukur dulu."""
    import pathlib
    import re

    js = (pathlib.Path(__file__).resolve().parent.parent
          / "web" / "static" / "app.js").read_text(encoding="utf-8")
    blok = js[js.index("const _KEANDALAN_SUARA"):js.index("function _tagKeandalan")]
    angka = dict(re.findall(r"'([^']+)':\s*\{pisah:\s*(-?[\d.]+)", blok))
    assert float(angka["RSI (14)"]) == -2.18
    assert float(angka["Volume"]) == -0.77
    assert float(angka["MACD"]) == 1.27


def test_vonis_TIDAK_ikut_berubah_oleh_temuan_ini():
    """Menggeser vonisnya membuat riwayat lama dan baru tidak sebanding
    tanpa satu pun tanda. Itu keputusan pemilik datanya, bukan keputusan
    yang boleh diambil diam-diam oleh perubahan tampilan.

    RSI <45 TETAP dihitung 'beli' walau terukur merugikan -- yang berubah
    cuma bahwa layar sekarang mengatakannya."""
    r = _vonis(rsi=40, macd=True, vol=1.5, score=70, c1=2.0, c5=5.0)
    assert r["beli"] == 6 and r["overall"] == "BELI KUAT"
