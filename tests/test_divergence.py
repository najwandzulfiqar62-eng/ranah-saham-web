"""Deteksi pemulihan-setelah-jatuh (divergence RSI).

Fitur ini lahir dari pengukuran yang BERTENTANGAN dengan apa yang dijual
aplikasi lain, jadi yang diuji di sini bukan cuma "kodenya jalan" melainkan
"aturannya tetap seperti yang diukur".

Dua jebakan yang pernah membuat angka saya sendiri salah, dan karena itu
diuji paling ketat:

  1. MENGINTIP MASA DEPAN. Dasar baru bisa disebut dasar sesudah beberapa
     bar berikutnya terbukti lebih tinggi. Mendeteksinya pada hari kejadian
     memakai informasi yang belum ada. Ini pengulangan pelajaran NR7 --
     sinyal yang menyala dari bar sesi berjalan, separuhnya artefak.

  2. SATU SETUP TERHITUNG BERKALI-KALI. Pengukuran pertama saya melaporkan
     86,2% naik; angka sebenarnya 80% dari 10 setup, bukan 86% dari 80.
     Sepasang pivot bertahan belasan bar, dan tiap bar terhitung ulang.
"""
import pytest

from core.divergence import (JEDA_KANAN, MAKS_JATUH_PCT, MIN_JATUH_PCT,
                             cari_setup, pivot_low, urutkan)


def _rangkai(harga: list, rsi: list | None = None, mulai="2026-01-01"):
    """(tanggal, harga, rsi) sepanjang `harga`. RSI datar kalau tak diberi."""
    import datetime as dt

    d0 = dt.date.fromisoformat(mulai)
    tgl = [(d0 + dt.timedelta(days=i)).isoformat() for i in range(len(harga))]
    return tgl, harga, (rsi if rsi is not None else [50.0] * len(harga))


def _dua_dasar(h1=100.0, h2=91.0, r1=30.0, r2=38.0, jarak=12, ekor=5,
               awal=30, kode="TEST"):
    # awal=30 supaya deretnya lewat penjaga panjang minimum di
    # cari_setup (40 bar) -- RSI 14 butuh pemanasan, dan deret yang
    # lebih pendek dari itu memang tidak layak dinilai.
    """Deret dengan DUA dasar yang jelas: dasar kedua lebih rendah, RSI-nya
    lebih tinggi. Bentuk minimum yang memenuhi syarat divergence."""
    harga, rsi = [], []
    # Pembuka datar yang tinggi, supaya dasar pertama benar-benar dasar.
    harga += [h1 * 1.25] * awal
    rsi += [50.0] * awal
    harga += [h1]              # dasar 1
    rsi += [r1]
    naik = max(1, jarak - 1)
    harga += [h1 * 1.18] * naik
    rsi += [48.0] * naik
    harga += [h2]              # dasar 2
    rsi += [r2]
    harga += [h2 * 1.12] * ekor
    rsi += [45.0] * ekor
    return (*_rangkai(harga, rsi), kode)


# ---------------------------------------------------------------------------
# 1. Tidak boleh mengintip masa depan
# ---------------------------------------------------------------------------

def test_dasar_belum_sah_sebelum_jeda_kanan_lewat():
    """Pengulangan pelajaran NR7: sinyal yang menyala dari bar yang belum
    selesai. Dasar yang baru terbentuk kemarin BELUM dasar -- besok harga
    bisa menembusnya, dan yang kemarin terlihat dasar ternyata cuma
    perhentian di tengah jalan turun."""
    tgl, harga, rsi, kode = _dua_dasar(ekor=JEDA_KANAN - 1)
    assert cari_setup(kode, tgl, harga, rsi) is None, (
        "setup terdeteksi padahal dasar keduanya belum dikonfirmasi")


def test_dasar_sah_begitu_jeda_kanan_terpenuhi():
    tgl, harga, rsi, kode = _dua_dasar(ekor=JEDA_KANAN)
    assert cari_setup(kode, tgl, harga, rsi) is not None


def test_bar_terakhir_tidak_pernah_jadi_pivot():
    """Bar sesi berjalan belum selesai -- lownya masih bisa turun sampai
    penutupan. Syarat jeda kanan membuatnya mustahil jadi pivot, dan uji
    ini yang menjaganya tetap mustahil."""
    harga = [100.0] * 30 + [50.0]          # bar terakhir jauh terendah
    assert (len(harga) - 1) not in pivot_low(harga)


def test_pivot_low_menemukan_dasar_yang_benar():
    harga = [10, 9, 8, 7, 6, 7, 8, 9, 10, 11, 12]
    assert pivot_low(harga, kiri=3, kanan=3) == [4]


# ---------------------------------------------------------------------------
# 2. Satu setup = satu penanda tetap
# ---------------------------------------------------------------------------

def test_setup_id_TIDAK_berubah_walau_dipindai_hari_berbeda():
    """Inti jebakan yang menggelembungkan 10 setup jadi 80 kejadian.
    Penandanya memakai tanggal KEDUA DASARNYA, bukan tanggal deteksi."""
    t1, h1, r1, k = _dua_dasar(ekor=JEDA_KANAN)
    t2, h2, r2, _ = _dua_dasar(ekor=JEDA_KANAN + 4)      # dipindai 4 hari kemudian
    s1, s2 = cari_setup(k, t1, h1, r1), cari_setup(k, t2, h2, r2)
    assert s1 and s2
    assert s1.setup_id == s2.setup_id, "setup yang sama dianggap dua setup"
    assert s2.umur_bar > s1.umur_bar, "umurnya harus bertambah"


def test_setup_id_berbeda_untuk_emiten_berbeda():
    t, h, r, _ = _dua_dasar(ekor=JEDA_KANAN)
    assert cari_setup("BBCA", t, h, r).setup_id != cari_setup("TLKM", t, h, r).setup_id


# ---------------------------------------------------------------------------
# 3. Syarat divergence
# ---------------------------------------------------------------------------

def test_rsi_harus_lebih_tinggi_di_dasar_kedua():
    """Tanpa ini ia cuma "harga turun", bukan divergence."""
    t, h, r, k = _dua_dasar(r1=40.0, r2=32.0, ekor=JEDA_KANAN)
    assert cari_setup(k, t, h, r) is None


def test_harga_harus_lebih_rendah_di_dasar_kedua():
    t, h, r, k = _dua_dasar(h1=90.0, h2=99.0, ekor=JEDA_KANAN)
    assert cari_setup(k, t, h, r) is None


@pytest.mark.parametrize("jarak,ada", [(3, False), (12, True), (90, False)])
def test_jarak_antar_dasar_dibatasi(jarak, ada):
    """Terlalu dekat = derau yang sama dihitung dua kali. Terlalu jauh = dua
    kejadian yang sudah tidak berhubungan."""
    t, h, r, k = _dua_dasar(jarak=jarak, ekor=JEDA_KANAN)
    assert (cari_setup(k, t, h, r) is not None) is ada


def test_setup_terlalu_tua_dibuang():
    """Harga sudah jauh dari dasarnya; tidak ada lagi yang bisa
    ditindaklanjuti dari situ."""
    t, h, r, k = _dua_dasar(ekor=40)
    assert cari_setup(k, t, h, r) is None


# ---------------------------------------------------------------------------
# 4. Penyaring yang TERUKUR -- jatuh harga, bukan selisih RSI
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("jatuh_pct,kuat", [
    (2.0, False),    # terlalu dangkal: keunggulannya +0,06%, praktis nol
    (9.0, True),     # titik manis: 65,4% naik, unggul +4,05%
    (14.0, True),
    (25.0, False),   # pisau jatuh: keunggulannya BERBALIK, -5,35%
])
def test_hanya_jatuh_5_sampai_15_persen_yang_disebut_kuat(jatuh_pct, kuat):
    """Ini satu-satunya penyaring yang terbukti memisahkan menang dari
    kalah. Diukur 10 Okt 2026 pada 256 setup unik, 2 tahun."""
    t, h, r, k = _dua_dasar(h1=100.0, h2=100.0 * (1 - jatuh_pct / 100),
                            ekor=JEDA_KANAN)
    s = cari_setup(k, t, h, r)
    assert s is not None
    assert s.kuat is kuat


def test_ambang_jatuh_sesuai_yang_diukur():
    """Kalau suatu hari angkanya digeser tanpa pengukuran baru, uji ini
    yang memaksa penggesernya berhenti dan mengukur dulu."""
    assert (MIN_JATUH_PCT, MAKS_JATUH_PCT) == (5.0, 15.0)


def test_yang_kuat_diurut_lebih_dulu():
    """Diurut menurut kekuatan lalu kebaruan -- BUKAN menurut selisih RSI
    walau itu yang ditonjolkan aplikasi lain. Selisih RSI tidak memisahkan
    menang dari kalah (-0,35%), jadi mengurutkan dengannya akan menaruh
    yang terbaik di tengah daftar."""
    t1, h1, r1, _ = _dua_dasar(h2=91.0, ekor=JEDA_KANAN)        # kuat
    t2, h2, r2, _ = _dua_dasar(h2=99.0, r2=48.0, ekor=JEDA_KANAN)  # lemah
    a, b = cari_setup("KUAT", t1, h1, r1), cari_setup("LEMAH", t2, h2, r2)
    assert a.kuat and not b.kuat
    assert [s.kode for s in urutkan([b, a])] == ["KUAT", "LEMAH"]


# ---------------------------------------------------------------------------
# 5. Data cacat
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("harga,rsi", [
    ([], []),
    ([100.0] * 10, [50.0] * 10),                 # terlalu pendek
    ([100.0] * 50, [50.0] * 49),                 # panjang tak sama
])
def test_data_cacat_memulangkan_None_bukan_meledak(harga, rsi):
    tgl = [f"2026-01-{i % 28 + 1:02d}" for i in range(len(harga))]
    assert cari_setup("X", tgl, harga, rsi) is None


def test_harga_nol_tidak_membagi_dengan_nol():
    t, h, r, k = _dua_dasar(h1=0.0, h2=0.0, ekor=JEDA_KANAN)
    assert cari_setup(k, t, h, r) is None


def test_harga_datar_total_tidak_menghasilkan_setup():
    tgl, harga, rsi = _rangkai([100.0] * 60)
    assert cari_setup("X", tgl, harga, rsi) is None
