"""Penggolongan sektor harus KONSISTEN KE DALAM.

Ditemukan 19 Sep 2026 dari satu baris di layar: ARNA (Arwana Citramulia,
pabrik keramik) tertulis "Technology". Sekali dicek menyeluruh, ada 14 emiten
yang penggolongannya bertentangan dengan penggolongan aplikasi ini sendiri --
tambang emas masuk Energy sementara tambang emas lain masuk Basic Materials,
kontraktor masuk Real Estate sementara kontraktor lain masuk Infrastructure.

Yang diuji di sini BUKAN "apakah cocok dengan GICS/Yahoo" -- penggolongan IDX
memang berbeda dan itu disengaja (e-commerce masuk Teknologi, menara telekom
masuk Infrastruktur). Yang diuji: apakah emiten yang usahanya SAMA digolongkan
SAMA. Itu yang bisa dinilai benar-salah tanpa berdebat soal mazhab.
"""
import pytest


@pytest.fixture(scope="module")
def peta():
    import web.app as app_module
    return app_module.SECTOR_MAP_UNIVERSE


# Kelompok usaha sejenis. Kalau satu anggota pindah sektor tanpa yang lain,
# uji ini gagal -- dan itu memang yang diinginkan: yang salah bisa jadi
# emiten yang baru dipindah, bisa juga acuannya, tapi keduanya tidak boleh
# berbeda diam-diam.
SEJENIS = [
    ("bahan bangunan", ["SMGR", "INTP", "ARNA"]),
    ("kertas & kemasan", ["INKP", "TKIM", "FASW"]),
    ("tambang logam", ["ANTM", "INCO", "MDKA", "AMMN", "ARCI", "BRMS"]),
    ("petrokimia", ["BRPT", "TPIA", "ESSA"]),
    ("barang konsumsi harian", ["UNVR", "MYOR", "ICBP", "KINO"]),
    ("ritel bahan pokok", ["AMRT", "MIDI"]),
    ("kontraktor", ["WIKA", "PTPP", "ADHI", "NRCA", "SSIA"]),
    ("batu bara", ["ADRO", "PTBA", "ITMG"]),
    ("bank", ["BBCA", "BBRI", "BMRI", "BBNI"]),
    ("menara telekomunikasi", ["TOWR", "TBIG", "SUPR"]),
]


@pytest.mark.parametrize("nama,kelompok", SEJENIS, ids=[n for n, _ in SEJENIS])
def test_emiten_sejenis_digolongkan_sama(peta, nama, kelompok):
    ada = {k: peta[k] for k in kelompok if k in peta}
    if len(ada) < 2:
        pytest.skip(f"kelompok {nama} tidak cukup anggota di peta")
    sektor = set(ada.values())
    assert len(sektor) == 1, (
        f"kelompok '{nama}' terpecah ke {len(sektor)} sektor: {ada}")


def test_arna_bukan_teknologi(peta):
    """Baris yang memulai semuanya. Arwana Citramulia membuat keramik."""
    assert peta["ARNA"] == "Basic Materials", (
        f"ARNA kembali salah golong: {peta['ARNA']}")


def test_semua_sektor_termasuk_daftar_yang_dikenal(peta):
    """Salah ketik nama sektor tidak memunculkan error -- ia cuma membuat satu
    emiten berdiri sendiri di golongan yang tidak pernah ada, dan itu lolos
    tanpa ketahuan sampai ada yang memandanginya di layar."""
    DIKENAL = {
        "Financials", "Infrastructure", "Industrials", "Energy",
        "Basic Materials", "Consumer Non-Cyclical", "Consumer Cyclical",
        "Healthcare", "Technology", "Real Estate",
        "Transportation & Logistics",
    }
    asing = {k: v for k, v in peta.items() if v not in DIKENAL}
    assert not asing, f"nama sektor tidak dikenal: {asing}"


def test_setiap_emiten_di_universe_punya_sektor():
    """Yang tidak ada di peta tampil sebagai "Lainnya" -- bukan error, tapi
    juga bukan informasi. Kalau jumlahnya bertambah diam-diam, tag sektor
    pelan-pelan berhenti berguna."""
    import web.app as app_module

    tanpa = [k for k in app_module.TOP_PICK_UNIVERSE
             if k not in app_module.SECTOR_MAP_UNIVERSE]
    assert len(tanpa) <= 5, (
        f"{len(tanpa)} emiten di universe tanpa sektor: {sorted(tanpa)}")


def test_tidak_ada_emiten_hilang_dari_universe():
    """Merapikan pengelompokan itu memindah baris antar-blok, dan salah
    tempel di situ menghapus emiten tanpa ada yang error."""
    import web.app as app_module

    assert len(app_module.LIQUID_250) == len(set(app_module.LIQUID_250)), (
        "ada kode ganda di LIQUID_250")
    for kode in ("ARNA", "KREN", "DPUM", "PALM"):
        assert kode in app_module.TOP_PICK_UNIVERSE, f"{kode} hilang dari universe"
