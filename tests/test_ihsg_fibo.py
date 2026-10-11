"""Fibonacci IHSG: satu mesin, bukan dua jawaban di satu layar.

TEMUAN 12 OKT 2026. Penulis sudah pernah meminta "di bagian ihsg juga
chartnya disamain". Chartnya memang sudah memakai mesin berarah
(core/fibo.py, lewat /api/ohlc), tapi panel "Level Kunci" di sebelahnya
dan SKOR bullish/bearish-nya masih memakai hitungan lama:

    high_50 = High.tail(50).max()
    low_50  = Low.tail(50).min()
    fib_382 = low_50 + (high_50 - low_50) * 0.382

Tertinggi dan terendah dalam 50 bar, TANPA memedulikan mana yang lebih
dulu -- persis cacat yang sudah didokumentasikan dan diperbaiki untuk
chart emiten. Kalau puncaknya terjadi SEBELUM lembahnya, level "38,2%
dari low ke high" mengukur gerakan yang tidak pernah terjadi ke arah itu.

Jadi satu layar IHSG menampilkan dua jawaban Fibonacci yang berbeda, dan
yang buta arah itu yang menyumbang +-10 poin ke skornya.
"""
import inspect
import io
import os

import pandas as pd
import pytest

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _deret(naik=True, n=320, besar=0.30):
    """Ayunan buatan dengan urutan pivot yang PASTI: mendatar, lalu
    bergerak besar satu arah, lalu mundur sedikit.

    Ujung ayunannya SENGAJA ditaruh ~40 bar dari akhir deret. core/fibo.py
    menolak ayunan yang lebih tua dari MAKS_UMUR_BAR=60 -- ayunan dari
    setengah tahun lalu bukan keadaan sekarang -- dan versi pertama uji
    ini menaruhnya 100 bar dari akhir, lalu gagal karena penolakan yang
    justru benar."""
    harga = []
    for i in range(n):
        if i < 150:
            v = 1000 + (i % 4)
        elif i < 280:
            laju = besar * (i - 150) / 130
            v = 1000 * (1 + laju if naik else 1 - laju)
        else:
            puncak = 1000 * (1 + besar if naik else 1 - besar)
            mundur = 0.25 * besar * (i - 280) / 40
            v = puncak * (1 - mundur if naik else 1 + mundur)
        harga.append(v)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "Open": harga, "Close": harga,
        "High": [h * 1.004 for h in harga],
        "Low": [h * 0.996 for h in harga],
        "Volume": [1_000_000] * n,
    }, index=idx)


@pytest.fixture
def hasil_naik():
    from core.ihsg.ihsg_analysis import analyze_ihsg_advanced
    d = _deret(naik=True)
    w = d.resample("W").agg({"Open": "first", "High": "max", "Low": "min",
                             "Close": "last", "Volume": "sum"}).dropna()
    return analyze_ihsg_advanced(d, w)


# ---------------------------------------------------------------------------
# Satu mesin
# ---------------------------------------------------------------------------

def test_level_fibonacci_datang_dari_mesin_berarah():
    """Yang DITAMPILKAN sebagai level Fibonacci harus datang dari
    core/fibo.py, mesin yang sama dengan chart emiten.

    Rumus rentang (low + range*rasio) tetap ada di fungsi ini, tapi untuk
    hal LAIN -- lihat uji berikutnya."""
    from core.ihsg import ihsg_analysis
    src = inspect.getsource(ihsg_analysis.analyze_ihsg_advanced)
    assert "from core.fibo import hitung" in src
    # Level yang dikirim ke layar diambil dari hasil mesin itu, bukan
    # dirakit dari rentang.
    assert 'fib_382, fib_500, fib_618 = (_per.get(0.382)' in src


def test_skor_memakai_POSISI_RENTANG_dan_tidak_tertukar_dengan_level():
    """CACAT YANG SAYA MASUKKAN SENDIRI LALU PERBAIKI, dicatat supaya
    tidak terulang.

    Sesudah fib_382/500/618 diganti mesin berarah, ember skornya ikut
    memakai nilai baru itu:

        if current_price > fib_618: "ABOVE-618"  -> bearish +10

    Ember itu mengandaikan fib_618 yang TERTINGGI -- benar untuk rumus
    rentang (rasio besar = harga tinggi), tapi mesin berarah menghitung
    retracement MUNDUR dari ujung ayunan, jadi pada ayunan NAIK fib_618
    justru yang TERENDAH. Harga sesudah koreksi sebagian hampir selalu di
    atasnya, sehingga setiap ayunan naik akan selalu dibaca "ABOVE-618"
    dan selalu dihukum -10. Tanda sebuah skor terbalik, tanpa satu pun
    error.

    AKARNYA: fib_position tidak pernah mengukur kedalaman retracement. Ia
    mengukur posisi harga dalam rentang 50 bar -- lebih mirip Stochastic
    atas rentang harga. Keduanya TIDAK bisa dipetakan satu ke satu:
    koreksi dalam pada ayunan naik berada di BAWAH rentang, pada ayunan
    turun di ATAS-nya.

    Jadi keduanya dipisah, dan skornya kembali PERSIS seperti semula."""
    from core.ihsg import ihsg_analysis
    src = inspect.getsource(ihsg_analysis.analyze_ihsg_advanced)
    i = src.index('if current_price > ')
    blok = src[i:src.index('"BELOW-382"', i)]
    # Embernya membandingkan terhadap level RENTANG (_r*), bukan terhadap
    # level Fibonacci berarah.
    assert "_r618" in blok and "_r500" in blok and "_r382" in blok
    for tertukar in ("fib_618", "fib_500", "fib_382"):
        assert tertukar not in blok, (
            f"ember skor memakai {tertukar} (level berarah); pada ayunan "
            "naik urutannya terbalik dan tandanya ikut terbalik")


def test_hitungan_posisi_rentang_tidak_berubah_sama_sekali():
    """Nol perubahan pada vonis IHSG. Rumusnya, jendelanya, dan jalur
    cadangan tail(20)-nya harus sama persis dengan sebelum hari ini --
    yang diperbaiki levelnya yang DITAMPILKAN, bukan skornya."""
    from core.ihsg import ihsg_analysis
    src = inspect.getsource(ihsg_analysis.analyze_ihsg_advanced)
    for wajib in ('df_daily["High"].tail(50).max()',
                  'df_daily["Low"].tail(50).min()',
                  'df_daily["High"].tail(20).max()',
                  'df_daily["Low"].tail(20).min()',
                  "_rg * 0.382", "_rg * 0.5", "_rg * 0.618"):
        assert wajib in src, wajib


def test_arah_ayunan_ikut_dikirim(hasil_naik):
    """"38,2%" pada ayunan naik dan pada ayunan turun adalah dua keadaan
    yang sama sekali berbeda. Angka tanpa arah tidak bisa dibaca."""
    assert hasil_naik is not None
    assert hasil_naik["fib_arah"] in ("naik", "turun")


def test_level_berurutan_naik(hasil_naik):
    """38,2% < 50% < 61,8% dalam harga pada ayunan naik: retracement
    diukur MUNDUR dari puncak, jadi rasio yang lebih besar ada lebih
    jauh ke bawah... yaitu lebih KECIL harganya."""
    f382, f500, f618 = (hasil_naik["fib_382"], hasil_naik["fib_500"],
                        hasil_naik["fib_618"])
    assert None not in (f382, f500, f618)
    if hasil_naik["fib_arah"] == "naik":
        assert f382 > f500 > f618
    else:
        assert f382 < f500 < f618


# ---------------------------------------------------------------------------
# Tanpa ayunan = tanpa pendapat
# ---------------------------------------------------------------------------

def test_tanpa_ayunan_levelnya_None_dan_analisisnya_tetap_jalan():
    """Deret nyaris datar: tidak ada ayunan yang cukup besar untuk
    ditarik Fibonacci.

    Yang HARUS terjadi: levelnya None, arahnya None, dan analisis IHSG
    selebihnya tetap berjalan. Kehilangan satu bagian jauh lebih baik
    daripada kehilangan seluruh jawabannya -- dan None jauh lebih baik
    daripada nol, karena nol adalah harga yang salah sementara None
    adalah pernyataan yang benar.

    Versi pertama uji ini membungkus seluruh pemeriksaannya dalam
    `if r["fib_position"] is None:` -- dan sesudah fib_position
    dikembalikan ke hitungan rentang (yang SELALU menghasilkan nilai),
    cabang itu tidak pernah dimasuki. Ujinya lolos tanpa menguji apa
    pun. Uji hampa lebih berbahaya daripada tidak ada uji: ia terhitung
    hijau."""
    from core.ihsg.ihsg_analysis import analyze_ihsg_advanced
    d = _deret(naik=True, besar=0.004)      # nyaris datar
    w = d.resample("W").agg({"Open": "first", "High": "max", "Low": "min",
                             "Close": "last", "Volume": "sum"}).dropna()
    r = analyze_ihsg_advanced(d, w)
    assert r is not None, "analisisnya tidak boleh gagal, cuma tanpa Fibonacci"
    assert r["fib_arah"] is None, "ayunan sekecil ini tidak boleh diterima"
    assert r["fib_382"] is None and r["fib_500"] is None
    assert r["fib_618"] is None
    # Dan skornya tetap terbentuk -- posisi rentang tidak bergantung pada
    # ada-tidaknya ayunan.
    assert r["fib_position"] is not None
    assert r["prediction"]


def test_bobot_skornya_TIDAK_diubah():
    """Yang diperbaiki MASUKANNYA, bukan bobotnya.

    BELOW-382 -> +10 bullish dan ABOVE-618 -> +10 bearish adalah asumsi
    PEMBALIKAN KE RATA-RATA, dan asumsi itu belum pernah diukur di
    tingkat indeks. Pengukuran Fibonacci per emiten di proyek ini justru
    mengarah sebaliknya: menyentuh level retracement dalam ayunan turun
    berkinerja DI BAWAH pasar (-2,12% pada 23,6%).

    Jadi bobot ini patut dipertanyakan -- tapi mengubahnya menggeser
    setiap vonis IHSG, dan itu keputusan yang harus diambil dengan angka
    di tangan, bukan disisipkan bersama perbaikan masukan. Uji ini
    memastikan perubahannya tidak terjadi diam-diam."""
    from core.ihsg import ihsg_analysis
    src = inspect.getsource(ihsg_analysis.analyze_ihsg_advanced)
    i = src.index('if fib_position == "BELOW-382"')
    blok = src[i:src.index("if current_rsi <", i)]
    assert "bullish_score += 10" in blok
    assert "bearish_score += 10" in blok


# ---------------------------------------------------------------------------
# Layar
# ---------------------------------------------------------------------------

def test_layar_menyiapkan_keadaan_tanpa_ayunan():
    """fib_382 kini bisa None. Tanpa cabangnya, selnya menampilkan
    "–/–/–" yang terbaca seperti data gagal diambil, padahal artinya
    "tidak ada ayunan yang cukup besar"."""
    js = io.open(os.path.join(AKAR, "web", "static", "app.js"),
                 encoding="utf-8").read()
    # Dijangkar pada SYARATNYA, bukan pada labelnya: cabang null berdiri
    # sebelum label dan pesan "belum ada ayunan" sesudahnya, jadi label
    # bukan titik awal yang bisa memuat keduanya.
    i = js.index("d.fib_382!=null")
    blok = js[i:i + 900]
    assert "Fibonacci .382/.5/.618" in blok
    assert "belum ada ayunan" in blok


def test_arah_ditampilkan_di_panel():
    js = io.open(os.path.join(AKAR, "web", "static", "app.js"),
                 encoding="utf-8").read()
    i = js.index("Fibonacci .382/.5/.618")
    assert "d.fib_arah" in js[i:i + 400]


def test_endpoint_meneruskan_arah():
    """Dihitung di core tapi tidak diteruskan = medan yang tidak pernah
    sampai ke layar, diam-diam, tanpa error."""
    app = io.open(os.path.join(AKAR, "web", "app.py"), encoding="utf-8").read()
    assert '"fib_arah": analysis.get("fib_arah")' in app


# ---------------------------------------------------------------------------
# Gambar statis: yang dikirim ke WhatsApp harus sama dengan yang di website
# ---------------------------------------------------------------------------
# Tiga tempat memakai Fibonacci buta arah, dan dua di antaranya GAMBAR yang
# dikirim lewat bot. Jadi untuk saham yang SAMA pada hari yang SAMA, garis
# Fibonacci di WhatsApp berbeda dari garis di website -- dan yang di
# WhatsApp dihitung dengan cara yang komentar di web/app.py sendiri sebut
# cacat. Perbedaan itu tidak akan pernah dilaporkan sebagai bug, karena
# tidak ada yang membandingkan dua layar berdampingan.


def _sumber(jalur):
    return io.open(os.path.join(AKAR, *jalur.split("/")),
                   encoding="utf-8").read()


def _kode_saja(jalur):
    """Sumbernya TANPA baris komentar.

    Penjaga di bawah memeriksa apa yang berkasnya KERJAKAN. Komentarnya
    justru mengutip bentuk hitungan yang lama -- itu gunanya, supaya
    tidak dipungut lagi -- dan penjaga yang menyala karena kalimat
    penjelasan akan dimatikan orang.

    Di proyek ini kesalahan ini sudah terjadi ENAM kali, termasuk pada
    penjaga ini sendiri saat pertama ditulis."""
    return "\n".join(b for b in _sumber(jalur).splitlines()
                     if not b.strip().startswith("#"))


@pytest.mark.parametrize("jalur", [
    "core/ihsg/ihsg_chart.py",       # chart IHSG 4 panel -> WhatsApp
    "core/charts/ta_chart.py",       # chart TA emiten    -> WhatsApp
])
def test_gambar_statis_memakai_mesin_berarah(jalur):
    assert "from core.fibo import hitung" in _sumber(jalur), jalur
    # Bentuk hitungan lamanya tidak boleh kembali -- diperiksa pada BARIS
    # KODE saja, karena komentar di berkas itu memang mengutipnya.
    kode = _kode_saja(jalur)
    for terlarang in ("tail(50).max()", "tail(50).min()",
                      "calculate_fibonacci_levels(df,"):
        assert terlarang not in kode, (jalur, terlarang)


def test_tanpa_ayunan_garisnya_tidak_digambar():
    """Garis Fibonacci dari jendela lama lebih buruk daripada tidak ada
    garis: gambar tanpa garis menyatakan "tidak ada ayunan yang cukup
    besar", sementara garis yang salah menyatakan sesuatu yang tidak
    benar DAN tidak bisa dibedakan dari yang benar."""
    ta = _sumber("core/charts/ta_chart.py")
    i = ta.index("# Fibonacci levels")
    assert "if fib:" in ta[i:i + 300]
    ih = _sumber("core/ihsg/ihsg_chart.py")
    j = ih.index("FIBONACCI BERARAH")
    assert "if _fb:" in ih[j:j + 1800]


def test_fungsi_lama_tidak_lagi_dipakai_chart():
    """calculate_fibonacci_levels() dibiarkan ADA di core/indicators.py --
    membuangnya bukan bagian dari perbaikan ini -- tapi ia tidak boleh
    lagi punya pemakai yang menggambar ke layar atau ke gambar."""
    import subprocess
    hasil = subprocess.run(
        ["git", "grep", "-ln", "calculate_fibonacci_levels", "--",
         "core", "web"],
        cwd=AKAR, capture_output=True, text=True)
    berkas = {b for b in hasil.stdout.split() if b}
    # Yang boleh menyebutnya: tempat ia DIDEFINISIKAN, dan komentar yang
    # menjelaskan kenapa ia tidak dipakai lagi.
    boleh = {"core/indicators.py", "web/app.py", "core/charts/ta_chart.py"}
    assert berkas <= boleh, f"pemakai baru fungsi lama: {berkas - boleh}"


# ---------------------------------------------------------------------------
# Jendela & event loop
# ---------------------------------------------------------------------------

def test_fibonacci_ihsg_memakai_histori_panjang():
    """df_daily cuma period='3mo' (~62 bar), sementara core/fibo.py
    dirancang mencari pivot dalam JENDELA=180 bar. Diberi 62 bar ia
    bekerja pada SEPERTIGA jendelanya -- jadi ayunan dominan IHSG dicari
    di rentang yang jauh lebih pendek daripada yang dipakai emiten mana
    pun, tanpa satu pun error yang menandainya.

    Histori panjangnya sudah diambil endpoint-nya untuk backtest, jadi
    memakainya di sini tidak menambah pengambilan data."""
    from core.ihsg import ihsg_analysis
    src = inspect.getsource(ihsg_analysis.analyze_ihsg_with_backtest)
    assert "analyze_ihsg_advanced(df_daily, df_weekly, df_longer_history)" in src


def test_jendela_panjang_dipakai_hanya_kalau_memang_lebih_panjang():
    """Pemanggil lain (mis. uji, atau kode yang belum tahu parameter
    ketiganya) tetap harus bekerja. Dan kalau yang diberikan justru
    LEBIH PENDEK, ia tidak boleh dipakai."""
    from core.ihsg import ihsg_analysis
    src = inspect.getsource(ihsg_analysis.analyze_ihsg_advanced)
    assert "len(df_fibo) > len(df_daily)" in src
    d = _deret(naik=True)
    w = d.resample("W").agg({"Open": "first", "High": "max", "Low": "min",
                             "Close": "last", "Volume": "sum"}).dropna()
    # Tanpa argumen ketiga: tetap jalan.
    assert ihsg_analysis.analyze_ihsg_advanced(d, w) is not None


def test_laporan_ihsg_tidak_menahan_event_loop():
    """/api/ihsg sudah memakai asyncio.to_thread sejak lama;
    /api/ihsg/report terlewat dan memanggil hitungan yang sama beratnya
    -- 10 teknik analisis ditambah backtest 2 tahun -- langsung di event
    loop. Satu permintaan laporan karenanya menahan SELURUH pengunjung
    lain, bukan cuma dirinya sendiri."""
    app = io.open(os.path.join(AKAR, "web", "app.py"), encoding="utf-8").read()
    i = app.index('@app.get("/api/ihsg/report")')
    blok = app[i:app.index("@app.", i + 10)]
    assert "analyze_ihsg_with_backtest" in blok
    assert "asyncio.to_thread(analyze_ihsg_with_backtest" in blok, (
        "dipanggil langsung di event loop")


def test_kunci_cache_ihsg_berversi():
    """Payload IHSG bertambah medan `fib_arah`, dan nilai fib_382/500/618
    kini dihitung dengan cara yang berbeda. Tanpa versi kunci yang naik,
    server menyajikan payload LAMA sampai TTL habis -- panelnya
    menampilkan angka buta arah sementara chartnya sudah berarah, yaitu
    persis ketidaksesuaian yang baru diperbaiki, cuma lebih sulit
    dilacak karena ia hilang sendiri sesudah beberapa menit.

    Jebakan ini sudah berulang di proyek ini: mengubah bentuk payload
    tanpa menaikkan versi kuncinya bukan menghasilkan error, melainkan
    kolom yang diam-diam salah sesudah deploy."""
    app = io.open(os.path.join(AKAR, "web", "app.py"), encoding="utf-8").read()
    assert '"ihsg:analyze"' not in app, "kunci cache IHSG belum berversi"
    assert '"ihsg:analyze:v2"' in app


# ---------------------------------------------------------------------------
# Render sungguhan: gambar yang dikirim ke WhatsApp harus benar-benar jadi
# ---------------------------------------------------------------------------
# core/ihsg/ihsg_chart.py TIDAK punya satu pun uji yang merendernya sebelum
# hari ini, padahal ia dipanggil perintah bot (jenis="chart_ihsg"). Gambar
# yang gagal dibuat tidak muncul sebagai error di mana pun kecuali di chat
# orang yang memintanya -- dan itu baru ketahuan dari keluhan.
#
# DUA KEADAAN diuji, karena sesudah perbaikan hari ini keduanya menempuh
# cabang yang berbeda: ada ayunan (garis Fibonacci digambar) dan tanpa
# ayunan (tidak digambar, dan `fib` None di ta_chart).


@pytest.mark.parametrize("besar,keadaan", [(0.30, "ada ayunan"),
                                           (0.004, "tanpa ayunan")])
def test_chart_statis_ihsg_benar_benar_terender(besar, keadaan, tmp_path):
    import matplotlib
    matplotlib.use("Agg")
    from core.ihsg.ihsg_chart import generate_ihsg_advanced_chart
    p = generate_ihsg_advanced_chart(_deret(besar=besar))
    assert p and os.path.exists(p), keadaan
    assert os.path.getsize(p) > 10_000, f"{keadaan}: gambarnya curiga kosong"


@pytest.mark.parametrize("besar,keadaan", [(0.30, "ada ayunan"),
                                           (0.004, "tanpa ayunan")])
def test_chart_statis_ta_benar_benar_terender(besar, keadaan):
    """Cabang "tanpa ayunan" yang paling rawan: `fib` jadi None, dan tiap
    pemakaiannya harus sudah berpagar. Satu yang terlewat = TypeError saat
    menggambar, yaitu perintah bot yang gagal tanpa jejak."""
    import matplotlib
    matplotlib.use("Agg")
    from core.charts.ta_chart import generate_ta_chart
    p = generate_ta_chart(_deret(besar=besar), "UJIX")
    assert p and os.path.exists(p), keadaan
    assert os.path.getsize(p) > 10_000, f"{keadaan}: gambarnya curiga kosong"


def test_panel_teks_ta_tidak_mencetak_None():
    """Baris Fibonacci kedua tidak ada saat ayunannya tidak ada. Kalau
    None lolos ke "\n".join(), tulisan "None" tercetak di gambar yang
    dikirim ke orang."""
    src = _sumber("core/charts/ta_chart.py")
    assert 'join(b for b in info_lines if b)' in src
