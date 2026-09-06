"""Deteksi pola harmonic.

Diuji dengan pola yang SENGAJA dibangun dari rasio Fibonacci-nya, bukan data
acak yang kebetulan lolos: kalau detektornya benar, Gartley buatan harus
dikenali sebagai Gartley, dan bentuk yang rasionya salah tidak boleh lolos
hanya karena zig-zagnya mirip.
"""

import numpy as np
import pandas as pd
import pytest

from core.harmonic import detect_harmonic, ringkas_harmonic


def _df_dari_titik(titik: list[float], bar_per_kaki: int = 12) -> pd.DataFrame:
    """Bangun OHLC yang bergerak lurus dari satu titik ke titik berikutnya.

    Tiap kaki diberi cukup bar supaya pivotnya terdeteksi detect_swing_points
    (butuh 5 bar kiri & kanan).
    """
    # Kaki AWALAN menuju X. Tanpa ini X berada di bar pertama dan TIDAK
    # pernah terdeteksi sebagai pivot -- detect_swing_points butuh 5 bar di
    # kiri. Arahnya otomatis benar untuk bullish maupun bearish: titiknya
    # ditaruh di seberang A, jadi X selalu jadi puncak/lembah sungguhan.
    awalan = titik[0] + 0.3 * (titik[1] - titik[0])
    titik = [awalan] + list(titik)

    harga = []
    for i in range(len(titik) - 1):
        harga += list(np.linspace(titik[i], titik[i + 1], bar_per_kaki, endpoint=False))
    harga.append(titik[-1])
    # Ekor datar supaya pivot terakhir punya bar kanan yang cukup.
    harga += [titik[-1]] * 8
    h = np.array(harga, dtype=float)
    return pd.DataFrame({
        "Open": h, "High": h + 0.5, "Low": h - 0.5, "Close": h,
        "Volume": np.full(len(h), 1_000_000),
    }, index=pd.bdate_range(end=pd.Timestamp("2026-09-04"), periods=len(h)))


def _gartley_bullish() -> list[float]:
    """X-A-B-C-D dengan rasio Gartley: AB=0.618 XA, BC=0.5 AB, CD=1.4 BC,
    dan AD = 0.786 XA."""
    X, A = 100.0, 200.0
    xa = A - X
    B = A - 0.618 * xa                    # 138.2
    ab = A - B
    C = B + 0.5 * ab                      # 169.1
    D = A - 0.786 * xa                    # 121.4
    return [X, A, B, C, D]


def test_gartley_bullish_dikenali_dengan_titik_dan_rasionya():
    df = _df_dari_titik(_gartley_bullish())
    hasil = detect_harmonic(df)
    assert hasil, "pola Gartley yang dibangun dari rasionya sendiri harus terdeteksi"
    p = hasil[0]
    assert p["pola"] == "Gartley"
    assert p["arah"] == "bullish"
    # Titik D = area pembalikan, harus dekat 0.786 dari XA.
    assert p["prz"] == pytest.approx(121.4, abs=3)
    assert [t["label"] for t in p["titik"]] == ["X", "A", "B", "C", "D"]
    assert p["rasio"]["AB/XA"] == pytest.approx(0.618, abs=0.06)
    assert p["rasio"]["AD/XA"] == pytest.approx(0.786, abs=0.06)


def test_bentuk_zigzag_dengan_rasio_salah_tidak_diklaim_sebagai_pola():
    """Zig-zag saja tidak cukup. Kalau rasionya jauh dari pola mana pun,
    mengklaimnya sebagai harmonic lebih berbahaya daripada diam."""
    # AB cuma 15% dari XA, CD nyaris rata -- tidak cocok pola mana pun.
    df = _df_dari_titik([100.0, 200.0, 185.0, 190.0, 187.0])
    assert detect_harmonic(df) == []


def test_arah_bearish_terbaca_saat_pola_terbalik():
    X, A = 200.0, 100.0
    xa = X - A
    B = A + 0.618 * xa
    ab = B - A
    C = B - 0.5 * ab
    D = A + 0.786 * xa
    hasil = detect_harmonic(_df_dari_titik([X, A, B, C, D]))
    assert hasil and hasil[0]["arah"] == "bearish"
    assert hasil[0]["pola"] == "Gartley"


def test_data_terlalu_pendek_menghasilkan_kosong_bukan_error():
    df = _df_dari_titik([100.0, 120.0], bar_per_kaki=5)
    assert detect_harmonic(df) == []
    assert detect_harmonic(None) == []


def test_ringkasan_menyebut_pola_arah_dan_area_pembalikan():
    df = _df_dari_titik(_gartley_bullish())
    teks = ringkas_harmonic(detect_harmonic(df))
    assert "Gartley" in teks and "bullish" in teks
    assert "area pembalikan" in teks
    assert ringkas_harmonic([]) == "Tidak ada pola harmonic yang terdeteksi."
