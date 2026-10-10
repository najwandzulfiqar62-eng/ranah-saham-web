"""Jarak stop yang menyesuaikan derau tiap saham.

Diukur 7 Okt 2026 pada 658 sinyal sungguhan: stop 3% itu 0,8x ATR harian
saham median (3,60%), dan kena 53,8% dari waktu. Ia tidak kena karena
analisisnya salah -- ia kena karena harinya hari biasa.

Yang diuji di sini bukan "rumusnya benar" melainkan "aturannya tetap
seperti yang diukur", plus keadaan-keadaan yang bisa membuatnya
menghasilkan rencana yang rugi bahkan ketika benar.
"""
import pytest

from core.atr_stop import (MAKS_SL_PCT, MIN_SL_PCT, PENGALI_SL, RASIO_TP,
                           jarak_stop, jarak_target, sesuaikan)


# ---------------------------------------------------------------------------
# Inti: stop tidak boleh berada di dalam derau harian
# ---------------------------------------------------------------------------

def test_support_yang_lebih_dekat_dari_derau_DIABAIKAN():
    """Kasus yang persis menjatuhkan sistem: S1 cuma 3% jauhnya padahal
    sahamnya bergerak 3,6% per hari. Support semacam itu bukan support --
    ia titik yang akan tersentuh besok apa pun yang terjadi."""
    assert jarak_stop(sr_pct=3.0, atr_pct=3.6) == round(3.6 * PENGALI_SL, 2)


def test_support_yang_LEBIH_JAUH_dari_derau_dipertahankan():
    """ATR tidak menggantikan level teknikal, ia cuma melantainya. Di
    situlah harga pernah benar-benar berhenti, dan itu arti yang tidak
    dimiliki ATR."""
    assert jarak_stop(sr_pct=11.0, atr_pct=2.0) == 11.0


def test_saham_tenang_dapat_stop_yang_ketat():
    """Inti gagasannya: stop 3% untuk BBCA dan untuk saham gorengan adalah
    dua hal yang sangat berbeda."""
    tenang = jarak_stop(sr_pct=1.0, atr_pct=1.2)     # 3,0%
    liar = jarak_stop(sr_pct=1.0, atr_pct=5.0)       # 12,5%
    assert tenang < liar
    assert tenang == 3.0 and liar == 12.5


# ---------------------------------------------------------------------------
# Pagar kewarasan
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("atr,harap", [
    (0.1, MIN_SL_PCT),       # saham nyaris tak bergerak
    (20.0, MAKS_SL_PCT),     # ATR kacau: IPO baru / lepas suspensi / data rusak
])
def test_nilai_ekstrem_dipagari(atr, harap):
    """Tanpa pagar, satu ATR aneh menghasilkan stop 50% yang akan diterima
    begitu saja oleh seluruh rantai di hilirnya -- termasuk penghitung lot."""
    assert jarak_stop(sr_pct=None, atr_pct=atr) == harap


def test_tanpa_masukan_sah_memulangkan_None_bukan_angka_bawaan():
    """Stop yang dikarang lebih berbahaya daripada sinyal yang tidak jadi
    dicatat: ia terlihat seperti rencana yang sudah dipikirkan."""
    assert jarak_stop(None, None) is None
    assert jarak_stop(0, 0) is None
    assert jarak_stop(-5, -2) is None


# ---------------------------------------------------------------------------
# Target tidak boleh lebih dekat daripada stop
# ---------------------------------------------------------------------------

def test_target_minimal_dua_kali_stop():
    """Rasio yang DIUKUR (TP 5xATR terhadap SL 2,5xATR), bukan angka yang
    dipilih karena terdengar enak."""
    assert jarak_target(sl_pct=8.0) == 16.0


def test_resistance_yang_lebih_jauh_dipertahankan():
    """Ruang yang memang lebih lebar tidak dipotong -- bagian itu justru
    yang menghasilkan di sistem yang pemenangnya lari jauh."""
    assert jarak_target(sl_pct=6.0, sr_pct=25.0) == 25.0


def test_resistance_yang_terlalu_dekat_TIDAK_dipakai():
    """BAHAYA YANG MUNCUL JUSTRU KARENA PERBAIKAN INI. Dengan stop yang
    kini lebih lebar, target lama yang dihitung dari R1 bisa jatuh DI BAWAH
    stop-nya sendiri. Rencana seperti itu rugi bahkan ketika analisisnya
    benar: menang 2% sekali, kalah 9% sekali."""
    tp = jarak_target(sl_pct=9.0, sr_pct=2.0)
    assert tp == 18.0
    assert tp > 9.0


def test_target_tanpa_stop_memulangkan_None():
    assert jarak_target(None) is None
    assert jarak_target(0) is None


# ---------------------------------------------------------------------------
# Gabungan
# ---------------------------------------------------------------------------

def test_sesuaikan_memulangkan_pasangan_yang_konsisten():
    tp, sl = sesuaikan(potensi_naik_pct=4.0, risiko_turun_pct=3.0, atr_pct=3.6)
    assert sl == 9.0                      # 3,6 x 2,5
    assert tp == 18.0                     # 2x stop, R1 (4%) terlalu dekat
    assert tp / sl == RASIO_TP


def test_sesuaikan_tanpa_atr_tetap_memakai_level_teknikal():
    """ATR bisa tidak tersedia (data terlalu pendek). Fitur ini tidak boleh
    menjatuhkan pencatatan sinyal -- cukup kembali ke perilaku lama."""
    tp, sl = sesuaikan(potensi_naik_pct=12.0, risiko_turun_pct=5.0, atr_pct=None)
    assert sl == 5.0 and tp == 12.0


def test_ambang_sesuai_yang_diukur():
    """Kalau suatu hari angkanya digeser tanpa pengukuran baru, uji ini
    yang memaksa penggesernya berhenti dan mengukur dulu."""
    assert (PENGALI_SL, RASIO_TP, MIN_SL_PCT, MAKS_SL_PCT) == (2.5, 2.0, 2.0, 15.0)
