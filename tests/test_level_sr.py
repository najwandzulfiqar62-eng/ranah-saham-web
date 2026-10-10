"""Penjaga level S/R dan rencana chart.

Yang dikunci adalah sifat yang kalau rusak membuat garis di chart
berbohong tanpa satu pun error muncul.
"""

from core import level_sr as ls
from core import rencana_chart as rc


def _deret(n=300, seed=11):
    """Jalan acak yang dapat diulang, tanpa numpy."""
    harga, x, s = [], 1000.0, seed
    for _ in range(n):
        s = (1103515245 * s + 12345) % (1 << 31)
        x *= 1 + ((s / (1 << 31)) - 0.5) * 0.05
        harga.append(x)
    return ([f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n)],
            [h * 1.012 for h in harga], [h * 0.988 for h in harga], harga)


def _pantul(n=260, level=1000.0):
    """Harga yang berulang kali memantul di satu level -- support yang
    benar-benar teruji, bukan kebetulan."""
    tinggi, rendah, tutup = [], [], []
    for i in range(n):
        fase = i % 40
        # turun menyentuh `level`, lalu naik 12%, berulang
        v = level * (1 + 0.12 * abs(fase - 20) / 20)
        tutup.append(v)
        tinggi.append(v * 1.01)
        rendah.append(v * 0.995 if fase != 20 else level)
    return ([f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n)],
            tinggi, rendah, tutup)


# ---------------------------------------------------------------------------
# Level
# ---------------------------------------------------------------------------

def test_level_berulang_ditemukan_dan_ditandai_kuat():
    tgl, hi, lo, cl = _pantul()
    lv = ls.cari_level(tgl, hi, lo, cl)
    assert lv, "level yang dipantul belasan kali tidak ketemu"
    assert any(x.sentuh >= 3 and x.kuat for x in lv)


def test_level_tidak_dihasilkan_dari_pemotongan_kotak():
    """BUG NYATA: versi pertama membagi titik jadi kelompok berurutan
    selebar tetap. Hasilnya di BBCA: empat "level" berjarak hampir rata,
    masing-masing tepat 4 sentuhan -- itu bekas potongan, bukan level.
    Levelnya bergeser hanya karena titik pertama kebetulan berbeda, dan
    empat garis rapi terlihat persis seperti analisis yang benar.

    Diuji lewat sifatnya: pada jalan acak, jarak antar-level tidak boleh
    hampir seragam."""
    tgl, hi, lo, cl = _deret(seed=23)
    lv = sorted(ls.cari_level(tgl, hi, lo, cl), key=lambda x: x.harga)
    if len(lv) < 4:
        return                      # tidak cukup untuk menguji keseragaman
    jarak = [b.harga - a.harga for a, b in zip(lv, lv[1:])]
    rata = sum(jarak) / len(jarak)
    sebar = max(abs(j - rata) for j in jarak) / rata
    assert sebar > 0.1, f"jarak antar-level terlalu seragam ({sebar:.3f})"


def test_titik_balik_tunggal_ikut_tapi_DIBEDAKAN():
    """Diperiksa pada BBCA: cuma 3 pivot low di bawah harga dan tak satu
    pun berpasangan, sehingga aturan "minimal dua sentuhan" melaporkan
    TIDAK ADA support sama sekali -- padahal dasarnya jelas terlihat di
    chart. Keduanya kini ditampilkan, dengan perbedaan yang DIJAGA."""
    tgl, hi, lo, cl = _deret(seed=5)
    lv = ls.cari_level(tgl, hi, lo, cl)
    for x in lv:
        assert x.sentuh >= 1
        # Satu sentuhan TIDAK boleh ditandai kuat.
        if x.sentuh == 1:
            assert not x.kuat
        if x.kuat:
            assert x.sentuh >= 3


def test_setiap_level_punya_nama_peran():
    """Nama peran itu yang membedakan "Support Terdekat" dari "Dasar
    Mayor" -- dua pertanyaan berbeda. Level tanpa nama akan tampil di
    chart sbg garis tanpa keterangan."""
    tgl, hi, lo, cl = _deret(seed=7)
    for x in ls.cari_level(tgl, hi, lo, cl):
        assert x.nama, f"level {x.harga} tanpa nama"
        assert x.nama in (ls._NAMA_RESISTANCE + ls._NAMA_SUPPORT
                          + ["Dasar Mayor", "Puncak Mayor"])


def test_tipe_level_konsisten_dengan_harga_sekarang():
    """Resistance harus DI ATAS harga dan support DI BAWAH. Kalau
    terbalik, garis merah muncul di bawah candle dan seluruh panel
    terbaca kacau."""
    tgl, hi, lo, cl = _deret(seed=31)
    kini = cl[-1]
    for x in ls.cari_level(tgl, hi, lo, cl):
        if x.tipe == "resistance":
            assert x.harga > kini
        else:
            assert x.harga < kini


def test_lebar_kelompok_mengikuti_volatilitas():
    """Ambang 1,5% tetap itu longgar untuk saham tenang dan sempit untuk
    saham liar. Lebar kelompok harus ikut ATR."""
    assert ls.PENGALI_ATR > 0
    tenang = ls._atr_pct([100.2] * 30, [99.8] * 30, [100.0] * 30)
    liar = ls._atr_pct([110.0] * 30, [90.0] * 30, [100.0] * 30)
    assert liar > tenang * 3


def test_deret_pendek_tidak_meledak():
    tgl, hi, lo, cl = _deret(n=30)
    assert ls.cari_level(tgl, hi, lo, cl) == []
    assert ls.cari_level([], [], [], []) == []


# ---------------------------------------------------------------------------
# Rencana
# ---------------------------------------------------------------------------

def _lvl(harga, tipe, sentuh=3, nama="Support Terdekat"):
    return {"harga": harga, "tipe": tipe, "sentuh": sentuh,
            "terakhir": "2026-09-01", "pertama": "2026-05-01",
            "kuat": sentuh >= 3, "nama": nama}


def test_rencana_tanpa_angka_keyakinan_karangan():
    """Aplikasi pembanding menampilkan "75% confidence" tanpa menyebut
    asalnya. Angka keyakinan karangan adalah kebohongan yang paling
    sulit dibantah pembaca -- ia terlihat persis seperti hasil
    perhitungan."""
    # Diuji lewat KELUARANNYA, bukan lewat teks sumbernya. Versi pertama
    # memindai sumber dan menyala karena docstring yang justru
    # MENJELASKAN kenapa angka itu tidak ada -- penjaga yang menyala
    # karena kalimat penjelasan akan dimatikan orang, lalu berhenti
    # menjaga hal yang sungguhan. (Kesalahan yang sama pernah terjadi di
    # penjaga pola chart.)
    pola = [{"nama": "Segitiga Menaik", "arah": "naik", "fase": "TEMBUS",
             "level_kunci": 1100, "unggul_pct": 3.24, "n_ukur": 464}]
    r = rc.susun(1000, [_lvl(950, "support"),
                        _lvl(1100, "resistance", 4, "Resistance Terdekat")],
                 pola)
    assert "confidence" not in str(r).lower()
    # Tidak ada medan yang menjanjikan peluang/keyakinan.
    for k in r:
        assert not any(x in k.lower()
                       for x in ("confidence", "keyakinan", "probabilitas",
                                 "peluang", "akurasi")), k
    # Angka yang BOLEH muncul di narasi hanyalah hasil ukur yang dioper
    # masuk; kalau polanya tanpa angka ukur, narasinya tidak mengarang.
    tanpa_ukur = [{**pola[0], "unggul_pct": None, "n_ukur": None}]
    r2 = rc.susun(1000, [_lvl(950, "support")], tanpa_ukur)
    assert "Diukur pada" not in r2["narasi"]


def test_beli_di_support_jual_di_resistance():
    r = rc.susun(1000, [_lvl(950, "support"),
                        _lvl(1100, "resistance", 4, "Resistance Terdekat")], [])
    assert r["beli"]["harga"] == 950
    assert r["jual"]["harga"] == 1100
    assert r["beli"]["jarak_pct"] < 0 < r["jual"]["jarak_pct"]


def test_satu_sentuhan_tidak_disebut_teruji():
    """"teruji 1x" itu kontradiksi: satu sentuhan justru BELUM teruji.
    Membiarkannya membuat level satu-sentuhan terbaca sekuat level yang
    bertahan delapan kali."""
    r = rc.susun(1000, [_lvl(950, "support", sentuh=1)], [])
    assert r["beli"]["teruji"] is False
    assert "teruji 1" not in r["beli"]["alasan"]
    assert "belum teruji" in r["beli"]["alasan"]


def test_arah_pola_ditentukan_angka_terukur_bukan_namanya():
    """Inverse H&S terukur -1,12%, yaitu BERLAWANAN dengan artinya.
    Membiarkan namanya menarik bias ke atas berarti mengulang kesalahan
    yang pengukurannya justru temukan."""
    pola = [{"nama": "Inverse Head & Shoulders", "arah": "naik",
             "fase": "TEMBUS", "level_kunci": 1050, "unggul_pct": -1.12,
             "n_ukur": 199}]
    r = rc.susun(1000, [_lvl(950, "support")], pola, ma20=1010, ma50=1020)
    assert r["skor_bias"] < 0, r["skor_bias"]


def test_bias_boleh_netral():
    """Memaksa tiap saham punya arah berarti memberi sinyal pada saham
    yang sedang tidak mengatakan apa-apa -- dan itu sebagian besar
    saham, sebagian besar waktu."""
    r = rc.susun(1000, [_lvl(950, "support")], [], ma20=1000, ma50=990)
    assert r["bias"] == "netral"


def test_invalidasi_tidak_memakai_3_persen_sbg_cadangan():
    """Stop 3% terukur kena 53,8% dari waktu oleh gerak harian biasa.
    Memakainya sbg cadangan akan menanam ulang persis kesalahan yang
    modul ATR dibuat untuk memperbaiki."""
    r = rc.susun(1000, [_lvl(950, "support")], [], atr_pct=4.0)
    jatuh = (950 - r["invalidasi"]) / 950 * 100
    assert jatuh > 3.0, f"jarak invalidasi cuma {jatuh:.1f}%"


def test_narasi_tidak_pecah_oleh_pemisah_ribuan():
    """BUG NYATA: .replace(",", ".") dipanggil pada SELURUH kalimat,
    sehingga koma kalimatnya ikut jadi titik -- "1.164 kejadian. pola di
    fase ini" -- dan pembaca menyangka ada teks yang hilang."""
    pola = [{"nama": "Segitiga Menaik", "arah": "naik", "fase": "TERBENTUK",
             "level_kunci": 1100, "unggul_pct": -0.60, "n_ukur": 1164}]
    r = rc.susun(1000, [_lvl(950, "support")], pola, ma20=1010, ma50=1020)
    n = r["narasi"]
    assert "1.164 kejadian, pola" in n, n
    assert "kejadian. pola" not in n
    # Desimal pakai koma, seperti seluruh aplikasi.
    assert "-0,60%" in n and "-0.60%" not in n


def test_narasi_menyebut_angka_yang_bisa_diperiksa():
    r = rc.susun(1000, [_lvl(950, "support", 4),
                        _lvl(1100, "resistance", 3, "Resistance Terdekat")],
                 [], ma20=1010, ma50=1020)
    n = r["narasi"]
    assert "Rp950" in n and "Rp1.100" in n
    assert "4× teruji" in n


def test_rencana_kosong_tidak_meledak():
    assert rc.susun(0, [], []) == {}
    r = rc.susun(1000, [], [])
    assert r["beli"] is None and r["jual"] is None
    assert r["invalidasi"] < 1000


# ---------------------------------------------------------------------------
# Area jual = tempat tekanan beli terbukti melemah
# ---------------------------------------------------------------------------

def _L(h, t, n, nama="L"):
    return {"harga": h, "tipe": t, "sentuh": n, "terakhir": "2026-09-01",
            "pertama": "2026-05-01", "kuat": n >= 3, "nama": nama}


_POLA_NAIK = [{"nama": "Segitiga Menaik", "arah": "naik", "fase": "TEMBUS",
               "level_kunci": 1010, "unggul_pct": 3.24, "n_ukur": 464}]


def test_di_tren_naik_atap_lemah_jadi_target_bukan_tempat_jual():
    """PERMINTAAN PENULIS: "untuk area jual cari area pucuk/tekanan beli
    melemah; kalau masih potensi naik ya cari area buy lagi".

    Benar, dan versi pertama keliru: ia selalu memakai atap TERDEKAT. Di
    tren yang sedang naik, atap terdekat justru yang paling sering
    tertembus -- menyuruh jual di situ berarti menyuruh keluar dari tren
    yang masih berjalan."""
    lv = [_L(950, "support", 4, "Support Terdekat"),
          _L(1020, "resistance", 1, "Resistance Terdekat"),   # lemah
          _L(1150, "resistance", 5, "Resistance Swing")]      # pucuk nyata
    r = rc.susun(1000, lv, _POLA_NAIK, ma20=980, ma50=960)
    assert r["bias"] == "bullish"
    assert r["jual"]["harga"] == 1150, "jual harus di pucuk, bukan atap terdekat"
    assert 1020 in r["target"], "atap lemah harus jadi target"


def test_tren_naik_tanpa_pucuk_teruji_TIDAK_punya_area_jual():
    """Ketiadaan area jual itu TEMUAN, bukan kolom yang gagal terisi.
    Memaksa satu angka berarti mengarang titik keluar supaya kolomnya
    tidak kosong."""
    lv = [_L(950, "support", 4, "Support Terdekat"),
          _L(1020, "resistance", 1, "Resistance Terdekat")]
    r = rc.susun(1000, lv, _POLA_NAIK, ma20=980, ma50=960)
    assert r["bias"] == "bullish"
    assert r["jual"] is None
    # ...tapi area BELI tetap ada: "kalau masih potensi naik ya cari
    # area buy lagi".
    assert r["beli"]["harga"] == 950
    assert "belum ada area jual" in r["narasi"].lower()


def test_di_luar_tren_naik_jual_tetap_di_pucuk_terkuat():
    """Bukti penolakan tetap yang menentukan, bukan kedekatan."""
    lv = [_L(950, "support", 4), _L(1020, "resistance", 1, "Resistance Terdekat"),
          _L(1150, "resistance", 5, "Resistance Swing")]
    r = rc.susun(1000, lv, [], ma20=1050, ma50=1080)
    assert r["jual"]["harga"] == 1150


def test_pucuk_dipilih_dari_bukti_penolakan_bukan_kedekatan():
    lv = [_L(950, "support", 3),
          _L(1010, "resistance", 2, "Resistance Terdekat"),
          _L(1080, "resistance", 6, "Resistance Swing"),
          _L(1200, "resistance", 3, "Puncak Mayor")]
    r = rc.susun(1000, lv, [], ma20=1000, ma50=1000)
    assert r["jual"]["harga"] == 1080, "yang 6x ditolak harus menang"


def test_seri_sentuhan_dimenangkan_yang_terdekat():
    """Level jauh benar, tapi tidak menolong keputusan minggu ini."""
    lv = [_L(950, "support", 3),
          _L(1050, "resistance", 4, "Resistance Terdekat"),
          _L(1250, "resistance", 4, "Resistance Swing")]
    r = rc.susun(1000, lv, [], ma20=1000, ma50=1000)
    assert r["jual"]["harga"] == 1050
