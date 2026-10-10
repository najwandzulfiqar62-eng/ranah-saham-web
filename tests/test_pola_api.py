"""Penjaga pola chart di halaman Analisis.

Yang dikunci di sini adalah kelas-kelas bug yang sudah pernah terjadi di
proyek ini, bukan "payloadnya ada medannya":

  - menambah medan tanpa menaikkan versi kunci cache -> kolom diam-diam
    kosong sesudah deploy, tanpa satu pun error
  - loop Python murni di event loop -> SELURUH server tersendat
  - fitur baru memicu unduhan tambahan (scaling #1)
  - satu emiten cacat menjatuhkan seluruh halaman
"""
import inspect

import web.app as app_module


def test_kunci_cache_analyze_berversi():
    """Payload analisis bertambah medan `pola_chart`. Tanpa versi baru,
    server yang masih memegang cache lama akan menyajikan payload TANPA
    medan itu sampai TTL-nya habis -- dan panelnya kosong hanya untuk
    sebagian pengunjung, yang jauh lebih sulit dilacak daripada kosong
    untuk semua orang."""
    import re
    src = inspect.getsource(app_module._analyze_payload)
    # Yang dikunci adalah ADANYA versi, bukan angkanya. Mengunci "v2"
    # berarti tes ini gagal setiap kali payloadnya bertambah medan --
    # yaitu gagal tepat ketika versinya dinaikkan dengan BENAR, dan tes
    # yang menghukum perbuatan benar akan dilonggarkan orang.
    assert re.search(r'f"analyze:v\d+:\{kode\}"', src), (
        "kunci cache analyze harus berversi (analyze:vN:{kode})")
    assert 'f"analyze:{kode}"' not in src


def test_pola_dihitung_di_worker_thread():
    """Loop Python murni di event loop menahan SELURUH server, bukan
    cuma halaman yang memanggilnya. Deteksi pola itu loop pivot di 220
    bar x 16 pencari."""
    src = inspect.getsource(app_module._analyze_payload)
    i_def = src.index("def _hitung():")
    i_thread = src.index("await asyncio.to_thread(_hitung)")
    i_panggil = src.index("_pola_chart_payload(")
    assert i_def < i_panggil < i_thread, "deteksi pola tidak di dalam _hitung()"


def test_pola_tidak_mengunduh_apa_pun():
    """Datanya sudah di tangan saat _hitung() berjalan. Mengunduh ulang
    akan menambah satu panggilan Yahoo per pembukaan halaman Analisis --
    jalur yang paling sering ditekan orang."""
    src = inspect.getsource(app_module._pola_chart_payload)
    for terlarang in ("download", "_clean(", "yf.", "requests", "await"):
        assert terlarang not in src, terlarang


def test_pola_chart_payload_sinkron():
    """Kalau ia jadi async, pemanggilan di dalam _hitung() (yang sinkron)
    akan menghasilkan coroutine yang tidak pernah ditunggu -- panelnya
    kosong TANPA error."""
    assert not inspect.iscoroutinefunction(app_module._pola_chart_payload)


def test_data_cacat_tidak_menjatuhkan_halaman():
    """Satu emiten dengan data aneh tidak boleh membuat seluruh halaman
    Analisis gagal. Yang benar adalah daftar pola kosong."""
    import pandas as pd
    assert app_module._pola_chart_payload("X", pd.DataFrame()) == []
    assert app_module._pola_chart_payload("X", None) == []


def test_pola_belum_terukur_dikirim_None_bukan_nol():
    """Nol adalah klaim ("tidak ada keunggulan"); "tidak tahu" bukan.
    Mengirim 0 untuk pola yang belum diukur akan membuat layar
    menuliskan angka yang tidak pernah diukur siapa pun."""
    src = inspect.getsource(app_module._pola_chart_payload)
    assert '"unggul_pct": None if u is None else u.get("unggul_pct")' in src
    assert "or 0" not in src


def test_payload_memuat_fase_dan_arah():
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(3)
    n = 260
    h = 1000 * np.cumprod(1 + rng.normal(0.001, 0.015, n))
    idx = pd.bdate_range("2024-01-01", periods=n)
    df = pd.DataFrame({"Open": h * .995, "High": h * 1.01, "Low": h * .99,
                       "Close": h, "Volume": [1e6] * n}, index=idx)
    out = app_module._pola_chart_payload("UJI", df)
    assert isinstance(out, list)
    for p in out:
        assert p["fase"] in ("TERBENTUK", "TEMBUS")
        assert p["arah"] in ("naik", "turun", "penerusan")
        assert p["arti"], f"pola {p['nama']} tidak punya keterangan"


def test_setiap_pola_yang_bisa_terdeteksi_punya_keterangan():
    """Pola tanpa keterangan akan muncul di layar sebagai nama asing
    tanpa penjelasan -- persis yang membuat pemula salah membaca Inverse
    H&S sebagai sinyal jual."""
    from core.pola_katalog import _CERMIN_NAMA
    from core.pola_ukur import keterangan
    nama = set(_CERMIN_NAMA) | {v for v in _CERMIN_NAMA.values() if v}
    nama |= {"Segitiga Menaik", "Segitiga Menurun", "Segitiga Simetris",
             "Rectangle"}
    for n in nama:
        assert keterangan(n), n


def test_keterangan_menyebut_jebakan_dua_pola_yang_sering_salah_dibaca():
    """Rising Wedge naik tapi bearish; Falling Wedge turun tapi bullish;
    Inverse H&S bullish. Penulis sendiri pernah salah membaca yang
    terakhir, jadi keterangannya wajib menyebutnya tegas."""
    from core.pola_ukur import keterangan
    assert "NAIK" in keterangan("Inverse Head & Shoulders")
    assert "TURUN" in keterangan("Rising Wedge")
    assert "NAIK" in keterangan("Falling Wedge")


def test_wedge_tidak_memajang_angka_dari_detektor_lama():
    """Detektor wedge diperbaiki 11 Okt 2026 (pivot wajib berurutan),
    dan deteksinya turun 19 -> 1 per 200 emiten. Angka lama mengukur
    bentuk yang BERBEDA; memajangnya berarti memberi pembaca angka yang
    ia tidak punya cara tahu sedang mengukur hal lain.

    Uji ini gagal kalau ada yang mengembalikannya tanpa pengukuran
    ulang."""
    from core.pola_ukur import UNGGUL_POLA
    lama = {("Falling Wedge", "TEMBUS"): 0.07,
            ("Falling Wedge", "TERBENTUK"): -0.71,
            ("Rising Wedge", "TEMBUS"): -0.12,
            ("Rising Wedge", "TERBENTUK"): 1.07}
    for k, v in lama.items():
        if k in UNGGUL_POLA:
            assert UNGGUL_POLA[k].get("unggul_pct") != v, (
                f"{k} memajang angka dari detektor lama ({v})")


def test_pola_tanpa_angka_tetap_bisa_ditampilkan():
    """Mencabut angkanya tidak boleh mematikan polanya. "Belum diukur"
    adalah keterangan yang sah; nol bukan."""
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(11)
    n = 260
    h = 1000 * np.cumprod(1 + rng.normal(0.0005, 0.02, n))
    idx = pd.bdate_range("2024-01-01", periods=n)
    df = pd.DataFrame({"Open": h * .995, "High": h * 1.01, "Low": h * .99,
                       "Close": h, "Volume": [1e6] * n}, index=idx)
    for p in app_module._pola_chart_payload("UJI", df):
        # unggul_pct boleh None, tapi nama & fase & arti wajib ada.
        assert p["nama"] and p["fase"] and p["arti"]
        assert p["unggul_pct"] is None or isinstance(p["unggul_pct"], (int, float))
