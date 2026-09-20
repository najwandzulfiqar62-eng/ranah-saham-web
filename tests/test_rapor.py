"""Tiga hal yang TIDAK bisa dilakukan aplikasi sekuritas.

Permintaan penulis 21 Sep 2026, sesudah ia menolak fitur pantauan harga
dengan alasan "di sekuritas udah ada". Penolakan itu menunjuk pertanyaan
yang lebih tepat: bukan "fitur bot trading apa yang bagus", melainkan "apa
yang TIDAK BISA dilakukan aplikasi sekuritas".

Jawabannya: catatan transaksimu digabung dengan sinyal beraudit, lima
teori, dan bar harga tersimpan.
"""
import datetime as dt

import pytest

from core.rapor import (MIN_SAMPEL, efek_disposisi, pasangkan_transaksi,
                        per_kelompok, ringkas)
from core.uji_aturan import bandingkan, putar_ulang, uji


def _tgl(n):
    return (dt.datetime(2026, 6, 1) + dt.timedelta(days=n)).isoformat()


def _perdagangan(data):
    """data = [(kode, harga_beli, harga_jual, hari_ditahan), ...]"""
    tx, i = [], 0
    for kode, beli, jual, hari in data:
        i += 1
        tx.append({"id": i, "kode": kode, "arah": "BELI", "lot": 10,
                   "harga": beli, "dicatat_at": _tgl(0)})
        i += 1
        tx.append({"id": i, "kode": kode, "arah": "JUAL", "lot": 10,
                   "harga": jual, "dicatat_at": _tgl(hari)})
    return tx


# ---------------------------------------------------------------------------
# Merangkai transaksi jadi perdagangan
# ---------------------------------------------------------------------------

def test_beli_lalu_jual_jadi_satu_perdagangan():
    s = pasangkan_transaksi(_perdagangan([("BBCA", 8000, 8600, 5)]))
    assert len(s) == 1
    assert s[0]["hasil_pct"] == pytest.approx(7.5)
    assert s[0]["hari"] == 5
    assert s[0]["hasil_rp"] == pytest.approx(600 * 10 * 100)


def test_posisi_yang_belum_dijual_tidak_dihitung():
    """Posisi berjalan belum punya hasil. Menganggapnya untung/rugi sekarang
    membuat rapornya berubah tiap hari tanpa ada yang terjadi."""
    tx = [{"id": 1, "kode": "BBCA", "arah": "BELI", "lot": 10, "harga": 8000,
           "dicatat_at": _tgl(0)}]
    assert pasangkan_transaksi(tx) == []


def test_jual_sebagian_memakai_fifo():
    """Beli 2×, jual sebagian: yang ditutup adalah pembelian TERLAMA. FIFO
    dipilih karena paling mudah dijelaskan kalau ada yang bertanya 'kok
    angkanya segitu'."""
    tx = [{"id": 1, "kode": "X", "arah": "BELI", "lot": 10, "harga": 100,
           "dicatat_at": _tgl(0)},
          {"id": 2, "kode": "X", "arah": "BELI", "lot": 10, "harga": 200,
           "dicatat_at": _tgl(1)},
          {"id": 3, "kode": "X", "arah": "JUAL", "lot": 10, "harga": 150,
           "dicatat_at": _tgl(5)}]
    s = pasangkan_transaksi(tx)
    assert len(s) == 1
    assert s[0]["harga_beli"] == 100, "bukan pembelian terlama yang ditutup"
    assert s[0]["hasil_pct"] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Efek disposisi -- pola paling mahal, dan paling tidak terasa
# ---------------------------------------------------------------------------

def test_menahan_yang_rugi_lebih_lama_terdeteksi():
    """Shefrin & Statman (1985), Odean (1998): memotong yang untung
    cepat-cepat sambil memeluk yang rugi lama-lama. Tidak terasa dari dalam;
    cuma kelihatan kalau dihitung."""
    s = pasangkan_transaksi(_perdagangan([
        ("A", 100, 108, 5), ("B", 200, 214, 4), ("C", 50, 54, 6),
        ("D", 100, 92, 20), ("E", 200, 186, 22), ("F", 50, 46, 21),
    ]))
    d = efek_disposisi(s)
    assert d["hari_untung"] == pytest.approx(5.0)
    assert d["hari_rugi"] == pytest.approx(21.0)
    assert d["rasio"] == pytest.approx(4.2)


def test_disposisi_diam_kalau_satu_sisi_terlalu_sedikit():
    """Menyimpulkan pola dari satu-dua kejadian itu mengarang -- dan
    mengarang di sini lebih berbahaya daripada diam, karena orang akan
    mengubah caranya berdasarkan pola yang tidak ada."""
    s = pasangkan_transaksi(_perdagangan([
        ("A", 100, 108, 5), ("B", 200, 214, 4), ("C", 50, 54, 6),
        ("D", 100, 92, 20),
    ]))
    assert efek_disposisi(s) is None


def test_rapor_diam_kalau_transaksinya_sedikit():
    s = pasangkan_transaksi(_perdagangan([("A", 100, 108, 5)] * 1))
    assert ringkas(s) is None


def test_kelompok_kecil_tidak_disimpulkan():
    """"Saham ini tidak cocok untukmu" dari dua kali masuk bukan
    kesimpulan."""
    s = pasangkan_transaksi(_perdagangan([("GOTO", 100, 90, 5),
                                          ("GOTO", 100, 92, 5)]))
    assert per_kelompok(s, lambda t: t["kode"]) == []


def test_emiten_yang_berulang_merugikan_terdeteksi():
    s = pasangkan_transaksi(_perdagangan([
        ("GOTO", 100, 92, 20), ("GOTO", 95, 88, 24), ("GOTO", 90, 83, 19),
        ("BBCA", 8000, 8600, 4), ("BBCA", 8200, 8750, 5), ("BBCA", 8400, 8900, 6),
    ]))
    per = {k["nama"]: k for k in per_kelompok(s, lambda t: t["kode"])}
    assert per["GOTO"]["menang"] == 0 and per["GOTO"]["n"] == 3
    assert per["BBCA"]["menang"] == 3


# ---------------------------------------------------------------------------
# Uji aturan -- putar ulang sinyal dengan TP/SL pilihan sendiri
# ---------------------------------------------------------------------------

def _bar(tgl, high, close, low):
    return (tgl, high, close, low)


def test_tp_tersentuh_dihitung_menang():
    bars = [_bar("2026-06-02", 105, 104, 99), _bar("2026-06-03", 112, 110, 103)]
    r = putar_ulang(100, bars, 8, 3)
    assert r["status"] == "TP" and r["hasil_pct"] == 8 and r["hari"] == 2


def test_sl_tersentuh_dihitung_kalah():
    bars = [_bar("2026-06-02", 101, 98, 96)]
    r = putar_ulang(100, bars, 8, 3)
    assert r["status"] == "SL" and r["hasil_pct"] == -3


def test_kalau_keduanya_kena_di_hari_sama_yang_dihitung_SL():
    """INI yang menentukan kejujuran seluruh angkanya.

    Dari bar HARIAN tidak mungkin tahu mana yang tersentuh lebih dulu.
    Menganggap TP duluan membuat hasilnya berbohong ke arah yang
    menyenangkan -- dan backtest yang berbohong ke arah menyenangkan lebih
    berbahaya daripada tidak ada backtest."""
    bars = [_bar("2026-06-02", 110, 100, 95)]      # +10% dan -5% sekaligus
    assert putar_ulang(100, bars, 8, 3)["status"] == "SL"


def test_yang_belum_selesai_tidak_dibuang():
    """Membuangnya menghapus justru yang bergerak lambat, dan itu
    memiringkan hasilnya."""
    bars = [_bar("2026-06-02", 102, 101, 99)]
    r = putar_ulang(100, bars, 8, 3)
    assert r["status"] == "BELUM"
    assert r["hasil_pct"] == pytest.approx(1.0)


def test_bar_sebelum_tanggal_masuk_tidak_ikut():
    """Memakai bar hari masuk berarti memakai pergerakan yang sebagian sudah
    terjadi sebelum sinyalnya lahir -- bias ke depan yang membuat hasilnya
    terlalu bagus tanpa ketahuan."""
    sinyal = [{"kode": "A", "entry_price": 100, "recorded_at": "2026-06-05",
               "source": "TOP_PICK"}]
    bar = {"A": [_bar("2026-06-04", 120, 118, 117),   # SEBELUM masuk
                 _bar("2026-06-06", 101, 100, 99)]}
    r = uji(sinyal, bar, 8, 3)
    assert r["n_tp"] == 0, "bar sebelum tanggal masuk ikut dihitung"


def test_membandingkan_beberapa_aturan():
    """Satu angka sendirian tidak memberi tahu apa pun -- "menang 58%" baru
    berarti kalau ada pembandingnya."""
    sinyal = [{"kode": "A", "entry_price": 100, "recorded_at": "2026-06-01",
               "source": "TOP_PICK"}]
    bar = {"A": [_bar("2026-06-02", 106, 105, 99),
                 _bar("2026-06-03", 115, 113, 104)]}
    hasil = bandingkan(sinyal, bar, [(5, 3), (12, 3)])
    assert [r["tp_pct"] for r in hasil] == [5, 12]
    assert hasil[0]["n_tp"] == 1 and hasil[1]["n_tp"] == 1


def test_menyaring_per_teori():
    sinyal = [{"kode": "A", "entry_price": 100, "recorded_at": "2026-06-01",
               "source": "TOP_PICK"},
              {"kode": "B", "entry_price": 100, "recorded_at": "2026-06-01",
               "source": "NR7_52W"}]
    bar = {"A": [_bar("2026-06-02", 110, 109, 99)],
           "B": [_bar("2026-06-02", 110, 109, 99)]}
    assert uji(sinyal, bar, 8, 3)["n"] == 2
    assert uji(sinyal, bar, 8, 3, sumber="NR7_52W")["n"] == 1


# ---------------------------------------------------------------------------
# Cek lima teori
# ---------------------------------------------------------------------------

def test_cek_menghitung_berapa_teori_yang_setuju():
    import asyncio

    import web.app as app_module

    peta = {
        app_module.SCREENERPRO_CACHE_KEY: {
            "items": [{"ticker": "ELSA", "criteria_met": 7, "skor": 72.5}]},
        "screener_harmonic:v3:luas:bullish:10": {"items": []},
        "confidence:raw": [{"kode": "ELSA", "confidence_score": 74,
                            "is_nr7_52w": False}],
    }
    asli = app_module._cache_get
    app_module._cache_get = lambda k: peta.get(k)
    try:
        teks = asyncio.run(app_module._wa_cek("ELSA"))
    finally:
        app_module._cache_get = asli

    assert "2 dari 5 teori setuju" in teks
    assert "✓ Minervini" in teks and "7/8 kriteria" in teks
    assert "✗ Harmonic" in teks


def test_cek_tidak_pernah_memindai():
    """Aturan yang sama dipegang seluruh perintah bot: saringan dihangatkan
    pemanas, dan memicu pemindaian dari sini berarti satu orang membuat
    semua pengunjung menunggu."""
    import asyncio

    import web.app as app_module

    asli = app_module._cache_get
    app_module._cache_get = lambda k: None
    try:
        teks = asyncio.run(app_module._wa_cek("ELSA"))
    finally:
        app_module._cache_get = asli
    assert "0 dari 5 teori setuju" in teks
    assert "tidak satu pun teori" in teks.lower()
