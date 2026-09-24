"""Nilai yang tidak diketahui tidak boleh menjatuhkan halamannya.

BUG NYATA 24 Sep 2026. Penulis melihat DUA panel sekaligus di halaman
Pemegang Saham berbunyi "Gagal: Terjadi kesalahan di server."

Asalnya perbaikan saya sendiri dua hari sebelumnya. Supaya hak suara yang
tidak terbaca berhenti dilaporkan sebagai nol (dan karenanya berhenti
mengarang "+15,00%" dari angka yang tak pernah dibaca), `pct_sebelum`
dibuat boleh bernilai None. Yang saya periksa waktu itu cuma pemakai
`perubahan`. Pemakai `pct_sebelum` sendiri terlewat -- dan `None >= 5.0`
di Python 3 bukan False, melainkan TypeError.

Yang membuatnya jadi DUA panel sekaligus, bukan satu: ungkapan
penyaringnya hidup dalam EMPAT salinan yang dituliskan ulang di empat
tempat. Ungkapan yang disalin tidak rusak sendiri-sendiri, ia rusak
serentak. Karena itu perbaikannya satu fungsi bersama, bukan empat
tambalan `or 0` -- tambalan begitu akan mengembalikan persis kebohongan
yang mau dihapus.
"""
import pytest

from web.app import _split_x15_items, _x15_substansial
from core.x15_parse import urai


def _baris(**ubah) -> dict:
    dasar = {"kode": "AAAA", "nama": "SESEORANG", "perusahaan": "PT Anu Tbk",
             "jabatan": "", "pct_sebelum": 1.0, "pct_setelah": 2.0,
             "perubahan": 1.0, "jenis": "beli", "pengendali": False}
    dasar.update(ubah)
    return dasar


# ---------------------------------------------------------------------------
# Yang meledak kemarin
# ---------------------------------------------------------------------------

def test_sebelum_tidak_diketahui_TIDAK_melempar_TypeError():
    """Inti kerusakannya. Satu baris begini cukup untuk memulangkan 500 ke
    seluruh panel, bukan cuma menghilangkan barisnya sendiri."""
    assert _x15_substansial(_baris(pct_sebelum=None, pct_setelah=3.0)) is False


def test_sebelum_tidak_diketahui_tapi_setelah_besar_tetap_lolos():
    """Kalau hak suara SESUDAH transaksi sudah >=5%, ia pemegang substansial
    apa pun nilai sebelumnya. Tidak tahu yang sebelumnya bukan alasan
    membuang laporan yang jelas memenuhi syarat."""
    assert _x15_substansial(_baris(pct_sebelum=None, pct_setelah=7.5)) is True


def test_pengendali_lolos_walau_kedua_persennya_tidak_terbaca():
    """Status pengendali ditetapkan lewat field sendiri, bukan disimpulkan
    dari persentase -- jadi ia tidak ikut gugur saat angkanya gagal dibaca."""
    assert _x15_substansial(
        _baris(pct_sebelum=None, pct_setelah=0.0, pengendali=True)) is True


@pytest.mark.parametrize("sebelum,setelah,harap", [
    (0.0, 0.0, False),      # nol SUNGGUHAN, bukan tak terbaca
    (5.0, 4.0, True),       # turun dari 5% -> tetap wajib tampil
    (4.9, 4.9, False),
    (None, None, False),    # dua-duanya tak terbaca
])
def test_ambang_lima_persen_tetap_seperti_semula(sebelum, setelah, harap):
    """Perbaikan ini tidak boleh diam-diam menggeser ambangnya. Yang berubah
    cuma perlakuan terhadap nilai yang TIDAK DIKETAHUI."""
    assert _x15_substansial(_baris(pct_sebelum=sebelum, pct_setelah=setelah)) is harap


# ---------------------------------------------------------------------------
# Jalur penuh: keluaran urai() harus bisa lewat penyaringnya
# ---------------------------------------------------------------------------

def test_keluaran_urai_yang_sebelumnya_kosong_lolos_penyaring():
    """Uji yang sebenarnya penting: BUKAN dict karangan, melainkan bentuk
    yang benar-benar dihasilkan urai(). Kalau suatu hari urai() memulangkan
    None untuk field lain, uji ini yang lebih dulu menemukannya."""
    hasil = urai(["Nama (sesuai SID)", ": SESEORANG",
                  "Hak Suara Setelah", ": 3,00%"])
    assert hasil["pct_sebelum"] is None, "prasyarat ujinya sendiri"
    assert _x15_substansial({**hasil, "kode": "AAAA"}) is False


def test_satu_baris_tak_terbaca_tidak_menghapus_baris_lain():
    """Yang dijaga di sini adalah PROPORSI kerusakannya: satu filing yang
    tidak terbaca boleh hilang, tapi tidak boleh membawa serta laporan lain
    yang terbaca sempurna."""
    baris = [
        _baris(kode="AAAA", pct_sebelum=None, pct_setelah=3.0),
        _baris(kode="BBBB", pct_sebelum=2.0, pct_setelah=9.0, perubahan=7.0),
        _baris(kode="CCCC", pct_sebelum=None, pct_setelah=8.0, perubahan=None),
    ]
    layak = [x for x in baris if _x15_substansial(x)]
    assert [x["kode"] for x in layak] == ["BBBB", "CCCC"]

    akum, dist, aksi = _split_x15_items(layak)
    assert [x["kode"] for x in akum] == ["BBBB"]
    # CCCC lolos sbg pemegang >=5%, tapi arah perubahannya tidak diketahui --
    # menaruhnya di akumulasi berarti mengaku tahu arah yang tidak dibaca.
    assert [x["kode"] for x in aksi] == ["CCCC"]
    assert dist == []
