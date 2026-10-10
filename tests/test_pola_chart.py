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


def _pastikan_bukan_sumber_sinyal():
    """Pola chart boleh DITAMPILKAN, tidak boleh MENYURUH.

    Bedanya bukan soal kata: sinyal masuk signal_history, ikut dihitung
    win rate, dan dikirim otomatis ke WhatsApp. Label cuma memberi tahu
    bentuknya, lengkap dengan angka terukurnya, dan pengguna yang
    menilai sendiri.

    Pengukuran 11 Okt 2026 (790 emiten, jalan maju, per pola) memang
    menemukan beberapa pola yang berarti -- Head & Shoulders tembus
    -3,36% dan Segitiga Menaik tembus +3,24%. Tapi "berarti" belum tentu
    "cukup untuk dijadikan sinyal": Inverse Head & Shoulders justru
    -1,12%, yaitu pola bullish yang terukur BERLAWANAN dengan artinya.
    Menyambungkan keseluruhan katalog ke jalur sinyal berarti ikut
    mengirimkan yang itu.

    Penjaga ini gagal kalau ada yang menyambungkannya ke pencatat sinyal
    tanpa pengukuran baru per pola lebih dulu.
    """
    import ast
    import pathlib
    import re

    akar = pathlib.Path(__file__).resolve().parent.parent

    # 1. Modul pencatat sinyal & screener sama sekali tidak boleh
    #    menyentuhnya.
    for nama in ("core/signal_history.py", "core/screening_pro.py"):
        f = akar / nama
        if not f.exists():
            continue
        isi = f.read_text(encoding="utf-8")
        assert "pola_chart" not in isi and "pola_katalog" not in isi, (
            f"{nama} menyentuh modul pola -- itu jalur SINYAL, "
            "dan pola belum diukur cukup untuk jadi sinyal.")

    # 2. Di web/app.py pola hanya boleh dipakai untuk MENAMPILKAN.
    #    Pemakaian yang sah: _pola_chart_payload (payload Analisis) dan
    #    /api/ohlc (gambar di chart). Apa pun di luar itu dicurigai.
    app = (akar / "web" / "app.py").read_text(encoding="utf-8")
    # Dibaca sbg POHON SINTAKS, bukan sbg teks. Pencarian teks ikut
    # menangkap kata di dalam komentar dan docstring -- penjaga ini
    # sempat menyala gara-gara satu KALIMAT PENJELASAN yang kebetulan
    # menyebut nama modulnya. Penjaga yang menyala karena kalimat akan
    # dimatikan orang, lalu berhenti menjaga hal yang sungguhan.
    pohon = ast.parse(app)
    fungsi_pemakai, n_impor = set(), 0
    for n in ast.walk(pohon):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in ast.walk(n):
                if isinstance(d, ast.ImportFrom) and "pola_" in (d.module or ""):
                    fungsi_pemakai.add(n.name)
                    n_impor += 1
    assert fungsi_pemakai <= {"_pola_chart_payload"}, (
        f"modul pola diimpor di {sorted(fungsi_pemakai)} -- satu-satunya "
        "jalur yang sah adalah _pola_chart_payload (tampilan).")
    assert n_impor, "penjaga tidak menemukan impor apa pun; ia tidak menguji apa pun"

    # 3. Dan yang paling penting: tidak boleh ada yang merekamnya sbg
    #    sinyal. `source=` di signal_history menandai sumber sinyal.
    for m in re.finditer(r"source\s*=\s*[\"']([A-Z_0-9]+)[\"']", app):
        assert "POLA" not in m.group(1), (
            f"pola direkam sbg sumber sinyal: {m.group(1)}")


def test_modul_ini_TIDAK_dipakai_sebagai_sinyal():
    """Diukur: setiap varian IHS berkinerja DI BAWAH pasar (terbaik -0,43%,
    terburuk -7,42%). Memasangnya sebagai sinyal berarti mengirimi orang
    daftar yang lebih buruk daripada menebak.

    Uji ini gagal kalau suatu hari ada yang menyambungkannya ke jalur
    sinyal tanpa mengukur ulang lebih dulu."""
    _pastikan_bukan_sumber_sinyal()


# ===========================================================================
# BULL FLAG -- pola LANJUTAN, satu-satunya jenis yang akhirnya positif
# ===========================================================================
# HASIL PENGUKURAN 10 Okt 2026 (178 emiten, 2 tahun, 20 hari bursa, per
# setup unik). Dasar: naik 45,9%, rata-rata +1,86%:
#
#     semua bull flag        n=4102   naik 48,2%   unggul +1,07%
#     sudah TEMBUS           n=1337   naik 47,3%   unggul +1,92%
#     belum tembus           n=2765   naik 48,6%   unggul +0,66%
#     koreksi dangkal <25%   n=2101   naik 48,7%   unggul +1,21%
#
# SATU-SATUNYA dari tiga pola yang diuji dengan tanda positif konsisten --
# Inverse H&S -0,68%, falling wedge +1,24% tapi win rate di bawah pasar.
#
# TAPI BELAH WAKTUNYA TIDAK STABIL: paruh awal unggul +0,41% (n=712),
# paruh akhir +2,25% (n=620). Lima kali lipat bedanya. Dengan n segitu,
# itu menunjukkan keunggulannya didorong beberapa pemenang besar, bukan
# efek yang ajeg. Karena itu ia TIDAK dipasang sebagai panel sendiri:
# +1,91% dengan sebaran seperti itu tidak sebanding dengan panel Pemulihan
# (+4,11%, stabil di kedua paruh).

from core.pola_chart import (MAKS_KOREKSI_TIANG, MIN_TIANG_PCT,
                             cari_bull_flag)


def _flag(tiang_pct=25.0, koreksi_porsi=0.3, bendera=6, awal=60,
          dasar=100.0, kode="TEST"):
    """Tiang naik tajam, lalu istirahat dangkal."""
    import datetime as dt

    tinggi, rendah = [], []

    def isi(lo, hi, n=1):
        rendah.extend([lo] * n)
        tinggi.extend([hi] * n)

    for i in range(awal):                       # datar sebelum tiang
        isi(dasar * 0.995, dasar * 1.005)
    puncak = dasar * (1 + tiang_pct / 100)
    for i in range(10):                         # tiang
        h = dasar + (puncak - dasar) * (i + 1) / 10
        isi(h * 0.99, h)
    rendah_bendera = puncak - (puncak - dasar) * koreksi_porsi
    for i in range(bendera):                    # bendera menurun dangkal
        h = puncak - (puncak - rendah_bendera) * (i + 1) / bendera
        isi(h, h * 1.005)

    tutup = [(t + r) / 2 for t, r in zip(tinggi, rendah)]
    d0 = dt.date(2026, 1, 1)
    tgl = [(d0 + dt.timedelta(days=i)).isoformat() for i in range(len(rendah))]
    return kode, tgl, tinggi, rendah, tutup


def test_bull_flag_terdeteksi():
    s = cari_bull_flag(*_flag())
    assert s is not None
    assert s.tiang_pct >= MIN_TIANG_PCT


def test_tiang_terlalu_pendek_ditolak():
    """Kenaikan 5% bukan tiang -- itu gerak biasa, dan pola yang
    memasukkannya akan "ditemukan" di mana-mana."""
    assert cari_bull_flag(*_flag(tiang_pct=5.0)) is None


def test_koreksi_terlalu_dalam_ditolak():
    """Lebih dari separuh tiang termakan = itu bukan istirahat, itu
    pembalikan. Pola yang definisinya memuat keduanya tidak memberi tahu
    apa pun."""
    assert cari_bull_flag(*_flag(koreksi_porsi=0.8)) is None
    assert MAKS_KOREKSI_TIANG == 0.50


def test_breakout_BISA_terdeteksi():
    """CACAT NYATA versi pertama: puncak tiang disyaratkan tetap yang
    tertinggi sampai bar terakhir, sehingga begitu harga menembusnya
    polanya berhenti terdeteksi. "Sudah tembus" melaporkan NOL dari 5.664
    pola -- breakout, yang justru inti pola lanjutan, tersingkir oleh
    syarat deteksinya sendiri. Ketahuan dari angka yang mustahil, bukan
    dari membaca kodenya."""
    kode, tgl, hi, lo, cl = _flag(bendera=5)
    # Satu bar menembus puncak tiang.
    puncak = max(hi[:-5])
    hi = hi + [puncak * 1.03]
    lo = lo + [puncak * 1.00]
    cl = cl + [puncak * 1.02]
    import datetime as dt
    tgl = tgl + [(dt.date.fromisoformat(tgl[-1]) + dt.timedelta(days=1)).isoformat()]
    s = cari_bull_flag(kode, tgl, hi, lo, cl)
    assert s is not None and s.tembus is True


def test_bendera_panjang_bisa_terdeteksi():
    """CACAT NYATA kedua: versi pertama mencoba panjang bendera dari yang
    terpendek lalu BERHENTI di yang pertama cocok, sehingga "bendera
    panjang" melaporkan SATU kejadian dari 5.664 -- bukan karena langka,
    tapi karena tidak pernah sempat dilihat."""
    s = cari_bull_flag(*_flag(bendera=14))
    assert s is not None and s.bendera_bar >= 10


def test_setup_id_dari_tanggal_pola_bukan_tanggal_pindai():
    """Jebakan yang sama sudah dua kali menggelembungkan angka di proyek
    ini: divergence (10 setup terhitung 80) dan falling wedge (3.808 pola
    per tahun, mustahil)."""
    a = cari_bull_flag(*_flag(bendera=6))
    b = cari_bull_flag(*_flag(bendera=8))
    assert a and b and a.setup_id == b.setup_id


@pytest.mark.parametrize("args", [
    ("X", [], [], [], []),
    ("X", ["2026-01-01"] * 20, [1.0] * 20, [1.0] * 20, [1.0] * 20),
])
def test_data_terlalu_pendek(args):
    assert cari_bull_flag(*args) is None


def test_bull_flag_juga_TIDAK_dipasang_sebagai_sinyal():
    """Terukur +1,91% pada breakout -- positif, dan satu-satunya dari tiga
    pola yang begitu. Tapi belah waktunya +0,41% vs +2,25%, lima kali
    lipat bedanya, dan panel Pemulihan yang sudah ada memberi +4,11% yang
    stabil di kedua paruh.

    Uji ini gagal kalau ia disambungkan ke jalur sinyal tanpa pengukuran
    baru yang menunjukkan kestabilannya."""
    _pastikan_bukan_sumber_sinyal()
