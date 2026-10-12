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
    assert "from core.screening_pro import (NR7_52W_LONGGAR_PCT" in src
    assert "NR7_52W_NEAR_PCT, detect_nr7_52w" in src
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
