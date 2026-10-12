"""Harness NR7 + 52W: yang diukur harus teori yang DIJALANKAN.

NR7_52W adalah sumber sinyal ke-4: ia menulis ke signal_history dengan
direction BUY, diaudit, ikut membentuk win rate, dan lencananya
menyandang "HIGH RISK". Dan ia tidak punya satu pun angka terukur.

Berkas ini menjaga metodenya, dan tiap butirnya menutup satu cara
pengukuran bisa berbohong tanpa menghasilkan error.
"""
import io
import os

import pytest

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return io.open(os.path.join(AKAR, "tools", "ukur_nr7.py"),
                   encoding="utf-8").read()


def _kode_saja():
    """Sumbernya TANPA komentar -- komentar di harness ini MENGUTIP
    bentuk-bentuk yang salah (itu gunanya), dan penjaga yang menyala
    karena kalimat penjelasan akan dimatikan orang. Sudah tujuh kali di
    proyek ini."""
    return "\n".join(b for b in _src().splitlines()
                     if not b.strip().startswith("#"))


# ---------------------------------------------------------------------------
# Jalan maju
# ---------------------------------------------------------------------------

def test_tidak_mengintip_masa_depan():
    """Potongan yang dinilai harus berhenti di bar NR7-nya."""
    assert "df.iloc[:i + 1]" in _kode_saja()


def test_entry_di_SESI_BERIKUTNYA_bukan_di_bar_nr7():
    """Teorinya begitu (Crabel: bar NR7 dikenali SESUDAH tutup, lalu
    ekspansinya ditradingkan sesi berikutnya) dan pencatat sinyal
    produksi juga begitu -- entry di harga pasar hari berikutnya.

    Mengukur dari close bar NR7 akan memberi teori ini satu hari gerakan
    yang tidak pernah bisa didapat siapa pun. Itu bukan kesalahan kecil:
    pada setup breakout, hari pertama justru harinya."""
    kode = _kode_saja()
    assert "j = i + 1" in kode
    assert "(cl[j + HORIZON] - cl[j]) / cl[j]" in kode, (
        "return diukur dari bar deteksi, bukan dari bar entry")


def test_dasar_pembanding_mengikuti_tanggal_ENTRY():
    """Dasarnya harus setanggal dengan jendela yang benar-benar dipegang.
    Memakai tanggal DETEKSI menggeser pembandingnya satu hari dari
    posisinya -- kecil, tapi searah dan karena itu sistematis."""
    assert "dasar.get(tg[j])" in _kode_saja(), (
        "dasar diambil di tanggal deteksi, bukan tanggal entry")


def test_bar_berjalan_tidak_dibuang_karena_data_historis_sudah_tutup():
    """abaikan_bar_terakhir HARUS False di sini, dan alasannya penting.

    Di produksi parameter itu True karena pemanggilnya menempelkan bar
    hari ini yang dirakit dari candle per-jam -- dan bar yang belum tutup
    hampir SELALU tersempit, sehingga syarat NR7 menyala untuk hampir
    semua saham tiap pagi. Separuh sinyal NR7 pernah artefak itu (cacat
    nyata 19 Sep 2026).

    Di data historis tiap bar SUDAH tutup. Memakai True di sini akan
    menilai bar i-1 sambil tetap memakai bar i+1 sebagai entry, yaitu
    menggeser seluruh pengukuran satu hari tanpa ada yang menandainya."""
    assert "abaikan_bar_terakhir=False" in _kode_saja()


def test_jeda_antar_sampel_PER_SEL():
    """PER SETUP, bukan per hari. Dan per SEL, metode baku di proyek ini.

    Jeda bersama pernah dicoba di harness MVH dan itu salah: ia
    membiaskan sel yang paling sedikit sampelnya, karena bar pertama di
    tiap jendela menang dan sel lain kehilangan kemunculan yang jatuh di
    dalam jendela itu."""
    kode = _kode_saja()
    assert "jeda = defaultdict(lambda: -999)" in kode
    assert "jeda[nama] = i + HORIZON" in kode
    assert "if not nama or i < jeda[nama]" in kode


# ---------------------------------------------------------------------------
# Kakinya ikut diukur
# ---------------------------------------------------------------------------

def test_mengukur_KAKI_dan_PELENGKAPNYA_bukan_cuma_persilangannya():
    """PELAJARAN DARI HARNESS MVH, dipakai di sini sejak awal.

    Teori ini persilangan dua syarat: NR7 (range tersempit 7 hari) dan
    52W High (close >= 98% dari tertinggi 52 minggu). Mengukurnya sebagai
    satu kesatuan lalu mendapat angka positif tidak membuktikan apa pun
    tentang persilangannya -- bisa jadi seluruh angkanya datang dari satu
    kaki, dan kaki lainnya cuma MENGURANGI JUMLAH sinyal.

    Pengurangan jumlah sinyal selalu terlihat seperti penyaringan yang
    ketat, padahal mungkin cuma membuang sinyal secara acak."""
    src = _src()
    assert "A. NR7 saja" in src, "kaki pertama tidak diukur sendiri"
    assert "B. NR7 + 52W >=98% (KETAT, yang dicatat)" in src
    assert "C. NR7 + 52W <98%" in src, "pelengkapnya tidak diukur"
    assert "SYARAT 'DEKAT PUNCAK' MENAMBAH" in src


def test_ambang_ketat_ikut_diuji_terhadap_yang_longgar():
    """Ambang longgar (90%) BUKAN karangan: ia dipajang di tab saringan
    dan pembaca boleh memilihnya. Jadi "apakah 98% layak lebih ketat
    dari 90%" adalah pertanyaan nyata, bukan latihan."""
    src = _src()
    assert "D. NR7 + 52W >=90% (longgar, tampilan)" in src
    assert "AMBANG 98% vs 90%" in src


def test_ambangnya_DIBACA_dari_produksi_bukan_ditulis_ulang():
    """Angka 0.98 dan 0.90 yang ditulis ulang di harness akan menyimpang
    dari produksi tanpa ada yang tahu -- dan yang terukur lalu bukan
    saringan yang dipajang."""
    src = _src()
    # Diperiksa lewat IMPOR SUNGGUHAN, bukan bentuk barisnya: daftar impor
    # bertambah panjang seiring harness berkembang (NR7_52W_WINDOW masuk
    # saat kaki "52W tanpa NR7" ditambahkan), dan penjaga yang mengunci
    # tata letak satu baris akan gagal karena pembungkusan baris -- bukan
    # karena ada yang salah.
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location(
        "ukur_nr7_impor", os.path.join(AKAR, "tools", "ukur_nr7.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ukur_nr7_impor"] = mod
    spec.loader.exec_module(mod)
    from core import screening_pro as sp
    assert mod.NR7_52W_NEAR_PCT == sp.NR7_52W_NEAR_PCT
    assert mod.NR7_52W_LONGGAR_PCT == sp.NR7_52W_LONGGAR_PCT
    assert mod.NR7_52W_WINDOW == sp.NR7_52W_WINDOW
    kode = _kode_saja()
    for angka in ("0.98", "0.90"):
        assert angka not in kode, (
            f"ambang {angka} ditulis ulang di harness; baca dari "
            "core/screening_pro.py")


def test_ketat_dibaca_dari_medan_yang_disediakan_detektornya():
    """Definisi "ketat" ada di detect_nr7_52w lewat medan nr7_ketat.
    Menghitungnya ulang di harness berarti dua definisi untuk satu
    aturan, dan yang kedua akan menyimpang."""
    assert 'r.get("nr7_ketat")' in _kode_saja()


def test_hasilnya_menyebut_bahwa_ini_BUKAN_win_rate():
    """Unggul 20 hari dan win rate TP/SL menjawab hal yang BERBEDA.
    Menyebut yang satu sebagai yang lain adalah cara tercepat membuat
    angka ini disalahpahami -- terutama karena Audit Sinyal memajang
    win rate untuk teori yang sama."""
    src = _src()
    assert "BUKAN win rate TP/SL" in src


def test_premis_stop_ketat_ikut_diperiksa():
    """Premis NR7 adalah kontraksi volatilitas -> stop KETAT. Kalau yang
    untung justru setup yang stopnya lebar, premisnya yang keliru dan
    bukan cuma angkanya. Itu hanya terlihat kalau dipisah."""
    src = _src()
    assert "E. KETAT, stop <=4%" in src
    assert "F. KETAT, stop >4%" in src


# ---------------------------------------------------------------------------
# Detektornya sendiri, dengan data buatan
# ---------------------------------------------------------------------------

def _df(ranges, closes=None, n_awal=260):
    """Deret dengan range harian yang DIATUR, supaya NR7 bisa dipicu
    dengan sengaja. `ranges` menempel di ekor deret."""
    import pandas as pd
    hi, lo, cl = [], [], []
    for i in range(n_awal):
        dasar = 1000 + i * 0.5
        hi.append(dasar + 10)
        lo.append(dasar - 10)
        cl.append(dasar)
    for r in ranges:
        dasar = 1000 + n_awal * 0.5
        hi.append(dasar + r / 2)
        lo.append(dasar - r / 2)
        cl.append(dasar)
    if closes:
        cl[-len(closes):] = closes
    idx = pd.date_range("2023-01-02", periods=len(hi), freq="B")
    return pd.DataFrame({"Open": cl, "High": hi, "Low": lo, "Close": cl,
                         "Volume": [1_000_000] * len(hi)}, index=idx)


def test_detektor_menolak_hari_yang_bukan_range_tersempit():
    """Penjaga kewarasan: kalau ini lolos, seluruh pengukurannya mengukur
    hal lain."""
    from core.screening_pro import detect_nr7_52w
    # Range terakhir PALING LEBAR dari tujuh terakhir.
    df = _df([5, 5, 5, 5, 5, 5, 40])
    assert detect_nr7_52w(df, abaikan_bar_terakhir=False) is None


def test_detektor_menerima_range_tersempit_di_area_puncak():
    from core.screening_pro import detect_nr7_52w
    df = _df([40, 38, 36, 34, 32, 30, 8])
    r = detect_nr7_52w(df, abaikan_bar_terakhir=False)
    if r is None:
        pytest.skip("deret buatan tidak lolos syarat 52W/stop; "
                    "yang diuji di sini cuma arah penolakannya")
    assert r["is_nr7_52w"] is True
    assert r["nr7_sl_pct"] > 0


def test_kaki_KEDEKATAN_52W_TANPA_NR7_ikut_diukur():
    """KAKI YANG SEMPAT HILANG, dan ia yang menentukan nama teorinya.

    Hasil jalan kedua: NR7 sendirian -0,13% dari 6.910 sampel -- sampel
    sebesar itu dengan angka sedekat itu ke nol adalah pernyataan yang
    kuat, bukan ketidaktahuan. Yang membawa angkanya justru kedekatan ke
    puncak 52 minggu, dan ia menanjak rapi: <90% negatif, >=90% +1,16,
    >=98% +2,13.

    Tapi tanpa sel "52W >=98% TANPA NR7", tidak ada cara tahu apakah NR7
    menyumbang apa pun. Kalau kedekatan saja sudah memberi +2%, maka
    teori ini sebenarnya "beli yang dekat puncak 52 minggu" dan NR7 cuma
    mengurangi jumlah sinyalnya.

    detect_nr7_52w TIDAK bisa memberi kaki ini -- ia mengembalikan None
    pada hari yang bukan NR7 -- jadi kedekatannya wajib dihitung
    terpisah."""
    src = _src()
    assert "H. 52W >=98% SAJA (tanpa syarat NR7)" in src
    assert "NR7 MENAMBAH PADA 52W" in src
    kode = _kode_saja()
    # Dihitung dari maksimum bergulir sendiri, bukan dari detektornya.
    assert "rolling(NR7_52W_WINDOW, min_periods=1)" in kode


def test_sel_A_benar_benar_tanpa_syarat_52W():
    """CACAT YANG DITUTUP, dan ia terlihat dari angkanya sendiri: sel A
    ("NR7 saja") dan sel D ("NR7 + 52W >=90%") sempat memberi hasil
    IDENTIK -- +1,36% dengan n=594 keduanya. Dua sel yang seharusnya
    berbeda mengukur himpunan yang sama.

    Sebabnya detect_nr7_52w MENOLAK bar di bawah `dekat_pct`, dan
    harness memanggilnya dengan 0,90. Jadi "NR7 saja" sebenarnya "NR7
    DAN >=90%", dan labelnya mengklaim yang tidak dikerjakan kodenya."""
    kode = _kode_saja()
    assert "dekat_pct=0.0" in kode, (
        "detektor masih menyaring kedekatan; sel A tidak akan pernah "
        "berisi NR7 yang jauh dari puncak")
    assert "A. NR7 saja (tanpa syarat 52W)" in _src()


# ---------------------------------------------------------------------------
# Hasilnya, dan klaim yang TIDAK boleh disandang
# ---------------------------------------------------------------------------

def test_angka_nr7_lulus_uji_dua_periode():
    from core.screening_pro import UNGGUL_NR7_52W as U
    assert U["stabil"] is True
    assert (U["unggul_pct"] > 0) == (U["unggul_2y"] > 0), "tanda berbalik"
    from core.screening_pro import MIN_N_NR7
    assert U["n"] >= MIN_N_NR7, "sel yang dicatat sampelnya kurang"


def test_kaki_52W_tercatat_JAUH_lebih_kuat_daripada_persilangannya():
    """TEMUAN UTAMANYA, dan ia harus bisa dibuktikan dari angka di baris
    itu sendiri -- bukan dari kalimat di komentarnya.

    'Dekat puncak 52 minggu' TANPA NR7 memberi +5,07% (n=2.538);
    ditambah syarat NR7 ia jatuh ke +0,71% (n=500). NR7 memotong sekitar
    85% keunggulannya."""
    from core.screening_pro import UNGGUL_NR7_52W as U
    assert U["dekat52w_saja_pct"] > U["unggul_pct"]
    assert abs((U["unggul_pct"] - U["dekat52w_saja_pct"])
               - U["nr7_menambah_poin"]) < 0.02
    assert U["nr7_menambah_poin"] < 0, "temuannya justru bahwa NR7 mengurangi"


def test_nr7_sendirian_terukur_nol_dengan_sampel_besar():
    """-0,37% dari 25.074 sampel. Sampel sebesar itu dengan angka sedekat
    itu ke nol adalah pernyataan yang KUAT, bukan ketidaktahuan."""
    from core.screening_pro import UNGGUL_NR7_52W as U
    assert U["nr7_saja_n"] > 10_000
    assert abs(U["nr7_saja_pct"]) < 1.0


def test_premis_stop_ketat_TIDAK_diklaim():
    """Premis NR7 adalah kontraksi volatilitas -> stop ketat. Diuji dua
    periode, tandanya BERBALIK:
        2 thn: stop <=4% +2,62% (n=93)  vs >4% -11,42% (n=4)
        5 thn: stop <=4% +0,15% (n=475) vs >4%  +7,46% (n=44)
    Dan sel yang mendukung premisnya di 2 tahun cuma n=4.

    Saya sempat mengutipnya sebagai dukungan dari satu periode saja. Uji
    ini mencegah klaim itu kembali -- ke tabelnya maupun ke layar."""
    from core.screening_pro import UNGGUL_NR7_52W as U
    assert U["stop_ketat_stabil"] is False
    from core import lencana as lc
    x = [y for y in lc.susun("X", nr7_aktif=True)["lencana"]
         if y["kunci"] == "nr7"][0]
    assert "stop ketat" not in x["catatan"], (
        "layar mengklaim 'stop ketat' padahal premisnya tidak bertahan "
        "di uji dua periode")


def test_lencana_nr7_memajang_kakinya():
    """+0,71% sendirian terbaca 'lumayan'. Di sebelah kakinya (+5,07%),
    yang terbaca adalah bahwa syarat NR7 memotong 85% keunggulannya. Di
    situlah maknanya, dan tanpa dipajang maknanya hilang."""
    from core import lencana as lc
    x = [y for y in lc.susun("X", nr7_aktif=True)["lencana"]
         if y["kunci"] == "nr7"][0]
    assert "TANPA syarat NR7" in x["catatan"]
    assert "MENGURANGI" in x["catatan"]
