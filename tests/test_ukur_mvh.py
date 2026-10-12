"""Harness MVH: yang diukur harus teori yang DIJALANKAN.

Pengukuran jalan-maju menuntut kriteria Minervini dihitung ulang di tiap
bar, dan menghitungnya dengan _score_minervini() satu bar demi satu bar
terlalu lambat untuk 786 emiten x ratusan bar. Jadi tools/ukur_mvh.py
punya versi VEKTOR-nya sendiri.

DI SITULAH BAHAYANYA. Dua implementasi dari satu aturan akan menyimpang,
dan simpangannya tidak menghasilkan error -- ia menghasilkan ANGKA, yang
lalu dipakai mengambil keputusan tentang teori yang sebenarnya tidak
diukur. Kalau ambang atau kriterianya berbeda sedikit saja, yang
terukur bukan saringan yang dipajang di Screener.

Berkas ini mengikat keduanya.
"""
import importlib.util
import os
import sys

import pandas as pd
import pytest

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _muat_harness():
    """Impor tools/ukur_mvh.py tanpa menjalankan main()."""
    jalur = os.path.join(AKAR, "tools", "ukur_mvh.py")
    spec = importlib.util.spec_from_file_location("ukur_mvh", jalur)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ukur_mvh"] = mod
    spec.loader.exec_module(mod)
    return mod


def _ohlc(n=400, bentuk="naik"):
    """Deret dengan bentuk yang berbeda-beda, supaya kriterianya tidak
    semuanya kebetulan terpenuhi atau semuanya gagal."""
    harga = []
    for i in range(n):
        if bentuk == "naik":
            v = 1000 * (1 + 0.8 * i / n)
        elif bentuk == "turun":
            v = 2000 * (1 - 0.5 * i / n)
        elif bentuk == "datar":
            v = 1000 + 12 * ((i % 40) - 20) / 20
        else:  # patah: naik lalu jatuh
            v = (1000 * (1 + 0.9 * i / n) if i < n * 0.7
                 else 1000 * 1.63 * (1 - 0.45 * (i - n * 0.7) / (n * 0.3)))
        harga.append(v)
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame({
        "Open": harga, "Close": harga,
        "High": [h * 1.005 for h in harga],
        "Low": [h * 0.995 for h in harga],
        "Volume": [1_000_000 + (i % 7) * 50_000 for i in range(n)],
    }, index=idx)


def _pasar(n=400, laju=0.25):
    harga = [1000 * (1 + laju * i / n) for i in range(n)]
    return pd.Series(harga, index=pd.date_range("2023-01-02", periods=n,
                                                freq="B"))


@pytest.mark.parametrize("bentuk", ["naik", "turun", "datar", "patah"])
def test_versi_vektor_cocok_dengan_produksi(bentuk):
    """criteria_met dari versi vektor harus SAMA dengan _score_minervini
    pada bar terakhir, untuk tiap bentuk deret.

    Kalau ini gagal, seluruh hasil tools/ukur_mvh.py batal -- ia mengukur
    saringan yang berbeda dari yang dijalankan aplikasi."""
    from core.screening_pro import _score_minervini
    mod = _muat_harness()

    df, pasar = _ohlc(bentuk=bentuk), _pasar()
    produksi = _score_minervini(df, "UJI", market_close=pasar)
    assert produksi is not None, "produksi gagal menilai; ujinya tak berarti"

    vektor = mod._minervini_vektor(df, pasar)
    assert int(vektor.iloc[-1]) == produksi["criteria_met"], (
        f"{bentuk}: vektor {int(vektor.iloc[-1])} vs "
        f"produksi {produksi['criteria_met']}")


def test_versi_vektor_cocok_di_BANYAK_bar_bukan_cuma_yang_terakhir():
    """Bar terakhir saja tidak cukup: pengukuran jalan-maju menilai
    RATUSAN bar, dan simpangan yang cuma muncul di tengah deret akan
    lolos dari uji yang memeriksa ujungnya."""
    from core.screening_pro import _score_minervini
    mod = _muat_harness()

    df, pasar = _ohlc(n=420, bentuk="patah"), _pasar(n=420)
    vektor = mod._minervini_vektor(df, pasar)
    diperiksa = 0
    for i in range(300, 420, 17):
        potong = df.iloc[:i + 1]
        p = _score_minervini(potong, "UJI", market_close=pasar.iloc[:i + 1])
        if p is None:
            continue
        diperiksa += 1
        assert int(vektor.iloc[i]) == p["criteria_met"], (
            f"bar {i}: vektor {int(vektor.iloc[i])} vs "
            f"produksi {p['criteria_met']}")
    assert diperiksa >= 5, "terlalu sedikit bar terperiksa; uji tak berarti"


# ---------------------------------------------------------------------------
# Metode
# ---------------------------------------------------------------------------

def _src():
    import io
    return io.open(os.path.join(AKAR, "tools", "ukur_mvh.py"),
                   encoding="utf-8").read()


def test_tidak_mengintip_masa_depan():
    """Potongan yang diberikan ke detect_harmonic harus BERHENTI di bar
    itu. Memberinya potongan yang melewati i akan membuat pola yang baru
    terbentuk minggu depan terlihat sudah ada hari ini -- dan hasilnya
    akan tampak cemerlang justru karena salah."""
    assert "df.iloc[awal:i + 1]" in _src()


def test_jendela_harmonic_sama_dengan_yang_dilihat_produksi():
    """CACAT YANG DIPERBAIKI. Versi pertama mengirim SELURUH riwayat
    sampai bar i -- pada periode 2 tahun itu ~490 bar. Produksi memberi
    detect_harmonic period="1y" (~245 bar).

    Akibatnya bukan cuma lambat (dan versi pertama memang tidak selesai
    dalam 2 jam): pola yang butuh 400 bar untuk terbentuk tidak akan
    PERNAH terlihat produksi, tapi terhitung di pengukuran. Yang terukur
    jadi bukan teori yang dijalankan."""
    mod = _muat_harness()
    assert 220 <= mod.EKOR <= 260, (
        f"EKOR={mod.EKOR}; produksi melihat ~245 bar (period='1y')")
    assert "awal = max(0, i - EKOR + 1)" in _src()


def test_jeda_antar_sampel_PER_SEL():
    """PER SETUP, bukan per hari. Satu keadaan yang bertahan dua minggu
    harus dihitung SEKALI.

    DAN JEDANYA PER SEL -- metode baku di proyek ini; ukur_pola,
    ukur_smc, dan ukur_fibo ketiganya begini.

    SATU JEDA BERSAMA PERNAH DICOBA DI SINI DAN ITU SALAH. Alasan yang
    dipakai waktu itu ("tumpang tindih antar-sel membuat return yang
    sama dihitung di kedua sisi") keliru menilai akibatnya: tumpang
    tindih antar-sel membuat kedua sampel BERKORELASI, dan itu soal uji
    keberartian, bukan bias -- rata-rata tiap selnya tetap tak berbias.

    Sementara jeda bersama JUSTRU membiaskan, dan membiaskan tepat sel
    yang paling sedikit sampelnya: dalam satu jendela 20 bar, bar
    PERTAMA yang lolos Minervini yang menang; kalau bar itu tidak punya
    harmonic ia tercatat C dan jendelanya melompat 20 bar, maka
    kemunculan harmonic tiga bar kemudian tidak pernah tersampel.
    Hasilnya B cuma n=15 -- artefak harness, bukan pengukuran."""
    src = _src()
    assert "jeda = defaultdict(lambda: -999)" in src
    assert "jeda[nama] = i + HORIZON" in src
    assert "if i < jeda[nama]" in src
    # Bentuk jeda-bersama tidak boleh kembali.
    assert "\n        jeda = -999" not in src, (
        "jeda bersama membiaskan sel B ke bawah; lihat docstring")


def test_harmonic_dihitung_di_TIAP_bar_yang_lolos_minervini():
    """Harus di tiap bar, bukan cuma di bar yang lolos jeda.

    Kalau detect_harmonic cuma dipanggil sesudah jeda, sel B kehilangan
    setiap kemunculan yang jatuh di dalam jendela sel C -- dan itu
    bukan penghematan, itu kehilangan data pada sel yang paling tipis.

    Yang menyelesaikan masalah 2 jam bukan ini, melainkan jendela 245
    bar dan universe 250 emiten."""
    src = _src()
    i_hm = src.index("detect_harmonic(df.iloc")
    i_jeda = src.index("jeda[nama] = i + HORIZON")
    assert i_hm < i_jeda, (
        "detect_harmonic dipanggil sesudah jeda; sel B akan kehilangan "
        "kemunculan yang jatuh di dalam jendela sel C")


def test_hasilnya_menyebut_bahwa_universenya_dibatasi():
    """Angkanya HANYA berlaku untuk emiten likuid. Saham sepi punya harga
    penutupan yang tidak mencerminkan harga yang bisa didapat, dan
    menyebut hasilnya berlaku umum akan menjanjikan yang tidak diuji."""
    src = _src()
    assert '"hanya_likuid": True' in src
    assert "HANYA emiten likuid" in src


def test_dasar_pembanding_per_tanggal():
    """Dasar tunggal untuk seluruh periode melebih-lebihkan teori yang
    kebetulan menyala di bulan-bulan bagus -- itu sudah membatalkan satu
    temuan di proyek ini."""
    src = _src()
    assert "dasar.get(tg[i])" in src
    assert "per_tgl" in src


def test_mengukur_pelengkapnya_juga():
    """Yang menentukan B vs C, bukan B vs nol. Tanpa C, angka positif
    pada B tidak bisa dibedakan dari "Minervini-nya yang bagus, harmonic
    cuma mengurangi jumlah sinyal"."""
    src = _src()
    assert "C. Minervini TANPA harmonic" in src
    assert "HARMONIC MENAMBAH" in src


def test_ambangnya_sama_dengan_produksi():
    src = _src()
    assert 'os.getenv("MINERVINI_MIN_KRITERIA", "7")' in src
    assert "MAKS_UMUR_D = 10" in src, (
        "umur pola harus sama dengan cache produksi "
        "(screener_harmonic:v3:luas:bullish:10)")
    assert 'arah") == "bullish"' in src, (
        "MVH memakai sisi bullish; mengukur sisi lain berarti mengukur "
        "teori yang tidak dijalankan")
