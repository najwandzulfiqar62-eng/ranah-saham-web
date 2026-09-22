"""Pasangan pemegang saham <-> emiten tidak boleh tertukar.

BUG NYATA 22 Sep 2026, terlihat penulis di layarnya sendiri:

    TRUK  · PT PUKUL RATA KANAN     +15,00%
    AKPI  · HAKIMSON GROWTH CAPITAL  +5,00%

Nama dan persentasenya BENAR -- keduanya perusahaan sungguhan, dan angkanya
cocok dengan pemberitaan. Yang salah EMITENNYA: Hakimson Growth Capital
membeli 5% saham TRUK, bukan AKPI. Keduanya membeli TRUK pada hari yang
sama, menggantikan Catur Dharma Anugerah Surya.

Kesalahan seperti ini yang paling sulit ditangkap: tiap bagiannya terlihat
benar, yang salah cuma pasangannya.

CATATAN UNTUK PEMBACA BERIKUTNYA. Saya sempat menyimpulkan "PUKUL RATA
KANAN" itu serpihan tata letak PDF (align right) dan nyaris memasang
penyaring nama yang "terdengar masuk akal". Itu akan MEMBUANG data yang
benar. Penyaring yang menebak-nebak nama mana yang wajar adalah cara
membuat kesalahan yang jauh lebih sulit disadari daripada nama aneh yang
lolos.
"""
import pytest

from core.x15_parse import baca_persen, bersih_nama, cari_nilai, emiten_cocok, urai


# ---------------------------------------------------------------------------
# Pemeriksaan pasangan -- inti perbaikannya
# ---------------------------------------------------------------------------

def test_kasus_nyata_hakimson_truk_bukan_akpi():
    """Filing atas Guna Timur Raya (TRUK) tidak boleh tampil di bawah AKPI."""
    assert emiten_cocok("PT Guna Timur Raya Tbk",
                        "Argha Karya Prima Industry Tbk") is False
    assert emiten_cocok("PT Guna Timur Raya Tbk", "Guna Timur Raya Tbk") is True


def test_bentuk_badan_usaha_tidak_dipakai_mencocokkan():
    """Hampir semua emiten BEI mengandung "PT" dan "Tbk". Mencocokkan lewat
    kata itu akan menyatakan SEMUA emiten cocok dengan semua emiten -- dan
    pemeriksaan yang selalu lolos sama saja dengan tidak ada."""
    assert emiten_cocok("PT Tbk", "PT Tbk") is None
    assert emiten_cocok("PT Indonesia Tbk", "PT Indonesia Tbk") is None


def test_tidak_bisa_dinilai_mengembalikan_None_bukan_menolak():
    """Menolak baris karena nama pembandingnya kebetulan tidak tersedia
    akan membuang data yang benar -- kesalahan yang sama seperti menerima
    yang salah, cuma arahnya berbeda."""
    assert emiten_cocok("", "Guna Timur Raya Tbk") is None
    assert emiten_cocok("PT Guna Timur Raya Tbk", "") is None


def test_baris_dengan_emiten_tidak_cocok_dibuang():
    strings = ["Nama (sesuai SID)", ": HAKIMSON GROWTH CAPITAL",
               "Nama Perusahaan Tbk", ": PT Guna Timur Raya Tbk",
               "Hak Suara Sebelum", ": 0,00%",
               "Hak Suara Setelah", ": 5,00%"]
    assert urai(strings, "Argha Karya Prima Industry Tbk") is None
    hasil = urai(strings, "Guna Timur Raya Tbk")
    assert hasil is not None
    assert hasil["nama"] == "HAKIMSON GROWTH CAPITAL"
    assert hasil["pct_setelah"] == 5.0
    assert hasil["emiten_terverifikasi"] is True


# ---------------------------------------------------------------------------
# Nama: jangan membuang yang benar
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nama", [
    "PT PUKUL RATA KANAN",          # sungguhan -- 15% TRUK, 18 Sep 2026
    "HAKIMSON GROWTH CAPITAL",      # sungguhan -- 5% TRUK
    "PT Catur Dharma Anugerah Surya",
    "Gabriel Rey",
])
def test_nama_sungguhan_tidak_dibuang(nama):
    assert bersih_nama(nama) == nama


@pytest.mark.parametrize("kosong", ["null", "NULL", "-", "n/a",
                                    "Tidak ditampilkan", "  "])
def test_penanda_kosong_dikosongkan(kosong):
    assert bersih_nama(kosong) == ""


# ---------------------------------------------------------------------------
# Persen: yang tidak terbaca BUKAN nol
# ---------------------------------------------------------------------------

def test_persen_yang_gagal_dibaca_bukan_nol():
    """Ini yang membuat laporan mengarang. Kalau "hak suara sebelum" tidak
    terbaca lalu dianggap 0, perubahannya tercetak sebagai kenaikan PENUH
    ("+15,00%") padahal yang sebenarnya terjadi tidak diketahui. Angka yang
    dikarang jauh lebih berbahaya daripada kolom kosong: kolom kosong
    terlihat kosong, angka karangan terlihat seperti fakta."""
    assert baca_persen("") is None
    assert baca_persen("n/a") is None
    assert baca_persen("-") is None
    assert baca_persen("0,00%") == 0.0, "nol SUNGGUHAN harus tetap nol"


@pytest.mark.parametrize("teks,harap", [
    ("15,00%", 15.0), ("5.5", 5.5), (": 7,25 %", 7.25), ("0%", 0.0),
])
def test_persen_yang_wajar_terbaca(teks, harap):
    assert baca_persen(teks) == harap


@pytest.mark.parametrize("diluar", ["250", "-13", "1000%"])
def test_persen_di_luar_nalar_ditolak(diluar):
    """Hak suara di luar 0-100 berarti yang terbaca bukan persentase --
    mungkin nomor urut, tanggal, atau jumlah lembar saham."""
    assert baca_persen(diluar) is None


def test_perubahan_tidak_dihitung_kalau_sebelumnya_tidak_diketahui():
    strings = ["Nama (sesuai SID)", ": SESEORANG",
               "Hak Suara Setelah", ": 5,00%"]
    hasil = urai(strings)
    assert hasil["pct_sebelum"] is None
    assert hasil["perubahan"] is None, "kenaikan penuh dikarang dari nilai tak diketahui"


# ---------------------------------------------------------------------------
# Penyambungan potongan teks
# ---------------------------------------------------------------------------

def test_nama_yang_terpecah_disambung():
    """Teks di PDF terpecah karena kerning: "PT SINAR MAS" bisa tersimpan
    sebagai ("PT ")("SINAR")(" MAS"). Mengambil satu potongan menghasilkan
    potongan, bukan nama -- dan itulah asal nama-nama aneh."""
    strings = ["Nama (sesuai SID)", ":", "PT ", "SINAR", " MAS", "TBK",
               "Jabatan:"]
    assert "SINAR" in cari_nilai(strings, "sesuai SID")
    assert "MAS" in cari_nilai(strings, "sesuai SID")


def test_nilai_di_baris_yang_sama_ikut_terbaca():
    strings = ["Hak Suara Setelah : 12,50%"]
    assert baca_persen(cari_nilai(strings, "Hak Suara Setelah")) == 12.5


def test_tanpa_hak_suara_setelah_barisnya_dibuang():
    """Tanpa angka itu, barisnya tidak memberi tahu apa pun yang bisa
    dipercaya."""
    assert urai(["Nama (sesuai SID)", ": SESEORANG"]) is None


def test_tanpa_nama_sama_sekali_barisnya_dibuang():
    assert urai(["Hak Suara Setelah", ": 5,00%"]) is None


# ---------------------------------------------------------------------------
# Pemakai hilir tidak boleh meledak karena perubahan None
# ---------------------------------------------------------------------------

def test_pembagian_akumulasi_distribusi_tahan_perubahan_None():
    """`None > 0` itu TypeError di Python 3. Satu filing yang tidak
    terbaca tidak boleh menjatuhkan seluruh halaman."""
    import web.app as app_module

    items = [
        {"kode": "A", "jenis": "beli", "perubahan": 2.0},
        {"kode": "B", "jenis": "beli", "perubahan": None},     # tak diketahui
        {"kode": "C", "jenis": "jual", "perubahan": -1.0},
        {"kode": "D", "jenis": "lain", "perubahan": 0.0},
    ]
    akum, dist, aksi = app_module._split_x15_items(items)
    assert [x["kode"] for x in akum] == ["A"]
    assert [x["kode"] for x in dist] == ["C"]
    # Yang tidak diketahui arahnya TIDAK boleh masuk akumulasi/distribusi --
    # menempatkannya di salah satu berarti mengaku tahu arahnya.
    assert {x["kode"] for x in aksi} == {"B", "D"}
