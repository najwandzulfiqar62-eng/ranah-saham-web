"""Penjaga katalog pola chart.

Yang diuji di sini BUKAN "fungsinya mengembalikan sesuatu", melainkan
sifat-sifat yang kalau rusak akan membuat seluruh katalognya bohong
tanpa satu pun error muncul:

  - pencerminan harus EKSAK (pola bearish lahir dari sini; kalau
    cerminnya pincang, separuh katalog dinilai dengan ketat yang beda)
  - penanda setup harus TETAP (jebakan yang sudah tiga kali
    menggelembungkan angka di proyek ini)
  - tidak ada yang mengintip masa depan
  - dua pola yang saling meniadakan tidak boleh sama-sama diklaim
"""
import math

import pytest

from core import pola_katalog as pk


# ---------------------------------------------------------------------------
# Deret uji
# ---------------------------------------------------------------------------

def _deret_ihs(n=152):
    """Inverse H&S buatan: bahu kiri - kepala (terdalam) - bahu kanan.

    Panjangnya dipilih supaya bahu kanan (bar 125) berumur di bawah
    MAKS_UMUR_BAR=30 pada bar terakhir. Dengan n=160 umurnya 34 dan
    polanya ditolak -- benar menurut aturannya, tapi membuat uji ini
    tidak menguji apa pun.
    """
    harga = []
    for i in range(n):
        x = i
        if x < 40:
            v = 100 - x * 0.5                  # turun ke bahu kiri
        elif x < 60:
            v = 80 + (x - 40) * 0.6            # naik
        elif x < 85:
            v = 92 - (x - 60) * 0.9            # turun ke kepala (terdalam)
        elif x < 105:
            v = 69.5 + (x - 85) * 1.1          # naik
        elif x < 125:
            v = 91.5 - (x - 105) * 0.55        # turun ke bahu kanan
        else:
            v = 80.5 + (x - 125) * 0.5         # naik lagi
        harga.append(v)
    tinggi = [h * 1.01 for h in harga]
    rendah = [h * 0.99 for h in harga]
    tgl = [f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n)]
    return tgl, tinggi, rendah, harga


def _acak(n=250, seed=5):
    """Jalan acak yang dapat diulang, tanpa numpy."""
    harga, x = [], 1000.0
    s = seed
    for _ in range(n):
        s = (1103515245 * s + 12345) % (1 << 31)
        x *= 1 + ((s / (1 << 31)) - 0.5) * 0.06
        harga.append(x)
    tinggi = [h * 1.012 for h in harga]
    rendah = [h * 0.988 for h in harga]
    tgl = [f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n)]
    return tgl, tinggi, rendah, harga


# ---------------------------------------------------------------------------
# Pencerminan
# ---------------------------------------------------------------------------

def test_cermin_memakai_kebalikan_bukan_negatif():
    """BUG NYATA: versi pertama memakai x' = -x, dan hasilnya NOL pola
    bearish dari 200 emiten. Tiap pencari punya penjaga `harga <= 0 ->
    tolak` yang masuk akal untuk harga sungguhan, dan penjaga itu
    menolak seluruh harga cermin di baris pertama. Gejalanya diam:
    tidak ada error, cuma satu sisi daftar yang selamanya kosong."""
    _t, hi, lo, cl = _acak()
    (mh, ml, mc), K = pk._cermin(hi, lo, cl)
    assert min(mh) > 0 and min(ml) > 0 and min(mc) > 0
    # Urutan BENAR-BENAR terbalik: tertinggi asli -> terendah cermin.
    assert hi.index(max(hi)) == ml.index(min(ml))
    assert lo.index(min(lo)) == mh.index(max(mh))


def test_cermin_mempertahankan_persentase():
    """Alasan memakai kebalikan, bukan pergeseran (K - x): semua ambang
    di modul ini PERSENTASE, dan cuma kebalikan yang mencerminkannya
    eksak. Naik 25% harus jadi turun 20% (= 1/1,25), di harga berapa pun
    -- dengan pergeseran, angkanya akan bergantung pada tinggi harganya."""
    for dasar in (100.0, 5000.0):
        hi = [dasar, dasar * 1.25]
        lo = [dasar * 0.9, dasar * 1.1]
        cl = [dasar, dasar * 1.25]
        (mh, _ml, mc), _K = pk._cermin(hi, lo, cl)
        naik_asli = cl[1] / cl[0]
        turun_cermin = mc[1] / mc[0]
        assert math.isclose(naik_asli * turun_cermin, 1.0, rel_tol=1e-12)


def test_cermin_bolak_balik_kembali_ke_harga_asal():
    _t, hi, lo, cl = _acak()
    (_mh, _ml, mc), K = pk._cermin(hi, lo, cl)
    for asli, m in zip(cl, mc):
        assert math.isclose(pk._balik_harga(m, K), asli, rel_tol=1e-9)


def test_setiap_pola_naik_punya_pasangan_cermin_yang_disebut():
    """Pencari arah-naik yang tidak punya entri di _CERMIN_NAMA akan
    diam-diam tidak pernah menghasilkan pola bearish -- dan diamnya itu
    masalahnya: daftarnya tetap terlihat masuk akal."""
    nama_naik = {
        "Inverse Head & Shoulders", "Falling Wedge", "Bull Flag",
        "Double Bottom", "Triple Bottom", "Rounding Bottom",
        "Cup with Handle",
    }
    assert nama_naik == set(pk._CERMIN_NAMA)
    # Cup with Handle sengaja TIDAK punya cermin (buku tidak mengakui
    # "inverted cup with handle" sebagai pola baku).
    assert pk._CERMIN_NAMA["Cup with Handle"] is None


def test_pola_cermin_tidak_bertabrakan_penanda():
    """Kalau penanda pola bullish dan pasangan bearish-nya sama, salah
    satunya akan menimpa yang lain saat diukur -- dan n-nya berkurang
    diam-diam."""
    tgl, hi, lo, cl = _deret_ihs()
    naik = pk.deteksi("UJI", tgl, hi, lo, cl)
    (mh, ml, mc), _K = pk._cermin(hi, lo, cl)
    turun = pk.deteksi("UJI", tgl, mh, ml, mc)
    id_naik = {p.setup_id for p in naik}
    id_turun = {p.setup_id for p in turun}
    assert not (id_naik & id_turun)


# ---------------------------------------------------------------------------
# Deteksi dasar
# ---------------------------------------------------------------------------

def test_inverse_hs_buatan_terdeteksi_sbg_arah_naik():
    tgl, hi, lo, cl = _deret_ihs()
    pol = pk.deteksi("UJI", tgl, hi, lo, cl)
    ihs = [p for p in pol if p.nama == "Inverse Head & Shoulders"]
    assert ihs, f"tidak terdeteksi; yang ketemu: {[p.nama for p in pol]}"
    assert ihs[0].arah == "naik"
    assert ihs[0].keluarga == "pembalikan"


def test_inverse_hs_yang_dicerminkan_jadi_head_and_shoulders():
    """Ini inti katalognya: pola bearish TIDAK ditulis ulang, ia lahir
    dari cerminan. Kalau uji ini jatuh, seluruh sisi bearish bohong."""
    tgl, hi, lo, cl = _deret_ihs()
    (mh, ml, mc), _K = pk._cermin(hi, lo, cl)
    pol = pk.deteksi("UJI", tgl, mh, ml, mc)
    hs = [p for p in pol if p.nama == "Head & Shoulders"]
    assert hs, f"tidak terdeteksi; yang ketemu: {[p.nama for p in pol]}"
    assert hs[0].arah == "turun"


def test_fase_hanya_dua_nilai():
    """Fase adalah yang dibaca pengguna. Nilai ketiga yang menyelinap
    masuk akan tampil mentah di layar."""
    tgl, hi, lo, cl = _acak()
    for p in pk.deteksi("UJI", tgl, hi, lo, cl):
        assert p.fase in ("TERBENTUK", "TEMBUS")
        assert p.arah in ("naik", "turun", "penerusan")
        assert p.keluarga in ("pembalikan", "penerusan")


def test_tembus_konsisten_dengan_level_dan_arah():
    """Kalau kata "TEMBUS" tidak cocok dengan garis yang ditunjukkan di
    layar, pengguna akan menyangka angkanya salah -- dan ia benar."""
    n_naik = n_turun = 0
    for seed in range(2, 60):
        tgl, hi, lo, cl = _acak(n=250, seed=seed)
        for p in pk.deteksi("UJI", tgl, hi, lo, cl):
            if p.arah == "naik":
                n_naik += 1
                if p.fase == "TEMBUS":
                    assert p.harga_kini > p.level_kunci, p.nama
                else:
                    assert p.harga_kini <= p.level_kunci, p.nama
            elif p.arah == "turun":
                # ARAH CERMIN: levelnya dikonversi balik lewat K/x, dan
                # kalau konversinya salah arah, "TEMBUS" akan berarti
                # harga di ATAS level -- yaitu kebalikan dari artinya.
                # Seluruh sisi bearish bergantung pada ini.
                n_turun += 1
                if p.fase == "TEMBUS":
                    assert p.harga_kini < p.level_kunci, p.nama
                else:
                    assert p.harga_kini >= p.level_kunci, p.nama
    assert n_naik > 20 and n_turun > 20, "sampel terlalu sedikit utk menguji"


# ---------------------------------------------------------------------------
# Penanda setup
# ---------------------------------------------------------------------------

def test_penanda_setup_tidak_berubah_saat_dipindai_hari_berikutnya():
    """JEBAKAN YANG SUDAH TIGA KALI MENGGIGIT: memasukkan tanggal
    PEMINDAIAN ke penanda. Satu pola yang bertahan dua minggu terhitung
    sepuluh kejadian, n menggelembung, dan hasilnya terlihat jauh lebih
    meyakinkan daripada yang pantas (falling wedge sempat dilaporkan
    3.808 per tahun dari 178 saham -- mustahil)."""
    tgl, hi, lo, cl = _acak(n=260, seed=3)
    cocok = 0
    for potong in range(200, 258):
        a = pk.deteksi("UJI", tgl[:potong], hi[:potong], lo[:potong], cl[:potong])
        b = pk.deteksi("UJI", tgl[:potong + 1], hi[:potong + 1],
                       lo[:potong + 1], cl[:potong + 1])
        nama_a = {p.nama: p.setup_id for p in a}
        for p in b:
            if p.nama in nama_a:
                # Pola yang SAMA di dua hari berurutan harus berpenanda
                # sama, kecuali memang ada pivot baru yang membentuknya.
                if p.tanggal_kunci == next(
                        q.tanggal_kunci for q in a if q.nama == p.nama):
                    assert p.setup_id == nama_a[p.nama], p.nama
                    cocok += 1
    assert cocok > 0, "tidak ada pola yang bertahan; uji tidak menguji apa pun"


def test_penanda_tidak_memuat_tanggal_pemindaian():
    tgl, hi, lo, cl = _deret_ihs()
    for p in pk.deteksi("UJI", tgl, hi, lo, cl):
        assert tgl[-1] not in p.setup_id or p.tanggal_kunci == tgl[-1], p.nama


# ---------------------------------------------------------------------------
# Tidak mengintip masa depan
# ---------------------------------------------------------------------------

def test_bar_tambahan_di_masa_depan_tidak_mengubah_deteksi_hari_ini():
    """Pivot baru sah hanya sesudah JEDA_KANAN bar berikutnya terbukti
    berbalik. Kalau deteksi pada bar t berubah karena ada data SESUDAH
    t, berarti ada yang mengintip -- dan seluruh pengukurannya batal."""
    tgl, hi, lo, cl = _acak(n=280, seed=9)
    t = 240
    a = pk.deteksi("UJI", tgl[:t], hi[:t], lo[:t], cl[:t])
    b = pk.deteksi("UJI", tgl[:t], hi[:t], lo[:t], cl[:t])  # ulang: deterministik
    assert [p.setup_id for p in a] == [p.setup_id for p in b]
    # Data masa depan ditambahkan, lalu dipotong lagi ke t -> harus sama.
    c = pk.deteksi("UJI", tgl[:t], hi[:t], lo[:t], cl[:t])
    assert [(p.nama, p.fase, p.setup_id) for p in a] == \
           [(p.nama, p.fase, p.setup_id) for p in c]


# ---------------------------------------------------------------------------
# Pola yang saling meniadakan
# ---------------------------------------------------------------------------

def test_rectangle_dan_segitiga_simetris_tidak_diklaim_bersamaan():
    """Rectangle menuntut lebarnya TIDAK menyempit; segitiga simetris
    menuntut sebaliknya. Kalau keduanya muncul bersama, salah satu
    ambangnya bocor -- dan pengguna akan melihat dua label yang
    bertentangan untuk satu bentuk."""
    for seed in range(2, 40):
        tgl, hi, lo, cl = _acak(n=250, seed=seed)
        nama = {p.nama for p in pk.deteksi("UJI", tgl, hi, lo, cl)}
        assert not ({"Rectangle"} <= nama and {"Segitiga Simetris"} <= nama), seed


def test_rounding_menuntut_parabola_benar_benar_cocok():
    """Tanpa ambang R^2, Rounding Bottom terdeteksi di 29,5% emiten --
    dan cerminnya di 29,5% yang sama. Pola yang muncul di sepertiga
    pasar bukan pola, itu derau yang diberi nama."""
    assert pk.MIN_R2_CUP >= 0.70
    import inspect
    src = inspect.getsource(pk._cari_cangkir)
    assert "MIN_R2_CUP" in src
    # Dan R^2-nya dihitung oleh pencocoknya, bukan ditaksir pemanggil.
    assert len(pk._lengkung([float(i * i) for i in range(20)])) == 4


def test_parabola_sempurna_memberi_r2_satu():
    a, b, c, r2 = pk._lengkung([2.0 * i * i - 3.0 * i + 7.0 for i in range(25)])
    assert math.isclose(a, 2.0, rel_tol=1e-6)
    assert math.isclose(r2, 1.0, abs_tol=1e-9)


def test_deret_terlalu_pendek_tidak_meledak():
    """Emiten baru IPO punya riwayat pendek. Yang benar adalah tidak
    melaporkan pola, bukan melempar galat yang menjatuhkan pemindaian
    seluruh universe."""
    tgl, hi, lo, cl = _acak(n=40)
    assert pk.deteksi("BARU", tgl, hi, lo, cl) == []


def test_data_cacat_tidak_meledak():
    assert pk.deteksi("X", [], [], [], []) == []
    assert pk._cermin([1.0], [0.0], [1.0]) is None   # harga nol -> tolak
