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
    """detect_harmonic harus menerima potongan yang berhenti DI BAR ITU.
    Memberinya seluruh df akan membuat pola yang baru terbentuk minggu
    depan terlihat sudah ada hari ini -- dan hasilnya akan tampak
    cemerlang justru karena salah."""
    assert "df.iloc[:i + 1]" in _src()


def test_jeda_antar_sampel_sepanjang_horizon():
    """PER SETUP, bukan per hari. Satu keadaan yang bertahan dua minggu
    harus dihitung SEKALI. Jebakan ini sudah menggigit proyek ini
    berkali-kali, dan ia selalu melebih-lebihkan."""
    src = _src()
    assert "jeda[nama] = i + HORIZON" in src
    assert "if i < jeda[nama]" in src


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
