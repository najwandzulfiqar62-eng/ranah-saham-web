"""Penjaga sinyal beli/jual yang digambar di chart.

GEJALA YANG MELAHIRKAN BERKAS INI: penulis menolak versi pertama --
"area buy dan sell kedeketan". Benar, dan sebabnya cacat nyata, bukan
selera: sinyalnya digambar sbg ZONA HARGA di support/resistance
terdekat, sehingga ketika harga terjepit di antara dua level berdekatan,
kedua garis nyaris menempel. Diukur pada IHSG saat itu: beli -1,7%,
jual +2,1%.

Sekarang sinyal adalah KEJADIAN bertanggal, dan berkas ini menjaga
sifat-sifat yang membuatnya tetap begitu.
"""
import inspect

import pandas as pd
import pytest

import web.app as app_module


def _df(vonis_urut):
    """DataFrame boneka; isinya tidak dipakai karena vonisnya dipalsukan.

    Panjangnya menentukan berapa bar yang dipindai.
    """
    n = len(vonis_urut) + 60
    idx = pd.bdate_range("2025-01-01", periods=n)
    return pd.DataFrame({"Open": [100.0] * n, "High": [101.0] * n,
                         "Low": [99.0] * n, "Close": [100.0] * n,
                         "Volume": [1e6] * n}, index=idx)


def _pakai_vonis(monkeypatch, urut):
    """Paksa _ringkasan_sinyal_teknikal mengikuti urutan vonis yang diberi.

    Dipanggil sekali per bar mulai dari indeks 60.
    """
    monkeypatch.setattr(app_module, "_cache_get", lambda k: None)
    monkeypatch.setattr(app_module, "_cache_set", lambda k, v, ttl=None: None)
    import core.ai_score as ai_mod
    monkeypatch.setattr(ai_mod, "calculate_ai_score_from_df",
                        lambda d: {"_n": len(d)})
    def _r(ai):
        i = ai["_n"] - 1 - 60
        return {"overall": urut[i] if 0 <= i < len(urut) else "NETRAL"}
    monkeypatch.setattr(app_module, "_ringkasan_sinyal_teknikal", _r)


# ---------------------------------------------------------------------------
# Aturan
# ---------------------------------------------------------------------------

def test_vonis_sehari_TIDAK_memicu_sinyal(monkeypatch):
    """Inti akurasinya. Terukur, BELI KUAT sehari cuma +1,11% sementara
    yang bertahan ke hari kedua +4,59% -- empat kali lipat. Menandai yang
    sehari berarti menggambar segitiga untuk kejadian yang terukur empat
    kali lebih lemah."""
    urut = ["NETRAL", "BELI KUAT", "NETRAL", "NETRAL"]
    _pakai_vonis(monkeypatch, urut)
    assert app_module._sinyal_chart_payload("X", _df(urut)) == []


def test_vonis_bertahan_dua_hari_memicu_sinyal(monkeypatch):
    urut = ["NETRAL", "BELI KUAT", "BELI KUAT", "NETRAL"]
    _pakai_vonis(monkeypatch, urut)
    out = app_module._sinyal_chart_payload("X", _df(urut))
    assert len(out) == 1
    assert out[0]["jenis"] == "BELI"
    assert out[0]["bertahan"] is True


def test_sisi_jual_memakai_aturan_yang_SAMA(monkeypatch):
    """Kalau sisi jual memakai syarat yang lebih longgar, segitiga merah
    akan muncul jauh lebih sering daripada hijau -- dan ketimpangan itu
    akan terbaca sbg pasar yang bearish, padahal cuma ambang yang
    berbeda."""
    urut = ["NETRAL", "JUAL KUAT", "JUAL KUAT", "NETRAL"]
    _pakai_vonis(monkeypatch, urut)
    out = app_module._sinyal_chart_payload("X", _df(urut))
    assert len(out) == 1 and out[0]["jenis"] == "JUAL"


def test_vonis_tengah_tidak_pernah_jadi_sinyal(monkeypatch):
    """Vonis TENGAH tidak boleh jadi segitiga. Yang masuk hitungan
    "tengah" ditentukan ANGKANYA, bukan namanya:

        BELI bertahan            +2,88%   <- sinyal
        BELI KUAT bertahan       +0,81%   <- sinyal
        CENDERUNG BELI bertahan  +0,32%   <- bukan
        NETRAL bertahan          -0,42%   <- bukan
        CENDERUNG JUAL bertahan  -0,46%   <- bukan
        JUAL bertahan            -0,87%   <- sinyal

    BELI dan JUAL dulu ikut dilarang di sini, dan itu keliru: keduanya
    justru terukur paling kuat. Menggambar segitiga untuk vonis yang
    terukur tak berbeda dari menebak tetap dilarang -- yang berubah cuma
    siapa yang masuk golongan itu.
    """
    for v in ("CENDERUNG BELI", "NETRAL", "CENDERUNG JUAL"):
        urut = ["NETRAL", v, v, v, "NETRAL"]
        _pakai_vonis(monkeypatch, urut)
        assert app_module._sinyal_chart_payload("X", _df(urut)) == [], v
        assert v not in app_module.VONIS_SINYAL_CHART, v


def test_vonis_pemicu_sinyal_dipilih_dari_ANGKA(monkeypatch):
    """Penjagaan arah: yang memicu segitiga harus vonis yang terukur
    paling kuat di sisinya, bukan yang namanya terdengar paling
    meyakinkan. BELI terukur di ATAS BELI KUAT, jadi membuangnya akan
    membuang sinyal terbaik yang punya aplikasi ini."""
    assert "BELI" in app_module.VONIS_SINYAL_CHART
    assert "JUAL" in app_module.VONIS_SINYAL_CHART
    terkuat = max(app_module.UNGGUL_BERTAHAN,
                  key=app_module.UNGGUL_BERTAHAN.get)
    assert terkuat in app_module.VONIS_SINYAL_CHART, terkuat
    # ...dan ia memang memicu, bukan cuma terdaftar.
    urut = ["NETRAL", terkuat, terkuat, "NETRAL"]
    _pakai_vonis(monkeypatch, urut)
    assert len(app_module._sinyal_chart_payload("X", _df(urut))) == 1


def test_vonis_panjang_dihitung_SATU_kejadian(monkeypatch):
    """Vonis yang bertahan dua minggu adalah SATU kejadian. Menandainya
    sepuluh kali adalah kesalahan yang sudah tiga kali menggelembungkan
    angka di proyek ini -- kali ini dalam bentuk gambar."""
    urut = ["NETRAL"] + ["BELI KUAT"] * 14 + ["NETRAL"]
    _pakai_vonis(monkeypatch, urut)
    out = app_module._sinyal_chart_payload("X", _df(urut))
    assert len(out) == 1, [x["t"] for x in out]


def test_sinyal_sejenis_diberi_jarak_minimum(monkeypatch):
    """Vonis yang berkedip di sekitar ambangnya melahirkan segitiga
    berdempetan -- yang menyiratkan beberapa kesempatan berbeda padahal
    itu satu keadaan yang sama. Inilah keluhan yang melahirkan berkas
    ini, dalam bentuknya yang lain."""
    kedip = ["BELI KUAT", "BELI KUAT", "NETRAL"] * 6
    urut = ["NETRAL"] + kedip
    _pakai_vonis(monkeypatch, urut)
    out = app_module._sinyal_chart_payload("X", _df(urut))
    # 6 kedipan, tapi jarak minimum 10 bar -> jauh lebih sedikit
    assert len(out) < 6, [x["t"] for x in out]
    assert app_module.JEDA_SINYAL_BAR >= 5


# ---------------------------------------------------------------------------
# Ongkos & keamanan
# ---------------------------------------------------------------------------

def test_sinyal_di_cache():
    """18,7 ms per bar x 170 bar = 3,2 detik. Chart menyegarkan dirinya
    tiap 30 detik; tanpa cache itu 3,2 detik CPU tiap setengah menit
    untuk SETIAP penonton."""
    import re
    src = inspect.getsource(app_module._sinyal_chart_payload)
    assert "_cache_get(" in src and "_cache_set(" in src
    # Yang dikunci ADANYA versi, bukan angkanya: mengunci "v1" membuat
    # tes gagal tepat ketika versinya dinaikkan dengan BENAR, dan tes
    # yang menghukum perbuatan benar akan dilonggarkan orang.
    assert re.search(r'f"sinyalchart:v\d+:', src), "kunci cache harus berversi"


def test_sinyal_dihitung_di_worker_thread():
    """Tiga detik di event loop membekukan SELURUH server, bukan cuma
    chart yang memintanya."""
    # DUA lapisan, dua perlakuan, dan keduanya di luar event loop:
    #   - lapisan ringan (pola/harmonic/S-R/rencana, 171 ms) dihitung
    #     di worker thread dan DITUNGGU
    #   - lapisan sinyal (3,2 detik) dihitung di worker thread tapi
    #     TIDAK ditunggu; ia menyusul lewat cache-nya sendiri
    src = inspect.getsource(app_module.ohlc)
    assert "asyncio.to_thread(_chart_overlay_payload" in src
    latar = inspect.getsource(app_module._sinyal_chart_latar)
    assert "asyncio.to_thread(_sinyal_chart_payload" in latar


def test_sinyal_payload_sinkron():
    assert not inspect.iscoroutinefunction(app_module._sinyal_chart_payload)


def test_data_cacat_tidak_meledak(monkeypatch):
    monkeypatch.setattr(app_module, "_cache_get", lambda k: None)
    monkeypatch.setattr(app_module, "_cache_set", lambda k, v, ttl=None: None)
    assert app_module._sinyal_chart_payload("X", pd.DataFrame()) == []


def test_angka_sinyal_TIDAK_memakai_tabel_vonis_sehari():
    """UNGGUL_VONIS mengukur vonis SEHARI. Memasangnya pada segitiga yang
    menandai aturan BERTAHAN berarti menempelkan label yang mengukur
    aturan berbeda dari yang digambar -- dan bedanya empat kali lipat."""
    src = inspect.getsource(app_module._sinyal_chart_payload)
    assert "UNGGUL_SINYAL_CHART" in src
    assert "UNGGUL_VONIS" not in src


def test_setiap_vonis_pemicu_punya_angka_terukurnya():
    """Nol adalah klaim ("tidak ada keunggulan"); None berarti "belum
    diukur". Keduanya sah, tapi vonis yang SUDAH dipakai memicu
    segitiga wajib punya angkanya -- menggambar segitiga tanpa angka
    berarti menyerahkan kesimpulan pada bentuk panah."""
    for v in app_module.VONIS_SINYAL_CHART:
        assert v in app_module.UNGGUL_SINYAL_CHART, v
        assert app_module.UNGGUL_SINYAL_CHART[v] is not None, v
        assert app_module.N_SINYAL_CHART[v], v


def test_angka_sinyal_chart_sama_dengan_tabel_bertahan():
    """Segitiga menandai aturan BERTAHAN, jadi angkanya harus angka
    aturan bertahan -- bukan angka vonis sehari, yang mengukur hal
    yang berbeda."""
    for v, a in app_module.UNGGUL_SINYAL_CHART.items():
        assert a == app_module.UNGGUL_BERTAHAN[v], v


# ---------------------------------------------------------------------------
# Layar
# ---------------------------------------------------------------------------

def test_layar_tidak_menggambar_garis_beli_jual_duplikat():
    """CACAT NYATA: price-line "AREA BELI" dipasang di harga yang PERSIS
    SAMA dengan level "Support Terdekat" yang sudah tergambar -- dua
    garis bertumpuk di satu harga, yang membuat chart terlihat sesak dan
    ikut membuat penulis menyangka area beli & jualnya berdempetan."""
    js = open("web/static/app.js", encoding="utf-8").read()
    i = js.index("function _gambarRencana(")
    j = js.index("function _gambarSinyal(", i)
    blok = js[i:j]
    assert "AREA BELI" not in blok, "garis beli masih digambar dua kali"
    assert "AREA JUAL" not in blok
    # Penandanya pindah ke judul garis S/R.
    assert "_tandaRencana" in js


def test_layar_menggambar_sinyal_di_tanggalnya():
    """Bukan di bar terakhir sbg "area". Menempelkan panah di bar
    terakhir untuk harga yang belum tentu tersentuh menyiratkan kejadian
    yang tidak pernah ada."""
    js = open("web/static/app.js", encoding="utf-8").read()
    i = js.index("function _gambarSinyal(")
    blok = js[i:js.index("function _renderPolaChips(", i)]
    assert "time:x.t" in blok, "panah tidak ditempel di tanggal sinyalnya"
    assert "arrowUp" in blok and "arrowDown" in blok


def test_imbal_risiko_dihitung_dan_ditandai():
    """Dua garis berdempetan bukan rencana. Kalau imbalannya lebih kecil
    dari risikonya, ia harus DITANDAI, bukan disajikan seolah peluang."""
    from core.rencana_chart import susun
    lv = lambda h, t, n=3: {"harga": h, "tipe": t, "sentuh": n,
                            "terakhir": "2026-09-01", "pertama": "2026-05-01",
                            "kuat": n >= 3, "nama": "L"}
    # jual cuma sedikit di atas beli, stop jauh -> tidak layak
    r = susun(1000, [lv(995, "support"), lv(1005, "resistance")], [],
              atr_pct=5.0)
    assert r["imbal_risiko"] is not None
    assert r["terlalu_sempit"] is True
    # jarak wajar -> layak
    r2 = susun(1000, [lv(980, "support"), lv(970, "support"),
                      lv(1100, "resistance")], [])
    assert r2["terlalu_sempit"] is False


# ---------------------------------------------------------------------------
# Pemisahan jalur: harmonic TIDAK boleh ikut menentukan beli/jual
# ---------------------------------------------------------------------------

def test_harmonic_tidak_menentukan_sinyal_beli_jual():
    """PERMINTAAN EKSPLISIT PENULIS: "buy jual nya itu bukan make
    harmonic ya".

    Harmonic boleh DIGAMBAR -- ia keterangan bentuk, dan pengguna yang
    menilai. Tapi ia tidak boleh ikut memutuskan kapan segitiga BELI
    atau JUAL muncul, dan keunggulannya sendiri memang belum pernah
    diukur terpisah dari saringan Minervini yang selama ini
    menyertainya.

    Dikunci lewat sumber kodenya karena jalurnya memang soal SIAPA
    MEMANGGIL SIAPA: begitu _sinyal_chart_payload atau
    _rencana_chart_payload menerima data harmonic, pemisahannya hilang
    tanpa satu pun hasil terlihat berubah di hari pertama."""
    for f in (app_module._sinyal_chart_payload,
              app_module._rencana_chart_payload):
        src = inspect.getsource(f)
        assert "harmonic" not in src.lower(), f.__name__


def test_harmonic_tidak_dioper_ke_pembangun_rencana():
    """Penjagaan di tingkat PEMANGGIL. Fungsi di atas bisa saja bersih
    isinya tapi menerima pola harmonic lewat argumen `pola`."""
    # Keempat lapisan kini dirakit di _chart_overlay_payload, jadi di
    # situlah pemisahannya harus diperiksa.
    src = inspect.getsource(app_module._chart_overlay_payload)
    assert "_rencana_chart_payload(df, pola, sr)" in src
    i_pola = src.index("pola = _pola_chart_payload(")
    i_harm = src.index("harmonic = _harmonic_chart_payload(")
    i_renc = src.index("_rencana_chart_payload(df, pola, sr)")
    assert i_pola < i_renc
    assert "pola = _harmonic" not in src
    assert i_harm != i_pola


def test_harmonic_tetap_dikirim_sbg_lapisan_terpisah():
    """Dipisah BUKAN berarti dibuang: ia tetap dikirim sbg medan
    sendiri supaya bisa digambar dan dinyalakan/dimatikan pengguna."""
    src = inspect.getsource(app_module.ohlc)
    assert '"harmonic": harmonic' in src
    assert 'ovl.get("harmonic")' in src
    js = open("web/static/app.js", encoding="utf-8").read()
    assert "_gambarHarmonic" in js
    # Penggambar sinyal tidak menyentuh data harmonic.
    i = js.index("function _gambarSinyal(")
    assert "harm" not in js[i:i + 900].lower()


# ---------------------------------------------------------------------------
# Kepadatan chart: lebih sedikit tampil sekaligus, TIDAK ada yang dibuang
# ---------------------------------------------------------------------------

def _js():
    return open("web/static/app.js", encoding="utf-8").read()


def test_sr_dibatasi_dua_per_sisi_secara_bawaan():
    """GEJALA: tangkapan layar penulis menunjukkan dua belas label
    berebut ruang di sumbu harga, beberapa saling menimpa sampai
    angkanya tidak terbaca. Chart yang labelnya tidak terbaca lebih
    buruk daripada chart dengan lebih sedikit garis."""
    js = _js()
    i = js.index("function _gambarSR(")
    blok = js[i:js.index("/* ---- Area beli", i)]
    assert "slice(0,2)" in blok and "slice(-2)" in blok
    assert "st.srPenuh" in blok, "harus ada jalan untuk menampilkan semuanya"


def test_sinyal_dibatasi_empat_terakhir_secara_bawaan():
    js = _js()
    i = js.index("function _gambarSinyal(")
    blok = js[i:js.index("/* ---- Pola ----", i)]
    assert "slice(-4)" in blok
    assert "st.sinyalPenuh" in blok


def test_tidak_ada_yang_dibuang_hanya_disembunyikan():
    """Permintaan penulis: "bikin lebih friendly tapi fungsi jangan di
    hilangkan". Pembatasan hanya boleh di TAMPILAN -- datanya tetap utuh
    dan tetap bisa dimunculkan."""
    js = _js()
    assert "data-srpenuh" in js and "data-sgpenuh" in js
    assert "Semua level" in js and "Semua sinyal" in js
    # Ringkasan tetap menghitung SELURUH sinyal, bukan yang tampil saja.
    i = js.index("const sg=st.sinyal||[];")
    assert "sg.filter(x=>x.hasil_pct!=null)" in js[i:i + 700]


def test_toggle_level_memasang_ulang_garis_BATAL():
    """CACAT YANG HAMPIR TERKIRIM. _gambarSR menghapus SELURUH price-line
    miliknya, termasuk garis BATAL yang dipasang _gambarRencana. Tanpa
    dipasang ulang, BATAL hilang diam-diam setiap kali tombol "Semua
    level" ditekan -- tanpa error, dan tanpa ada yang menyadarinya
    sampai seseorang bertanya ke mana garis stopnya."""
    js = _js()
    # Yang diperiksa LISTENER-nya, bukan markup chip-nya. "data-srpenuh"
    # muncul dua kali; yang pertama cuma atribut tombol.
    i = js.index("querySelectorAll('[data-srpenuh]')")
    blok = js[i:js.index("querySelectorAll('[data-sgpenuh]')", i)]
    assert "_gambarSR(" in blok
    assert "_gambarRencana(" in blok, "BATAL tidak dipasang ulang"
    assert "_renderPolaChips(" in blok, "tulisan tombolnya tidak akan berubah"


def test_pilihan_kepadatan_direset_tiap_ganti_saham():
    """Kalau terbawa, orang yang pernah menekan "Semua level" di satu
    saham akan mendapati chart saham berikutnya penuh garis tanpa tahu
    sebabnya."""
    js = _js()
    i = js.index("function _pasangOverlay(")
    blok = js[i:i + 1200]
    assert "st.srPenuh=false" in blok and "st.sinyalPenuh=false" in blok


def test_xabcd_mati_secara_bawaan():
    """Lapisan paling berat secara visual, dan keunggulannya BELUM
    terukur. Menyalakannya secara bawaan berarti memajang garis paling
    ramai untuk hal yang paling sedikit diketahui."""
    js = _js()
    i = js.index("st.harm=o.harmonic")
    assert "_gambarHarmonic(kunci, -1)" in js[i:i + 500]
    # ...tapi chip-nya tetap ada.
    assert "data-harm" in js


def test_penanda_sinyal_tidak_lagi_mengulang_harga():
    """Posisi panah di chart sudah menunjukkan harganya; menuliskannya
    lagi membuat tiap penanda tiga kali lebih panjang, dan ada empat di
    layar sekaligus."""
    js = _js()
    i = js.index("function _gambarSinyal(")
    blok = js[i:js.index("/* ---- Pola ----", i)]
    assert "text:`${x.jenis}${ekor}`" in blok
    assert "_rpT(x.harga)" not in blok


# ---------------------------------------------------------------------------
# Lapisan sinyal menyusul, tidak menahan
# ---------------------------------------------------------------------------

def test_sinyal_tidak_menahan_pembukaan_chart():
    """UKURAN NYATA: pemindaian sinyal 18,7 ms x 170 bar = 3,2 detik
    kerja Python MURNI. Memindahkannya ke worker thread saja tidak
    cukup -- Python tidak menjalankan kerja CPU secara paralel (GIL),
    jadi sepuluh orang yang membuka chart saham berbeda bersamaan tetap
    berarti 32 detik berurutan.

    Diukur sesudah diperbaiki: pembukaan pertama 1,0-1,6 detik (dari
    3,5-4 detik), pembukaan berikutnya 73-102 ms."""
    src = inspect.getsource(app_module.ohlc)
    assert "_jalankan_latar(_sinyal_chart_latar" in src
    # Dan ia TIDAK ditunggu -- kalau di-await, tidak ada yang berubah.
    assert "await _sinyal_chart_latar" not in src


def test_sinyal_kosong_TIDAK_ikut_tercache_di_overlay():
    """CACAT YANG DICEGAH: kalau daftar sinyal kosong ikut tersimpan di
    cache overlay, ia terkunci selama TTL overlay (15 menit) -- sehingga
    segitiganya tidak pernah muncul walau penghitungannya selesai dua
    detik kemudian. Tanpa error apa pun."""
    ovl = inspect.getsource(app_module._chart_overlay_payload)
    assert '"sinyal"' not in ovl, "sinyal tidak boleh disimpan di overlay"
    src = inspect.getsource(app_module.ohlc)
    assert 'sinyal = _cache_get(f"sinyalchart:' in src


def test_tugas_latar_dipegang_rujukannya():
    """asyncio hanya memegang rujukan LEMAH ke tugas yang berjalan.
    Tugas yang tidak dipegang siapa pun bisa dibuang pemulung memori di
    tengah jalan -- dan gejalanya paling jahat: tidak selalu terjadi,
    dan ketika terjadi tidak ada error, sinyalnya cuma kadang tidak
    pernah muncul."""
    src = inspect.getsource(app_module._jalankan_latar)
    assert "_TUGAS_LATAR.add" in src
    assert "add_done_callback" in src, "rujukan harus dilepas saat selesai"


def test_penghitungan_latar_tidak_dijadwalkan_berulang():
    """Chart menyegarkan dirinya tiap 30 detik. Tanpa penjaga, pembukaan
    yang sama menjadwalkan penghitungan 3 detik berkali-kali sebelum
    yang pertama sempat selesai."""
    src = inspect.getsource(app_module._sinyal_chart_latar)
    assert "_SINYAL_SEDANG_DIHITUNG" in src
    assert "finally:" in src, "penjaga harus dilepas walau gagal"
