"""Jarak ke R1/S1 dan jarak TP/SL rencana adalah DUA HAL BERBEDA.

BUG NYATA 10 Okt 2026, dilaporkan penulis dari layarnya sendiri:

    RESISTANCE R1    Rp61  (+30,0%)
    SUPPORT S1       Rp57  (-15,0%)

Harga saat itu sekitar Rp60. Jarak ke Rp61 itu +1,7%, bukan +30%. Angka
30% dan 15% itu persis pagar ATR (MAKS_SL_PCT 15% dan 2x lipatnya) --
yaitu jarak TP/SL RENCANA, bukan jarak ke level teknikalnya.

Saya menyatukan dua field yang maksudnya berbeda:

    potensi_naik_pct / risiko_turun_pct  = DI MANA R1/S1 berada
    tp_rencana_pct   / sl_rencana_pct    = SEBERAPA JAUH target & stop
                                           dipasang sesudah dilantai derau

Yang membuatnya lolos sampai ke layar: keduanya sama-sama persentase,
sama-sama tentang naik/turun, dan tidak ada satu pun yang gagal. Yang
rusak cuma ARTINYA. Berkas ini mengunci invariannya: angka yang dipajang
di sebelah sebuah harga harus menjelaskan harga ITU.
"""
import pytest

import web.app as app_module
from core.atr_stop import MAKS_SL_PCT


# ---------------------------------------------------------------------------
# Invarian yang dilanggar: persen harus cocok dengan harga di sebelahnya
# ---------------------------------------------------------------------------

def _ringkasan(harga=60.0, r1=61.0, s1=57.0, atr_pct=8.0, monkeypatch=None):
    """Panggil _compute_ringkasan_cepat dengan level & ATR yang dikendalikan."""
    monkeypatch.setattr(app_module, "calculate_snr_levels",
                        lambda df: {"r1": r1, "s1": s1, "r2": r1 * 1.1,
                                    "s2": s1 * 0.9, "r3": r1 * 1.2,
                                    "s3": s1 * 0.8})
    monkeypatch.setattr(app_module, "calculate_ad_line", lambda df, **k: None)
    monkeypatch.setattr(app_module, "_liquidity_label", lambda v: "Likuid")
    monkeypatch.setattr(app_module, "_compute_grade", lambda *a: "B")
    monkeypatch.setattr(app_module, "_trading_style_label", lambda v: "Swing")

    class _DF:
        def __getitem__(self, k):
            class _S:
                def tail(self, n): return self
                def mean(self): return 1e9
                iloc = property(lambda s: [1.0])
                def __mul__(self, o): return self
            return _S()

    return app_module._compute_ringkasan_cepat(
        _DF(), {"price": harga, "atr_pct": atr_pct, "score": 70})


def test_persen_R1_menjelaskan_harga_R1(monkeypatch):
    """Kasus persis dari layar penulis: harga 60, R1 61. Jaraknya +1,7%,
    dan angka itulah yang boleh berdiri di sebelah Rp61."""
    r = _ringkasan(harga=60.0, r1=61.0, atr_pct=8.0, monkeypatch=monkeypatch)
    assert r["potensi_naik_pct"] == pytest.approx(1.67, abs=0.01)
    assert r["r1"] == 61.0


def test_persen_S1_menjelaskan_harga_S1(monkeypatch):
    r = _ringkasan(harga=60.0, s1=57.0, atr_pct=8.0, monkeypatch=monkeypatch)
    assert r["risiko_turun_pct"] == pytest.approx(5.0, abs=0.01)
    assert r["s1"] == 57.0


def test_ATR_tidak_mencemari_persen_level(monkeypatch):
    """ATR besar pernah membuat angka level melonjak ke pagarnya (15% dan
    30%). Level teknikal tidak berubah karena sahamnya bergejolak -- yang
    berubah cuma seberapa jauh stop dipasang."""
    tenang = _ringkasan(atr_pct=1.0, monkeypatch=monkeypatch)
    liar = _ringkasan(atr_pct=12.0, monkeypatch=monkeypatch)
    assert tenang["potensi_naik_pct"] == liar["potensi_naik_pct"]
    assert tenang["risiko_turun_pct"] == liar["risiko_turun_pct"]
    # Tapi rencananya MEMANG harus berbeda.
    assert liar["sl_rencana_pct"] > tenang["sl_rencana_pct"]


def test_rencana_tetap_dilantai_derau(monkeypatch):
    """Perbaikan tampilan tidak boleh ikut membatalkan perbaikan stopnya.
    Saham dengan ATR 8%/hari tidak boleh distop 5% di bawah harga."""
    r = _ringkasan(harga=60.0, s1=57.0, atr_pct=8.0, monkeypatch=monkeypatch)
    assert r["risiko_turun_pct"] == pytest.approx(5.0, abs=0.01)   # level
    assert r["sl_rencana_pct"] == MAKS_SL_PCT                      # rencana
    assert r["tp_rencana_pct"] == MAKS_SL_PCT * 2


# ---------------------------------------------------------------------------
# Yang dibaca pencatatan sinyal
# ---------------------------------------------------------------------------

def test_sinyal_memakai_jarak_RENCANA_bukan_jarak_level():
    from core.signal_history import _tp_sl_rencana

    tp, sl = _tp_sl_rencana({"potensi_naik_pct": 1.67, "risiko_turun_pct": 5.0,
                             "tp_rencana_pct": 30.0, "sl_rencana_pct": 15.0})
    assert (tp, sl) == (30.0, 15.0)


def test_tanpa_rencana_kembali_ke_jarak_level():
    """ATR bisa tidak terhitung pada saham yang datanya terlalu pendek.
    Sinyalnya tetap layak dicatat dengan perilaku lama daripada hilang."""
    from core.signal_history import _tp_sl_rencana

    assert _tp_sl_rencana({"potensi_naik_pct": 8.0,
                           "risiko_turun_pct": 4.0}) == (8.0, 4.0)
    assert _tp_sl_rencana({"potensi_naik_pct": 8.0, "risiko_turun_pct": 4.0,
                           "tp_rencana_pct": None,
                           "sl_rencana_pct": None}) == (8.0, 4.0)


def test_arah_SELL_menukar_target_dan_stop():
    """potensi_naik/risiko_turun dihitung dengan asumsi BUY, jadi untuk
    SELL keduanya bertukar tempat. Salah tukar di sini membuat stop
    dipasang di arah yang justru diharapkan."""
    from core.signal_history import _tp_sl_rencana

    it = {"tp_rencana_pct": 30.0, "sl_rencana_pct": 15.0,
          "potensi_naik_pct": 1.67, "risiko_turun_pct": 5.0}
    assert _tp_sl_rencana(it, is_sell=True) == (15.0, 30.0)
    assert _tp_sl_rencana(it, is_sell=False) == (30.0, 15.0)
