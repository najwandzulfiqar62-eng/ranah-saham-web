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
    # Kandidat ayunan dibangun dari URUTAN: pasangan "naik" selalu
    # lembah-dulu-lalu-puncak (l < ip), "turun" sebaliknya. Yang dikunci
    # adalah adanya penyaringan posisi itu, bukan satu baris tertentu.
    assert "l for l in lembah if l < ip" in src,         "ayunan naik tidak menuntut lembah mendahului puncak"
    assert "p for p in puncak if p < il" in src,         "ayunan turun tidak menuntut puncak mendahului lembah"
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


def test_fibonacci_TIDAK_diklaim_punya_keunggulan():
    """TEMUAN YANG MEMBATALKAN TEMUAN SEBELUMNYA.

    Pengukuran pertama -- waktu ayunannya masih diambil dari pivot
    TERAKHIR -- memberi 38,2% naik +0,67% dan turun -1,24%, dan selisih
    1,91 poin itu sempat disebut salah satu yang terbesar di proyek ini.

    Sesudah penjangkarannya diperbaiki ke ayunan DOMINAN (perbaikan yang
    benar: itu yang ditarik manusia, dan tanpanya Fibonacci hilang di
    saham yang ayunan besarnya paling jelas), selisih itu LENYAP --
    kedua arah kini negatif, dan tandanya berganti-ganti antar-rasio
    tanpa urutan yang masuk akal.

    Jadi selisihnya artefak penjangkaran, bukan sifat pasar. Uji ini
    menjaga agar tidak ada yang menyajikan Fibonacci sbg sesuatu yang
    terukur menguntungkan hanya karena satu sel kebetulan positif.
    """
    m = _ukur()
    nilai = [r["unggul_pct"] for r in m.values()
             if "gabungan" not in r["aturan"] and r["n"] >= fibo.MIN_N_FIBO]
    assert nilai, "tidak ada sel bersampel memadai"
    # Tandanya campur aduk -- itu yang membuktikan tidak ada struktur.
    assert any(v > 0 for v in nilai) and any(v < 0 for v in nilai), nilai
    # Dan rata-ratanya tidak positif berarti.
    assert sum(nilai) / len(nilai) < 0.5, sum(nilai) / len(nilai)


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
    # Tabelnya BOLEH kosong -- ia memang dikosongkan sesudah
    # penjangkaran ayunan diganti, sampai pengukuran ulang selesai.
    # Yang dilarang bukan kosong, melainkan BERISI ANGKA LAMA.
    assert fibo.unggul(0.382, "naik") in (None,) or         fibo.UNGGUL_FIBO[(0.382, "naik")]["unggul_pct"] != 0.67,         "angka dari penjangkaran lama muncul kembali tanpa pengukuran ulang"


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


def test_angka_lama_tidak_boleh_kembali_tanpa_diukur_ulang():
    """Penjangkaran ayunan diganti dari "pivot terakhir" ke "ayunan
    dominan" -- aturan yang BERBEDA, pada saham yang sebagian besar
    berbeda pula (dulu 37% emiten dapat level, sekarang hampir
    semuanya).

    Memajang angka lama di atas aturan baru persis kesalahan yang sudah
    terjadi pada wedge: pembaca tidak punya cara tahu bahwa angka di
    depannya mengukur hal yang lain."""
    lama = {(0.382, "naik"): 0.67, (0.382, "turun"): -1.24,
            (0.618, "naik"): -0.28, (0.618, "turun"): 0.10}
    for k, v in lama.items():
        if k in fibo.UNGGUL_FIBO:
            assert fibo.UNGGUL_FIBO[k].get("unggul_pct") != v, k
