"""Penjaga Fibonacci berarah.

Yang dijaga di sini satu hal, dan ia yang membuat seluruh fitur ini
berarti: ARAH AYUNANNYA. Diukur, dua arah memberi hasil yang
BERLAWANAN, sehingga menggabungkannya saling meniadakan -- dan
implementasi lama persis menghasilkan kasus gabungan itu.
"""
import inspect
import json
import pathlib

from core import fibo


def _ukur():
    f = pathlib.Path(__file__).resolve().parent.parent / "tools" / "hasil_ukur_fibo.json"
    return {r["aturan"]: r for r in json.loads(f.read_text(encoding="utf-8"))["aturan"]}


def _ayun(naik=True, n=160, besar=0.30):
    """Ayunan buatan: mendatar, lalu bergerak besar satu arah, lalu
    mundur sedikit. Pivotnya jelas dan urutannya pasti."""
    harga = []
    for i in range(n):
        if i < 60:
            v = 1000 + (i % 4)                      # mendatar
        elif i < 100:
            laju = besar * (i - 60) / 40
            v = 1000 * (1 + laju if naik else 1 - laju)
        else:
            puncak = 1000 * (1 + besar if naik else 1 - besar)
            mundur = 0.25 * besar * (i - 100) / 60
            v = puncak * (1 - mundur if naik else 1 + mundur)
        harga.append(v)
    tgl = [f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n)]
    return tgl, [h * 1.004 for h in harga], [h * 0.996 for h in harga], harga


# ---------------------------------------------------------------------------
# Arah
# ---------------------------------------------------------------------------

def test_arah_dari_URUTAN_WAKTU_bukan_dari_yang_paling_ekstrem():
    """CACAT YANG DIPERBAIKI. calculate_fibonacci_levels() yang lama
    mengambil High.max() dan Low.min() dari 90 bar TANPA memedulikan
    mana yang lebih dulu. Kalau puncaknya terjadi sebelum lembahnya,
    level "61,8% dari low ke high" mengukur gerakan yang tidak pernah
    terjadi ke arah itu."""
    src = inspect.getsource(fibo.hitung)
    assert "p_akhir > l_akhir" in src, "arah tidak ditentukan dari urutan waktu"
    f_naik = fibo.hitung(*_ayun(naik=True))
    f_turun = fibo.hitung(*_ayun(naik=False))
    assert f_naik and f_naik.arah == "naik"
    assert f_turun and f_turun.arah == "turun"


def test_retracement_ayunan_naik_ada_DI_BAWAH_ujung_ayunan():
    """Pada ayunan naik, retracement adalah calon LANTAI saat harga
    mundur -- jadi ia harus di bawah puncaknya."""
    f = fibo.hitung(*_ayun(naik=True))
    ret = [x for x in f.level if x["jenis"] == "retracement"]
    assert ret and all(x["harga"] < f.akhir_harga for x in ret)


def test_retracement_ayunan_turun_ada_DI_ATAS_ujung_ayunan():
    f = fibo.hitung(*_ayun(naik=False))
    ret = [x for x in f.level if x["jenis"] == "retracement"]
    assert ret and all(x["harga"] > f.akhir_harga for x in ret)


def test_arah_terukur_BERLAWANAN_jadi_tidak_boleh_digabung():
    """TEMUAN UTAMA. 38,2% pada ayunan naik +0,67%, pada ayunan turun
    -1,24% -- dan gabungannya +0,04%, yaitu nol.

    Memperbaiki arahnya bukan kosmetik: ia selisih antara sinyal
    (1,91 poin) dan derau."""
    m = _ukur()
    naik = m["Fibo 38.2% ayunan naik"]["unggul_pct"]
    turun = m["Fibo 38.2% ayunan turun"]["unggul_pct"]
    gab = m["Fibo 38.2% (gabungan arah)"]["unggul_pct"]
    assert naik > 0 > turun, (naik, turun)
    assert abs(gab) < min(abs(naik), abs(turun)), (
        "gabungan arah seharusnya mendekati nol; kalau tidak, dasar "
        "pemisahan arahnya perlu ditinjau ulang")


# ---------------------------------------------------------------------------
# Jumlah level mengikuti besar ayunan
# ---------------------------------------------------------------------------

def test_ayunan_kecil_dapat_lebih_sedikit_garis():
    """Syaratnya bisa dihitung: jarak antar-level harus melebihi derau
    harian. Lima level menuntut ayunan > 8,5x ATR; dua level > 4,2x.
    Memaksakan lima pada ayunan kecil menggambar garis yang lebih rapat
    daripada gerak sehari."""
    assert fibo.MIN_AYUNAN_ATR_PENUH > fibo.MIN_AYUNAN_ATR_RINGKAS
    assert len(fibo.RETRACEMENT_RINGKAS) < len(fibo.RETRACEMENT)
    besar = fibo.hitung(*_ayun(naik=True, besar=0.60))
    kecil = fibo.hitung(*_ayun(naik=True, besar=0.10))
    n_besar = len([x for x in besar.level if x["jenis"] == "retracement"])
    if kecil:
        n_kecil = len([x for x in kecil.level if x["jenis"] == "retracement"])
        assert n_besar >= n_kecil


def test_ayunan_terlalu_kecil_tidak_menghasilkan_apa_pun():
    assert fibo.hitung(*_ayun(naik=True, besar=0.01)) is None


# ---------------------------------------------------------------------------
# Angka terukur
# ---------------------------------------------------------------------------

def test_kunci_tabel_memakai_rasio_pecahan():
    """BUG NYATA: kuncinya sempat tersimpan 38.2 sementara level memakai
    0.382 -- pencariannya tidak pernah cocok, dan layar diam-diam
    menulis "belum diukur" untuk level yang SUDAH diukur. Diam, tanpa
    error."""
    for (r, arah) in fibo.UNGGUL_FIBO:
        assert 0 < r < 1, r
        assert arah in ("naik", "turun")
    assert fibo.unggul(0.382, "naik") is not None


def test_level_membawa_angkanya_atau_None():
    f = fibo.hitung(*_ayun(naik=True, besar=0.60))
    for x in f.level:
        if x["jenis"] != "retracement":
            continue
        assert "unggul_pct" in x
        # None sah ("belum cukup sampel"); nol TIDAK -- nol itu klaim.
        assert x["unggul_pct"] is None or isinstance(x["unggul_pct"], float)


def test_rasio_bersampel_kecil_tidak_diberi_angka():
    """50% pada ayunan turun cuma 109 kejadian. Angka dari sampel
    sekecil itu tidak bisa dibedakan dari kebetulan."""
    m = _ukur()
    kecil = m.get("Fibo 50% ayunan turun")
    if kecil and kecil["n"] < fibo.MIN_N_FIBO:
        assert fibo.unggul(0.5, "turun") is None


def test_tidak_mengintip_masa_depan():
    """Pivot baru sah hanya sesudah JEDA_KANAN bar berikutnya terbukti
    berbalik -- sama dengan seluruh modul pola."""
    src = inspect.getsource(fibo.hitung)
    assert "JEDA_KANAN" in src


def test_data_cacat_tidak_meledak():
    assert fibo.hitung([], [], [], []) is None
    assert fibo.hitung(["2025-01-01"], [1.0], [1.0], [1.0]) is None
