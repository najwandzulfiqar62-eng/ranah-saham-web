"""Inverse Head & Shoulders -- detektornya benar, polanya yang tidak bekerja.

HASIL PENGUKURAN 10 Okt 2026 (178 emiten likuid, 2 tahun, horizon 20 hari
bursa, dihitung per SETUP UNIK). Dasar pembanding +1,86%:

    IHS terbentuk            n=133   naik 48,1%   unggul -0,43%
    IHS TEMBUS neckline      n= 68   naik 41,2%   unggul -0,68%
    terbentuk, belum tembus  n= 65   naik 43,1%   unggul -2,68%
    tembus + potensi >=10%   n= 41   naik 31,7%   unggul -7,42%

SETIAP VARIAN DI BAWAH PASAR. Konfirmasi tembus neckline -- aturan klasik
Edwards & Magee yang seharusnya memisahkan pola sungguhan dari pola gagal
-- tidak menolong. Dan yang paling MENGESANKAN justru paling buruk: pola
bertinggi >=10% cuma naik 31,7% dari waktu, tertinggal 7,42% dari sekadar
memegang saham acak.

Pola yang sama berulang di seluruh proyek ini: Minervini 8/8 terburuk, AI
score 65-80 terburuk, selisih RSI >6 terburuk, jatuh harga >15% terburuk.
Setup yang terlihat paling sempurna adalah setup yang sudah terlanjur
dihargai pasar.

KARENA ITU MODUL INI TIDAK DIPASANG SEBAGAI SINYAL MAUPUN SCREENER. Ia
disimpan beserta angkanya supaya tidak ada yang membangunnya lagi dari
nol -- termasuk saya. Berkas ini menguji dua hal terpisah: bahwa
detektornya BENAR (bentuk yang ditemukan memang Inverse H&S), dan bahwa
hasil pengukurannya tercatat.
"""
import pytest

from core.divergence import JEDA_KANAN
from core.pola_chart import (MAKS_UMUR_BAR, MIN_KEPALA_LEBIH_DALAM,
                             TOLERANSI_BAHU, cari_ihs, pivot_high)


def _bentuk(bahu_kiri=100.0, kepala=85.0, bahu_kanan=100.0, puncak=112.0,
            jarak=12, ekor=JEDA_KANAN, awal=70, kode="TEST"):
    """Deret berbentuk Inverse H&S: lembah - puncak - lembah - puncak - lembah.

    Puncaknya dibuat RUNCING (satu bar lebih tinggi dari tetangganya), bukan
    mendatar. Versi pertama fixture ini memakai dataran, dan penjaga
    daerah-datar di pivot_high menolaknya dengan benar -- yang salah
    fixture-nya, bukan kodenya.
    """
    import datetime as dt

    rendah, tinggi = [], []

    def isi(nilai_rendah, nilai_tinggi, n=1):
        rendah.extend([nilai_rendah] * n)
        tinggi.extend([nilai_tinggi] * n)

    # Pembuka menurun landai supaya bahu kiri jadi lembah sungguhan.
    for i in range(awal):
        h = puncak * (1.25 - 0.10 * i / max(awal - 1, 1))
        isi(h, h * 1.01)

    def lembah(v):
        isi(v, v * 1.01)

    # Dasar rally harus tetap DI ATAS bahu tertinggi; kalau tidak, ekor
    # rally yang menurun sendiri jadi lembah dan menggeser bahu yang
    # dimaksud. Versi pertama fixture ini kena persis jebakan itu.
    dasar_rally = max(bahu_kiri, bahu_kanan) * 1.03

    def rally(n):
        """Naik lalu turun, dengan SATU bar tertinggi di tengahnya."""
        rentang = puncak - dasar_rally
        sisi = max(1, (n - 1) // 2)
        for i in range(sisi):
            h = dasar_rally + rentang * (i + 1) / (sisi + 1)
            isi(h * 0.995, h)
        isi(puncak * 0.995, puncak)                     # puncak runcing
        sisa = n - sisi - 1
        for i in range(sisa):
            h = puncak - rentang * (i + 1) / (sisa + 1)
            isi(h * 0.995, h)

    lembah(bahu_kiri)
    rally(jarak - 1)
    lembah(kepala)
    rally(jarak - 1)
    lembah(bahu_kanan)
    for i in range(ekor):
        h = bahu_kanan * (1.02 + 0.02 * i)
        isi(h * 0.99, h)

    tutup = [(t + r) / 2 for t, r in zip(tinggi, rendah)]
    d0 = dt.date(2026, 1, 1)
    tgl = [(d0 + dt.timedelta(days=i)).isoformat() for i in range(len(rendah))]
    return kode, tgl, tinggi, rendah, tutup


# ---------------------------------------------------------------------------
# Detektornya benar
# ---------------------------------------------------------------------------

def test_bentuk_lengkap_terdeteksi():
    s = cari_ihs(*_bentuk())
    assert s is not None
    assert s.harga_kepala < s.harga_bahu_kiri
    assert s.harga_kepala < s.harga_bahu_kanan


def test_neckline_SELALU_di_atas_kepala():
    """BUG NYATA, ditemukan saat memeriksa BENTUK hasil deteksi (bukan
    hasilnya): 1 dari 48 pola punya neckline di BAWAH kepala. Itu mustahil
    untuk H&S terbalik -- polanya didefinisikan sebagai lembah di bawah
    neckline, dan proyeksi targetnya jadi negatif."""
    s = cari_ihs(*_bentuk())
    assert s.neckline > s.harga_kepala
    assert s.potensi_pct > 0


def test_kepala_harus_lebih_dalam_dari_KEDUA_bahu():
    """Tiga lembah yang nyaris sama tinggi bukan H&S -- itu cuma sideways."""
    assert cari_ihs(*_bentuk(bahu_kiri=100.0, kepala=99.5, bahu_kanan=100.0)) is None


def test_bahu_yang_terlalu_timpang_ditolak():
    """Pola yang definisinya terlalu longgar akan "ditemukan" di mana-mana,
    dan menemukan sesuatu di mana-mana sama dengan tidak menemukan apa pun.

    Bahu 100 vs 108 dengan kepala 85: selisih 8 terhadap kedalaman 19 =
    0,42, di atas ambang 0,35. Angkanya sengaja dekat ambang -- bahu yang
    jauh lebih tinggi dari puncak rally-nya sendiri tidak bisa jadi lembah
    sama sekali, jadi ia menguji penjaga yang salah."""
    assert cari_ihs(*_bentuk(bahu_kiri=100.0, kepala=85.0, bahu_kanan=108.0)) is None


def test_bahu_yang_sedikit_timpang_tetap_diterima():
    """Bahu H&S sungguhan jarang persis sejajar; ambang yang terlalu ketat
    akan membuang pola yang sah."""
    assert cari_ihs(*_bentuk(bahu_kiri=100.0, kepala=85.0,
                             bahu_kanan=103.0)) is not None


def test_lembah_belum_sah_sebelum_jeda_kanan():
    """Pelajaran yang sama dengan NR7 dan divergence: lembah baru bisa
    disebut lembah sesudah beberapa bar berikutnya terbukti lebih tinggi."""
    assert cari_ihs(*_bentuk(ekor=JEDA_KANAN - 1)) is None


def test_pola_yang_terlalu_tua_dibuang():
    """Pola yang menunggu terlalu lama bukan lagi pola yang sama -- keadaan
    yang melahirkannya sudah berganti."""
    assert cari_ihs(*_bentuk(ekor=MAKS_UMUR_BAR + 5)) is None


def test_setup_id_tetap_walau_dipindai_hari_berbeda():
    """Supaya satu pola tidak terhitung berkali-kali. Pelajaran dari
    divergence, di mana 10 setup sempat terhitung 80 kejadian dan
    menggelembungkan angkanya 3-4 kali lipat."""
    a = cari_ihs(*_bentuk(ekor=JEDA_KANAN))
    b = cari_ihs(*_bentuk(ekor=JEDA_KANAN + 5))
    assert a and b and a.setup_id == b.setup_id
    assert b.umur_bar > a.umur_bar


def test_pivot_high_menolak_daerah_datar():
    """Cerminan penjaga di pivot_low: kalau semua nilainya sama, tiap bar
    adalah "maksimum jendelanya" -- dan saham tidur di IDX sering menutup
    di harga persis sama berhari-hari."""
    assert pivot_high([10.0] * 30) == []
    assert pivot_high([1, 2, 3, 9, 3, 2, 1], kiri=3, kanan=3) == [3]


@pytest.mark.parametrize("args", [
    ("X", [], [], [], []),
    ("X", ["2026-01-01"] * 10, [1.0] * 10, [1.0] * 10, [1.0] * 10),
])
def test_data_terlalu_pendek_memulangkan_None(args):
    assert cari_ihs(*args) is None


# ---------------------------------------------------------------------------
# Hasil pengukurannya -- tercatat supaya tidak dibangun ulang
# ---------------------------------------------------------------------------

def test_ambang_sesuai_yang_dipakai_saat_mengukur():
    """Angka-angka ini yang berlaku saat pengukuran 10 Okt 2026. Kalau
    digeser, hasil pengukurannya tidak lagi berlaku dan harus diukur ulang
    sebelum pola ini dipertimbangkan lagi."""
    assert (TOLERANSI_BAHU, MIN_KEPALA_LEBIH_DALAM, MAKS_UMUR_BAR) == (0.35, 0.02, 30)


def test_modul_ini_TIDAK_dipakai_sebagai_sinyal():
    """Diukur: setiap varian IHS berkinerja DI BAWAH pasar (terbaik -0,43%,
    terburuk -7,42%). Memasangnya sebagai sinyal berarti mengirimi orang
    daftar yang lebih buruk daripada menebak.

    Uji ini gagal kalau suatu hari ada yang menyambungkannya ke jalur
    sinyal tanpa mengukur ulang lebih dulu."""
    import pathlib

    akar = pathlib.Path(__file__).resolve().parent.parent
    pemakai = []
    for f in (akar / "web" / "app.py", akar / "core" / "signal_history.py",
              akar / "core" / "screening_pro.py"):
        if f.exists() and "pola_chart" in f.read_text(encoding="utf-8"):
            pemakai.append(f.name)
    assert not pemakai, (
        f"core/pola_chart.py tersambung ke {pemakai} padahal pengukurannya "
        "menunjukkan keunggulan NEGATIF. Ukur ulang dulu sebelum memasangnya.")
